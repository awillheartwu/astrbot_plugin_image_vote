from __future__ import annotations

import importlib
import json
import time
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
_avatar_module = _internal("src.avatar_service")
_activity_module = _internal("src.report_activity")
_workspace_module = _internal("src.workspace_api")
_models_module = _internal("src.models")
_character_service_module = _internal("src.character_service")

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
get_sender_display_name = _compat.get_sender_display_name
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
SessionNotFoundError = _session_manager_module.SessionNotFoundError
VoteParser = _vote_collector_module.VoteParser
VoteRouter = _vote_collector_module.VoteRouter
MessageSender = _message_sender_module.MessageSender
DirectoryReportGenerator = _report_generator_module.DirectoryReportGenerator
PillowImageProcessor = _image_processor_module.PillowImageProcessor
AiSummaryService = _ai_module.AiSummaryService
SessionStatus = _models_module.SessionStatus
character_layout = _character_service_module.character_layout
status_label = _models_module.status_label
get_logger = _logging.get_logger

logger = get_logger()

BUILD = "2026-09-13.4"
CONFIG_KEYS = frozenset(VoteConfig.__dataclass_fields__)


def _looks_like_plugin_config(raw: Mapping) -> bool:
    """AstrBot 可能按 _conf_schema.json 的分组保存配置，这里同时认分组与扁平结构。"""
    if CONFIG_KEYS.intersection(raw):
        return True
    return any(isinstance(value, Mapping) and CONFIG_KEYS.intersection(value) for value in raw.values())


