from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


def _internal(module_name: str):
    """AstrBot 以 data.plugins.<插件名>.main 加载本文件，本地测试以顶层 main 导入。"""
    if __package__:
        return importlib.import_module("." + module_name, __package__)
    return importlib.import_module(module_name)


_compat = _internal("src.astrbot_compat")
_logging = _internal("src.logging_utils")
_adapter_module = _internal("src.astrbot_adapter")
_application_module = _internal("src.application")
_config_module = _internal("src.config")
_persistence_module = _internal("src.persistence")
_project_service_module = _internal("src.project_service")
_project_registry_module = _internal("src.project_registry")
_session_manager_module = _internal("src.session_manager")
_vote_collector_module = _internal("src.vote_collector")
_message_sender_module = _internal("src.message_sender")
_report_generator_module = _internal("src.report_generator")
_image_processor_module = _internal("src.image_processor")
_ai_module = _internal("src.ai_summary_service")
_models_module = _internal("src.models")

register = _compat.register
filter = _compat.filter
Star = _compat.Star
EventMessageType = _compat.EventMessageType
ASTRBOT_AVAILABLE = _compat.ASTRBOT_AVAILABLE
EVENT_MESSAGE_TYPE_SOURCE = _compat.EVENT_MESSAGE_TYPE_SOURCE
PLUGIN_NAME = _compat.PLUGIN_NAME
compat_report = _compat.compat_report
get_event_text = _compat.get_event_text
get_group_id = _compat.get_group_id
get_message_id = _compat.get_message_id
get_plugin_data_dir = _compat.get_plugin_data_dir
get_sender_id = _compat.get_sender_id
get_sender_name = _compat.get_sender_name
get_self_id = _compat.get_self_id
get_unified_message_origin = _compat.get_unified_message_origin
is_admin_event = _compat.is_admin_event

AstrBotAdapter = _adapter_module.AstrBotAdapter
VoteApplication = _application_module.VoteApplication
VoteConfig = _config_module.VoteConfig
SQLiteStore = _persistence_module.SQLiteStore
ProjectService = _project_service_module.ProjectService
ProjectRegistry = _project_registry_module.ProjectRegistry
SessionManager = _session_manager_module.SessionManager
VoteParser = _vote_collector_module.VoteParser
VoteRouter = _vote_collector_module.VoteRouter
MessageSender = _message_sender_module.MessageSender
DirectoryReportGenerator = _report_generator_module.DirectoryReportGenerator
PillowImageProcessor = _image_processor_module.PillowImageProcessor
AiSummaryService = _ai_module.AiSummaryService
SessionStatus = _models_module.SessionStatus
get_logger = _logging.get_logger

logger = get_logger()

BUILD = "2026-09-12.4"
CONFIG_KEYS = frozenset(VoteConfig.__dataclass_fields__)


def _looks_like_plugin_config(raw: Mapping) -> bool:
    """AstrBot 可能按 _conf_schema.json 的分组保存配置，这里同时认分组与扁平结构。"""
    if CONFIG_KEYS.intersection(raw):
        return True
    return any(isinstance(value, Mapping) and CONFIG_KEYS.intersection(value) for value in raw.values())