@register(
    PLUGIN_NAME,
    "AstrBot Image Vote",
    "QQ 群人物图片投票插件的兼容入口与应用装配层",
    "0.13.0",
)
class ImageVotePlugin(Star):
    """Keep AstrBot events at the edge and delegate business logic to src/."""

    # 群消息热路径的短路参数：没有未结束场次的群不必每条消息都查库、读配置。
    GROUP_SESSION_CACHE_SECONDS = 5.0
    CONFIG_CHECK_INTERVAL_SECONDS = 1.0

    def __init__(self, context: Any, config: Any = None):
        super().__init__(context)
        if ASTRBOT_AVAILABLE and EVENT_MESSAGE_TYPE_SOURCE is None:
            raise RuntimeError(
                "找不到 AstrBot 的 EventMessageType，无法注册群消息监听；兼容信息：%s" % compat_report()
            )
        self.context = context
        self._page_config_object = config if callable(getattr(config, 'save_config', None)) else None
        # 报告读取、生成与清理的守卫在插件生命周期内只建一次，配置热更新重建应用层时继续沿用。
        self.report_activity = _activity_module.ReportActivity()
        self._session_probe_cache: Dict[str, float] = {}
        self._config_checked_at = 0.0
        self.workspace_api = None
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

    def _apply_config(self, config: Any = None, source: Optional[str] = None) -> None:
        raw, resolved_source = self._resolve_raw_config(config)
        self._raw_config = raw
        self._config_source = source or resolved_source
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
        configured_application = VoteApplication(
            self.settings,
            self.project_service,
            self.store,
            self.session_manager,
            self.vote_router,
            sender=self._send_candidate,
            report_generator=DirectoryReportGenerator(
                image_extension=self.settings.report_image_format,
                image_policy=self.settings.report_image_policy,
                avatar_service=_avatar_module.AvatarService(data_dir / 'avatar_cache')
                if self.settings.report_include_avatars and self.settings.report_include_participants else None,
            ),
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
            file_sender=self.adapter.send_file,
            report_activity=self.report_activity,
        )
        existing = getattr(self, 'application', None)
        if existing is None:
            self.application = configured_application
        else:
            # Running session closures retain this application instance. Refresh operation-time
            # services in place; score/interval snapshots remain on the persisted Session.
            for name in ('config', 'projects', 'router', 'sender', 'report_generator',
                         'image_processor', 'ai_summary_service', 'notifier', 'file_sender'):
                setattr(existing, name, getattr(configured_application, name))

    def _build_ai_summary_service(self):
        if not self.settings.ai_summary_enabled:
            logger.info("AI 总结已按配置关闭")
            return None
        return AiSummaryService(self._generate_ai_summary, prompt_template=self.settings.ai_prompt_template)

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
        for path in self._plugin_config_files():
            payload = self._read_config_file(path)
            if isinstance(payload, Mapping) and payload and _looks_like_plugin_config(payload):
                candidates.append((dict(payload), "配置文件 %s" % path.name))
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
        for raw, source in candidates:
            if _looks_like_plugin_config(raw) or source == "构造参数":
                return raw, source
        if candidates:
            return candidates[0]
        return {}, "defaults"

    def _plugin_config_files(self):
        """AstrBot 把插件配置存成 <data>/config/<插件名>_config.json，UI 保存后会更新这个文件。"""
        if self.store is None:
            return []
        config_dir = Path(self.store.database_path).parent.parent / "config"
        found = []
        actual_path = getattr(self._page_config_object, 'config_path', None)
        if actual_path and Path(actual_path).is_file():
            found.append(Path(actual_path))
        expected = config_dir / ("%s_config.json" % PLUGIN_NAME)
        if expected.is_file():
            found.append(expected)
        try:
            for path in sorted(config_dir.glob("*image_vote*.json")):
                if path.is_file() and path not in found:
                    found.append(path)
        except OSError:
            pass
        return found

    def _read_config_file(self, path: Path):
        cache = getattr(self, "_config_file_cache", None)
        if cache is None:
            cache = self._config_file_cache = {}
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None
        cached = cache.get(str(path))
        if cached is not None and cached[0] == stamp:
            return cached[1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        cache[str(path)] = (stamp, payload)
        return payload

    def _ensure_config(self) -> None:
        raw, source = self._resolve_raw_config()
        if raw and raw != self._raw_config:
            logger.info("检测到配置更新（来源=%s），重新装配应用层", source)
            self._apply_config(raw, source=source)

    async def initialize(self):
        await self.store.initialize()
        await self.application.recover_incomplete_sessions()
        self.application.cleanup_expired_reports()
        self.workspace_api = _workspace_module.WorkspaceAPI(self)
        if self.workspace_api.register():
            self.workspace_api.ready = True

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

        if command == "reloadconfig":
            if not is_admin_event(event):
                yield self._plain_result(event, "只有 AstrBot 管理员可以执行此操作。")
                return
            raw, _source = self._resolve_raw_config()
            if raw:
                self._apply_config(raw, source=_source)
            yield self._plain_result(event, self._config_report_text())
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
                yield self._plain_result(event, await self._control_reply(command, session))
            except SessionNotFoundError:
                yield self._plain_result(event, "当前群没有进行中的投票。")
            except Exception as exc:
                if "no recoverable paused session" in str(exc):
                    yield self._plain_result(event, "当前群没有可恢复的投票。")
                else:
                    yield self._plain_result(event, "操作失败：%s" % exc)
            return
        if command == "status":
            yield self._plain_result(event, await self._status_text(group_id))
            return
        if command in {"export", "cleanup", "purge"}:
            if not is_admin_event(event):
                yield self._plain_result(event, "只有 AstrBot 管理员可以执行此操作。")
                return
            if command == "export":
                try:
                    if argument_text.strip() not in {"", "--ai"}:
                        raise ValueError("用法：/vote export [--ai]")
                    report_path = await self.application.export_latest(group_id, regenerate_ai=argument_text.strip() == "--ai")
                    yield self._plain_result(event, "报告已生成：%s" % self._relative_output_path(report_path))
                except Exception as exc:
                    yield self._plain_result(event, "导出失败：%s" % exc)
                return
            if command == "purge":
                purge_parts = argument_text.split()
                if len(purge_parts) != 2 or purge_parts[1].lower() != "confirm":
                    yield self._plain_result(
                        event,
                        "彻底删除会同时清掉这场投票的投票记录（票与候选）和报告文件，不可恢复。\n"
                        "确认请使用：/vote purge <session_id|短ID> confirm",
                    )
                    return
                try:
                    result = await self.application.purge_session(purge_parts[0], confirm=True)
                    yield self._plain_result(
                        event,
                        "已彻底删除场次 %s：报告 %d 个、投票 %d 条、候选 %d 条。原图未受影响。"
                        % (result.short_id, result.reports, result.votes, result.candidates),
                    )
                except Exception as exc:
                    yield self._plain_result(event, "彻底删除失败：%s" % exc)
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
                result = self.application.cleanup_reports(selector, confirmed=cleanup_parts[0] == "all")
                message = "已清理 %d 个报告目录。" % result.removed
                if result.skipped:
                    message += "\n跳过 %d 个正在生成或下载的报告。" % result.skipped
                yield self._plain_result(event, message)
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
                "已开始投票：%s\n人物数量：%d，图片数量：%d\n发送方式：%s\n人物间隔：%d 秒\n评分范围：%d-%d\n预计耗时：%s"
                % (
                    session.project_name,
                    session.character_count,
                    session.candidate_count,
                    self._send_mode_label(),
                    session.interval_seconds,
                    self.settings.score_min,
                    self.settings.score_max,
                    self._estimated_duration(
                        session.character_count, session.interval_seconds, session.final_grace_seconds
                    ),
                ),
            )
        except Exception as exc:
            yield self._plain_result(event, "启动失败：%s" % exc)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: Any):
        group_id = get_group_id(event)
        sender_id = get_sender_id(event)
        if sender_id and sender_id == get_self_id(event):
            return None
        self._ensure_config_throttled()
        if not await self._group_needs_attention(group_id):
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
            get_sender_display_name(event),
            active_candidate,
            reply=self.adapter.resolve_reply(event),
            message_id=get_message_id(event),
        )
        if decision is not None and self.settings.ack_vote:
            respond = getattr(event, "send", None)
            if callable(respond):
                await respond(
                    "已记录人物「%s」评分：%d"
                    % (decision.character, decision.score)
                )
        return None

    def _ensure_config_throttled(self) -> None:
        """群消息热路径上的配置检查最多每秒一次；指令路径仍用无节流的 _ensure_config。"""
        now = time.monotonic()
        if now - self._config_checked_at < self.CONFIG_CHECK_INTERVAL_SECONDS:
            return
        self._config_checked_at = now
        self._ensure_config()

    async def _group_needs_attention(self, group_id: str) -> bool:
        """本群是否值得继续处理这条消息：有活跃场次，或有可恢复的暂停场次。

        既没有场次、又不在白名单里的群直接退出，避免每条群消息都做一次 SQLite 查询。
        只缓存「没有场次」这个结论：场次一开始就会出现在内存里的活跃表，不受缓存影响。
        结算中（FINALIZING）与准备中（PREPARING）同样不处理：截止符号已经发出，
        此后的数字与引用票一律不计，也就不必记录。
        """
        managed = await self.session_manager.active_for_group(group_id)
        if managed is not None:
            return managed.session.status in {SessionStatus.RUNNING, SessionStatus.PAUSED}
        if self.settings.allowed_group_ids and group_id not in self.settings.allowed_group_ids:
            return False
        now = time.monotonic()
        checked_at = self._session_probe_cache.get(group_id)
        if checked_at is not None and now - checked_at < self.GROUP_SESSION_CACHE_SECONDS:
            return False
        session = await self.store.latest_session_for_group(group_id)
        if session is not None and session.status == SessionStatus.PAUSED:
            self._session_probe_cache.pop(group_id, None)
            return True
        self._session_probe_cache[group_id] = now
        return False

    async def terminate(self):
        if self.workspace_api is not None:
            await self.workspace_api.close()
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
            "reloadconfig",
        }:
            return head, tail.strip() if separator else ""
        return "start", value

    @staticmethod
    def _plain_result(event: Any, text: str):
        method = getattr(event, "plain_result", None)
        return method(text) if callable(method) else text

    async def _send_candidate(self, session, candidate, image_paths):
        return await self.message_sender.send_candidate(session, candidate, image_paths)

    @staticmethod
    def _candidate_index(candidates, candidate_id):
        for candidate in candidates:
            if candidate.id == candidate_id:
                return candidate.display_index
        return 0

    @staticmethod
    def _active_candidate(session, candidates):
        """最近成功发送的图片用于引用来源；普通票实际归属 session.active_character。"""
        active_id = getattr(session, "active_candidate_id", None)
        if active_id:
            for candidate in candidates:
                if candidate.id == active_id:
                    return candidate
        if 0 < session.current_index <= len(candidates):
            return candidates[session.current_index - 1]
        return None

    async def _control_reply(self, command: str, session) -> str:
        """控制指令的确认回复：让人一眼看出触发了什么、当前进度和下一步。"""
        head = {
            "pause": "已暂停",
            "resume": "已继续",
            "finish": "已请求提前结束",
            "stop": "已取消本次投票",
        }.get(command, "已执行 %s" % command)
        candidates = await self.store.list_candidates(session.id)
        lines = [
            "%s：%s" % (head, session.project_name),
            "进度：%d / %d 张%s"
            % (session.current_index, session.candidate_count, self._character_position(session, candidates)),
        ]
        character = session.active_character
        if character:
            votes = await self.store.list_votes(session.id)
            received = sum(1 for vote in votes if vote.character == character)
            lines.append("当前人物：%s（已收 %d 票）" % (character, received))
        if command == "pause":
            lines.append("倒计时已冻结，已发出的图片仍可引用投票；执行 /vote resume 继续。")
        elif command == "resume":
            lines.append("从第 %d 张接着发送，不重发已发送的图片。" % min(session.current_index + 1, session.candidate_count))
        elif command == "finish":
            lines.append("将立即停止后续发送，按现有票数结算并生成报告。")
        elif command == "stop":
            lines.append("已收到的投票保留，不会自动生成报告；需要时执行 /vote export。")
        lines.append(
            "项目：%s · Session：%s · 状态：%s"
            % (session.project_name, session.short_id, status_label(session.status))
        )
        return "\n".join(lines)

    @staticmethod
    def _character_position(session, candidates) -> str:
        """「（第 2/17 位人物 · 该人物第 3/7 张）」；一张都没发出去时返回空串。"""
        if not candidates or session.current_index <= 0:
            return ""
        layout = character_layout(candidates)
        ordinal, image_ordinal, image_count = layout[min(session.current_index, len(candidates)) - 1]
        return "（第 %d/%d 位人物 · 该人物第 %d/%d 张）" % (
            ordinal,
            max(item[0] for item in layout),
            image_ordinal,
            image_count,
        )

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
        total = max(0, count - 1) * interval_seconds + grace_seconds
        minutes, seconds = divmod(int(total), 60)
        if minutes and seconds:
            return "约 %d 分 %d 秒" % (minutes, seconds)
        if minutes:
            return "约 %d 分钟" % minutes
        return "约 %d 秒" % seconds

    def _send_mode_label(self) -> str:
        """本轮图片怎么发：逐张，还是同一个人物合并成一条（受每条上限约束）。"""
        if not self.settings.merge_character_images:
            return "逐张发送（同一人物的图片连续发出）"
        limit = self.settings.merge_character_images_max
        if limit and limit > 0:
            return "合并发送（同一人物一条消息，每条最多 %d 张）" % limit
        return "合并发送（同一人物一条消息）"

    def _check_text(self, snapshot, project_name: str = "") -> str:
        numbered = sum(1 for item in snapshot.candidates if item.sequence_number is not None)
        plain = len(snapshot.candidates) - numbered
        character_names = {item.character or item.display_title for item in snapshot.candidates}
        character_line = "人物：%d 个" % len(character_names)
        if len(character_names) < len(snapshot.candidates):
            character_line += "（同一人物连续发送，全部图片共用一张人物票）"
        lines = [
            "项目：%s" % snapshot.project_name,
            "路径：%s" % self._project_path_label(snapshot.project_path, project_name),
            "图片：%d（带序号 %d，普通命名 %d）" % (len(snapshot.candidates), numbered, plain),
            character_line,
            "原始总大小：%.1f MB" % (snapshot.total_size / (1024.0 * 1024.0)),
            "排序方式：%s" % snapshot.sort_mode,
            "评分范围：%d-%d" % (self.settings.score_min, self.settings.score_max),
            "预计耗时：%s"
            % self._estimated_duration(
                len(character_names),
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

    def _config_report_text(self) -> str:
        """把插件当前实际生效的配置打出来，用于确认 UI 保存的值有没有传到运行中的插件。"""
        settings = self.settings
        return (
            "已重新读取配置（来源：%s）\n"
            "发送间隔：%d 秒\n"
            "发送方式：%s\n"
            "最后一张额外等待：%d 秒\n"
            "评分范围：%d-%d\n"
            "重复投票：%s\n"
            "报告模式：%s（单文件上限 %d MB）\n"
            "结束提醒：%s · 自动报告：%s · 报告发群：%s\n"
            "AI 总结：%s"
            % (
                self._config_source,
                settings.default_interval_seconds,
                self._send_mode_label(),
                settings.effective_final_grace_seconds,
                settings.score_min,
                settings.score_max,
                settings.same_user_vote_policy,
                settings.report_mode,
                settings.single_html_max_mb,
                "开" if settings.notify_on_finish else "关",
                "开" if settings.auto_report_on_finish else "关",
                "开" if settings.send_report_html else "关",
                "开" if settings.ai_summary_enabled else "关",
            )
        )

    async def _status_text(self, group_id):
        managed = await self.session_manager.active_for_group(group_id)
        session = managed.session if managed is not None else await self.store.latest_session_for_group(group_id)
        if session is None:
            return "当前群没有投票记录。"
        candidates = await self.store.list_candidates(session.id)
        votes = await self.store.list_votes(session.id)
        current_character = session.active_character
        current_votes = sum(1 for vote in votes if current_character and vote.character == current_character)
        next_candidate = candidates[session.current_index] if session.current_index < len(candidates) else None
        countdown = managed.control.seconds_until_next if managed is not None else None
        return (
            "项目：%s\n"
            "状态：%s\n"
            "图片进度：%d / %d 张%s\n"
            "当前人物：%s\n"
            "本人物已收：%d 票\n"
            "总投票：%d\n"
            "下一步：%s\n"
            "Session：%s"
            % (
                session.project_name,
                status_label(session.status),
                session.current_index,
                session.candidate_count,
                self._character_position(session, candidates),
                current_character or "尚未发送",
                current_votes,
                len(votes),
                self._next_step_label(session, candidates, next_candidate, countdown),
                session.short_id,
            )
        )

    def _next_step_label(self, session, candidates, next_candidate, countdown) -> str:
        """下一张（合并模式下是下一组）会发什么，以及还要等多少秒。"""
        if next_candidate is None:
            return "无（本场图片已发完）"
        layout = character_layout(candidates)
        start = session.current_index
        ordinal, image_ordinal, image_count = layout[start]
        character = next_candidate.character or next_candidate.display_title
        limit = self.settings.merge_character_images_max if self.settings.merge_character_images else 0
        span = 1
        while limit > 0 and span < limit and start + span < len(candidates) and layout[start + span][0] == ordinal:
            span += 1
        if span > 1:
            body = "第 %d-%d/%d 张（本条 %d 张）" % (image_ordinal, image_ordinal + span - 1, image_count, span)
        else:
            body = "第 %d/%d 张" % (image_ordinal, image_count)
        label = "%s %s · 第 %d/%d 位人物" % (character, body, ordinal, max(item[0] for item in layout))
        if countdown is not None:
            label += " · 约 %d 秒后" % max(0, int(round(countdown)))
        return label