@register(
    PLUGIN_NAME,
    "AstrBot Image Vote",
    "QQ 群图片轮播投票插件的兼容入口与应用装配层",
    "0.8.0",
)
class ImageVotePlugin(Star):
    """Keep AstrBot events at the edge and delegate business logic to src/."""

    def __init__(self, context: Any, config: Any = None):
        super().__init__(context)
        if ASTRBOT_AVAILABLE and EVENT_MESSAGE_TYPE_SOURCE is None:
            raise RuntimeError(
                "找不到 AstrBot 的 EventMessageType，无法注册群消息监听；兼容信息：%s" % compat_report()
            )
        self.context = context
        self.store = None
        self.session_manager = None
        self.adapter = None
        self._raw_config: Dict[str, Any] = {}
        self._config_source = "defaults"
        self._apply_config(config)
        logger.info(
            "插件装配完成：构建=%s，%s，配置来源=%s，数据目录=%s，登记项目=%d",
            BUILD,
            compat_report(),
            self._config_source,
            self.store.database_path,
            len(self.project_service.list_registered()),
        )

    def _apply_config(self, config: Any = None) -> None:
        raw, source = self._resolve_raw_config(config)
        self._raw_config = raw
        self._config_source = source
        self.settings = VoteConfig.from_mapping(raw)
        data_dir = get_plugin_data_dir(self.context, Path(self.settings.output_root).expanduser())
        if self.store is None:
            self.store = SQLiteStore(data_dir / "vote.db")
        self.project_registry = ProjectRegistry(Path(self.store.database_path).parent / "projects.json")
        self.project_service = ProjectService(Path(self.settings.input_root), registry=self.project_registry)
        if self.session_manager is None:
            self.session_manager = SessionManager()
        if self.adapter is None:
            self.adapter = AstrBotAdapter(self.context)
        self.message_sender = MessageSender(
            self.adapter.send_vote_message,
            max_retries=self.settings.max_send_retries,
            retry_base_seconds=self.settings.send_retry_base_seconds,
        )
        self.vote_router = VoteRouter(
            VoteParser(self.settings.score_min, self.settings.score_max),
            allow_quoted_vote_after_window=self.settings.allow_quoted_vote_after_window,
        )
        self.application = VoteApplication(
            self.settings,
            self.project_service,
            self.store,
            self.session_manager,
            self.vote_router,
            sender=self._send_candidate,
            report_generator=DirectoryReportGenerator(image_extension=self.settings.report_image_format),
            image_processor=PillowImageProcessor(
                image_format=self.settings.report_image_format,
                max_width=self.settings.report_image_max_width,
                max_height=self.settings.report_image_max_height,
                quality=self.settings.report_image_quality,
                thumbnail_width=self.settings.thumbnail_width,
                thumbnail_quality=self.settings.thumbnail_quality,
                strip_metadata=self.settings.strip_metadata,
            ),
            ai_summary_service=self._build_ai_summary_service(),
            notifier=self.adapter.send_text,
        )

    def _build_ai_summary_service(self):
        if not self.settings.ai_summary_enabled:
            logger.info("AI 总结已按配置关闭")
            return None
        return AiSummaryService(self._generate_ai_summary)

    async def _generate_ai_summary(self, prompt: str, umo: Optional[str] = None) -> str:
        provider_id = self.settings.ai_provider_id
        if not provider_id and umo:
            getter = getattr(self.context, "get_current_chat_provider_id", None)
            if callable(getter):
                try:
                    provider_id = await getter(umo)
                except Exception as exc:
                    logger.warning("获取当前会话 AI Provider 失败：%s", exc)
        if not provider_id:
            logger.warning("没有可用的 AI Provider，跳过 AI 总结")
            return ""
        generator = getattr(self.context, "llm_generate", None)
        if not callable(generator):
            logger.warning("当前 AstrBot 没有 llm_generate，跳过 AI 总结")
            return ""
        response = await generator(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt="你只根据给定统计生成简短中文总结，不要编造或修改任何数字。",
        )
        text = self._extract_completion(response)
        if not text:
            logger.warning("AI 返回内容为空，报告按纯统计生成")
        return text

    @staticmethod
    def _extract_completion(response: Any) -> str:
        for attribute in ("completion_text", "text", "content"):
            value = getattr(response, attribute, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _resolve_raw_config(self, config: Any = None):
        candidates = []
        if isinstance(config, Mapping) and config:
            candidates.append((dict(config), "构造参数"))
        attribute = getattr(self, "config", None)
        if isinstance(attribute, Mapping) and attribute:
            candidates.append((dict(attribute), "插件实例属性"))
        getter = getattr(self.context, "get_config", None)
        if callable(getter):
            for args in ((), (PLUGIN_NAME,)):
                try:
                    value = getter(*args)
                except Exception:
                    continue
                if isinstance(value, Mapping) and value and _looks_like_plugin_config(value):
                    candidates.append((dict(value), "context.get_config"))
        manager = getattr(self.context, "astrbot_config_mgr", None)
        if manager is not None:
            for name in ("get_conf", "get_plugin_config", "get"):
                method = getattr(manager, name, None)
                if not callable(method):
                    continue
                try:
                    value = method(PLUGIN_NAME)
                except Exception:
                    continue
                if isinstance(value, Mapping) and value and _looks_like_plugin_config(value):
                    candidates.append((dict(value), "astrbot_config_mgr.%s" % name))
        if self.store is not None:
            path = Path(self.store.database_path).parent.parent / "config" / ("%s_config.json" % PLUGIN_NAME)
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
                if isinstance(payload, Mapping) and payload and _looks_like_plugin_config(payload):
                    candidates.append((dict(payload), "配置文件 %s" % path))
        for raw, source in candidates:
            if _looks_like_plugin_config(raw) or source == "构造参数":
                return raw, source
        if candidates:
            return candidates[0]
        return {}, "defaults"

    def _ensure_config(self) -> None:
        raw, source = self._resolve_raw_config()
        if raw and raw != self._raw_config:
            logger.info("检测到配置更新（来源=%s），重新装配应用层", source)
            self._apply_config(raw)

    async def initialize(self):
        await self.store.initialize()
        await self.application.recover_incomplete_sessions()
        self.application.cleanup_expired_reports()

    @filter.command("vote")
    async def vote_command(self, event: Any):
        """Parse commands at the edge and delegate state changes to VoteApplication."""
        self._ensure_config()
        command, argument_text = self._parse_command(get_event_text(event))
        if not command:
            yield self._plain_result(event, "用法：/vote <项目名>，或 /vote list、/vote check <项目名>")
            return
        if command == "list":
            registered = self.project_service.list_registered()
            projects = self.project_service.list_projects()
            lines = []
            if registered:
                lines.append("注册项目：" + "、".join(registered))
            if projects:
                lines.append("目录项目：" + "、".join(projects))
            yield self._plain_result(event, "\n".join(lines) if lines else "暂无项目")
            return
        if command == "check":
            if not argument_text:
                yield self._plain_result(event, "用法：/vote check <项目名>")
                return
            try:
                options = self.project_service.resolve_options(argument_text)
                recursive = bool(options.get("recursive", self.settings.recursive_scan))
                snapshot = self.project_service.inspect(argument_text, recursive)
                text = self._check_text(snapshot, argument_text)
            except Exception as exc:
                text = "预检失败：%s" % exc
            yield self._plain_result(event, text)
            return

        if command in {"register", "unregister", "projects"}:
            if not is_admin_event(event):
                yield self._plain_result(event, "只有 AstrBot 管理员可以管理项目登记表。")
                return
            yield self._plain_result(event, self._registry_command_text(command, argument_text))
            return

        group_id = get_group_id(event)
        if not group_id:
            yield self._plain_result(event, "该插件只支持 QQ 群消息。")
            return
        if command in {"pause", "resume", "stop", "finish"}:
            if not is_admin_event(event):
                yield self._plain_result(event, "只有 AstrBot 管理员可以执行此操作。")
                return
            try:
                session = await getattr(self.application, command)(group_id)
                yield self._plain_result(event, "Session %s：%s" % (session.short_id, session.status.value))
            except Exception as exc:
                yield self._plain_result(event, "操作失败：%s" % exc)
            return
        if command == "status":
            yield self._plain_result(event, await self._status_text(group_id))
            return
        if command in {"export", "cleanup"}:
            if not is_admin_event(event):
                yield self._plain_result(event, "只有 AstrBot 管理员可以执行此操作。")
                return
            if command == "export":
                try:
                    report_path = await self.application.export_latest(group_id)
                    yield self._plain_result(event, "报告已生成：%s" % self._relative_output_path(report_path))
                except Exception as exc:
                    yield self._plain_result(event, "导出失败：%s" % exc)
                return
            cleanup_parts = argument_text.split()
            if not cleanup_parts:
                yield self._plain_result(event, "用法：/vote cleanup <session_id|项目名|all confirm>")
                return
            if cleanup_parts[0] == "all" and cleanup_parts[1:] != ["confirm"]:
                yield self._plain_result(event, "清理全部报告请使用：/vote cleanup all confirm")
                return
            selector = cleanup_parts[0] if cleanup_parts[0] == "all" else argument_text.strip()
            try:
                removed = self.application.cleanup_reports(selector, confirmed=cleanup_parts[0] == "all")
                yield self._plain_result(event, "已清理 %d 个报告目录。" % removed)
            except Exception as exc:
                yield self._plain_result(event, "清理失败：%s" % exc)
            return

        if not argument_text:
            yield self._plain_result(event, "用法：/vote <项目名>")
            return
        if self.settings.admin_only_start and not is_admin_event(event):
            yield self._plain_result(event, "只有 AstrBot 管理员可以启动投票。")
            return
        try:
            session = await self.application.start_session(
                group_id, get_unified_message_origin(event), argument_text
            )
            yield self._plain_result(
                event,
                "已开始投票：%s\n图片数量：%d\n发送间隔：%d 秒\n评分范围：%d-%d\n预计耗时：%s"
                % (
                    session.project_name,
                    session.candidate_count,
                    session.interval_seconds,
                    self.settings.score_min,
                    self.settings.score_max,
                    self._estimated_duration(
                        session.candidate_count, session.interval_seconds, session.final_grace_seconds
                    ),
                ),
            )
        except Exception as exc:
            yield self._plain_result(event, "启动失败：%s" % exc)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: Any):
        self._ensure_config()
        group_id = get_group_id(event)
        sender_id = get_sender_id(event)
        if sender_id and sender_id == get_self_id(event):
            return None
        managed = await self.session_manager.active_for_group(group_id)
        if managed is None:
            persisted = await self.store.latest_session_for_group(group_id)
            if persisted is None or persisted.status != SessionStatus.PAUSED:
                return None
            session = persisted
        else:
            session = managed.session
        candidates = await self.store.list_candidates(session.id)
        if not candidates:
            return None
        active_candidate = self._active_candidate(session, candidates)
        decision = await self.application.record_vote(
            session,
            candidates,
            get_event_text(event),
            sender_id,
            get_sender_name(event),
            active_candidate,
            reply=self.adapter.resolve_reply(event),
            message_id=get_message_id(event),
        )
        if decision is not None and self.settings.ack_vote:
            respond = getattr(event, "send", None)
            if callable(respond):
                await respond(
                    "已记录第 %d 张图片评分：%d"
                    % (self._candidate_index(candidates, decision.candidate_id), decision.score)
                )
        return None

    async def terminate(self):
        await self.session_manager.shutdown()
        await self.store.close()

    @staticmethod
    def _parse_command(text: str):
        value = (text or "").strip()
        lowered = value.lower()
        for prefix in ("/vote", "vote"):
            if lowered == prefix:
                return "", ""
            if lowered.startswith(prefix + " ") or lowered.startswith(prefix + "\t"):
                value = value[len(prefix):].strip()
                break
        if not value:
            return "", ""
        head, separator, tail = value.partition(" ")
        head = head.lower()
        if head in {
            "list",
            "check",
            "status",
            "pause",
            "resume",
            "stop",
            "finish",
            "export",
            "cleanup",
            "register",
            "unregister",
            "projects",
        }:
            return head, tail.strip() if separator else ""
        return "start", value

    @staticmethod
    def _plain_result(event: Any, text: str):
        method = getattr(event, "plain_result", None)
        return method(text) if callable(method) else text

    async def _send_candidate(self, session, candidate, image_path):
        return await self.message_sender.send_candidate(session, candidate, image_path)

    @staticmethod
    def _candidate_index(candidates, candidate_id):
        for candidate in candidates:
            if candidate.id == candidate_id:
                return candidate.display_index
        return 0

    @staticmethod
    def _active_candidate(session, candidates):
        """投票目标 = 最近一次成功发送的图片；发送失败的图片不会成为目标。"""
        active_id = getattr(session, "active_candidate_id", None)
        if active_id:
            for candidate in candidates:
                if candidate.id == active_id:
                    return candidate
        if 0 < session.current_index <= len(candidates):
            return candidates[session.current_index - 1]
        return None

    def _relative_output_path(self, path):
        try:
            output_root = Path(self.settings.output_root).expanduser().resolve()
            return str(Path(path).expanduser().resolve().relative_to(output_root))
        except ValueError:
            return Path(path).name

    @staticmethod
    def _estimated_duration(count: int, interval_seconds: int, grace_seconds: int) -> str:
        if count <= 0:
            return "无"
        total = max(0, count - 1) * interval_seconds + max(grace_seconds, interval_seconds)
        minutes, seconds = divmod(int(total), 60)
        if minutes and seconds:
            return "约 %d 分 %d 秒" % (minutes, seconds)
        if minutes:
            return "约 %d 分钟" % minutes
        return "约 %d 秒" % seconds

    def _check_text(self, snapshot, project_name: str = "") -> str:
        numbered = sum(1 for item in snapshot.candidates if item.sequence_number is not None)
        plain = len(snapshot.candidates) - numbered
        lines = [
            "项目：%s" % snapshot.project_name,
            "路径：%s" % self._project_path_label(snapshot.project_path, project_name),
            "图片：%d（带序号 %d，普通命名 %d）" % (len(snapshot.candidates), numbered, plain),
            "原始总大小：%.1f MB" % (snapshot.total_size / (1024.0 * 1024.0)),
            "排序方式：%s" % snapshot.sort_mode,
            "评分范围：%d-%d" % (self.settings.score_min, self.settings.score_max),
            "预计耗时：%s"
            % self._estimated_duration(
                len(snapshot.candidates),
                self.settings.default_interval_seconds,
                self.settings.effective_final_grace_seconds,
            ),
            "报告主图：%s，最长边 %d，质量 %d；缩略图宽 %d"
            % (
                self.settings.report_image_format,
                max(self.settings.report_image_max_width, self.settings.report_image_max_height),
                self.settings.report_image_quality,
                self.settings.thumbnail_width,
            ),
            "报告体积估算：约 %.1f~%.1f MB（按派生图占原图 10%%~25%% 估算）"
            % (
                snapshot.total_size * 0.10 / (1024.0 * 1024.0),
                snapshot.total_size * 0.25 / (1024.0 * 1024.0),
            ),
        ]
        lines.append(
            "前 5 张："
            + (
                "；".join(
                    "#%03d %s" % (item.display_index, item.source_filename) for item in snapshot.candidates[:5]
                )
                or "无"
            )
        )
        lines.append(
            "后 5 张："
            + (
                "；".join(
                    "#%03d %s" % (item.display_index, item.source_filename) for item in snapshot.candidates[-5:]
                )
                or "无"
            )
        )
        lines.append("非法/忽略文件：%d" % len(snapshot.invalid_files))
        if snapshot.invalid_files:
            lines.append("  " + "；".join(snapshot.invalid_files[:5]))
        lines.append("警告：" + ("；".join(snapshot.warnings) if snapshot.warnings else "无"))
        return "\n".join(lines)

    def _relative_project_path(self, project_path: str) -> str:
        try:
            return str(Path(project_path).relative_to(Path(self.settings.input_root).expanduser().resolve()))
        except ValueError:
            return Path(project_path).name

    def _project_path_label(self, project_path: str, project_name: str) -> str:
        if project_name and project_name in self.project_service.list_registered():
            return "%s（已登记目录，绝对路径见 /vote projects）" % project_name
        return self._relative_project_path(project_path)

    def _registry_command_text(self, command: str, argument: str) -> str:
        registry = self.project_registry
        if command == "projects":
            entries = registry.entries()
            if not entries:
                return "还没有登记项目。用法：/vote register <项目名> <容器内绝对路径>"
            lines = ["已登记 %d 个项目：" % len(entries)]
            for name in sorted(entries):
                entry = entries[name]
                extras = []
                if entry.get("interval_seconds"):
                    extras.append("间隔 %s 秒" % entry["interval_seconds"])
                if entry.get("recursive"):
                    extras.append("递归")
                suffix = ("（%s）" % "、".join(extras)) if extras else ""
                lines.append("· %s → %s%s" % (name, entry.get("path"), suffix))
            return "\n".join(lines)

        name, _separator, path_text = argument.partition(" ")
        name = name.strip()
        if not name:
            if command == "register":
                return "用法：/vote register <项目名> <容器内绝对路径>"
            return "用法：/vote unregister <项目名>"
        if command == "unregister":
            try:
                removed = registry.unregister(name)
            except Exception as exc:
                return "操作失败：%s" % exc
            return ("已取消登记：%s" % name) if removed else ("没有登记过 %s" % name)

        path_text = path_text.strip().strip('"').strip("'")
        if not path_text:
            return "用法：/vote register <项目名> <容器内绝对路径>"
        try:
            registry.register(name, Path(path_text))
        except Exception as exc:
            return "登记失败：%s" % exc
        return "已登记：%s → %s" % (name, registry.entries()[name]["path"])

    async def _status_text(self, group_id):
        managed = await self.session_manager.active_for_group(group_id)
        session = managed.session if managed is not None else await self.store.latest_session_for_group(group_id)
        if session is None:
            return "当前群没有投票记录。"
        candidates = await self.store.list_candidates(session.id)
        votes = await self.store.list_votes(session.id)
        current = self._active_candidate(session, candidates)
        current_votes = sum(1 for vote in votes if current is not None and vote.candidate_id == current.id)
        next_candidate = candidates[session.current_index] if session.current_index < len(candidates) else None
        countdown = managed.control.seconds_until_next if managed is not None else None
        current_label = "尚未发送" if current is None else "#%03d %s" % (current.display_index, current.display_title)
        if countdown is not None:
            next_label = "%d 秒后" % max(0, int(round(countdown)))
        elif next_candidate is not None:
            next_label = "#%03d %s" % (next_candidate.display_index, next_candidate.display_title)
        else:
            next_label = "无"
        return "项目：%s\n状态：%s\n进度：%d / %d\n当前：%s\n本图已投：%d 人\n总投票：%d\n下一张：%s\nSession：%s" % (
            session.project_name,
            session.status.value,
            session.current_index,
            session.candidate_count,
            current_label,
            current_votes,
            len(votes),
            next_label,
            session.short_id,
        )
