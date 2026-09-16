from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from .config import VoteConfig
from .character_service import character_layout, character_of
from .ai_summary_service import AiSummaryService, build_summary_statistics
from .logging_utils import get_logger
from .models import Candidate, SendContext, SendStatus, Session, SessionStatus, Vote, VoteDecision
from .path_guard import PathGuard
from .persistence import SQLiteStore
from .project_service import ProjectService
from .reply_resolver import ReplyPayload
from .session_manager import SessionAlreadyActiveError, SessionManager, SessionNotFoundError
from .report_generator import CleanupResult, ReportCleanupService
from .report_activity import ReportActivity
from .statistics_service import calculate_statistics
from .vote_collector import VoteRouter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PurgeResult:
    """彻底删除的结果：报告目录数、票数、候选数。"""

    session_id: str
    short_id: str
    reports: int = 0
    votes: int = 0
    candidates: int = 0


logger = get_logger()


class VoteApplication:
    """Framework-neutral application service for command handlers and event listeners."""

    def __init__(
        self,
        config: VoteConfig,
        projects: ProjectService,
        store: SQLiteStore,
        sessions: SessionManager,
        router: VoteRouter,
        sender: Optional[Callable[[Session, Candidate, Path], Awaitable[Optional[str]]]] = None,
        report_generator: Optional[object] = None,
        image_processor: Optional[object] = None,
        ai_summary_service: Optional[AiSummaryService] = None,
        notifier: Optional[Callable[[str, str], Awaitable[None]]] = None,
        file_sender: Optional[Callable[[str, Path, str], Awaitable[None]]] = None,
        report_activity: Optional[ReportActivity] = None,
    ):
        self.config = config
        self.projects = projects
        self.store = store
        self.sessions = sessions
        self.router = router
        self.sender = sender
        self.report_generator = report_generator
        self.image_processor = image_processor
        self.ai_summary_service = ai_summary_service
        self.notifier = notifier
        self.file_sender = file_sender
        # 报告读取、生成与清理的互斥由应用层持有，网页工作区与群命令共用同一份状态。
        self.report_activity = report_activity or ReportActivity()
        self._range_warned: set = set()

    async def prepare_session(self, group_id: str, umo: str, project_name: str) -> Session:
        if self.config.allowed_group_ids and group_id not in self.config.allowed_group_ids:
            raise PermissionError("group is not allowed to use image voting")
        if await self.sessions.active_for_group(group_id) is not None:
            raise SessionAlreadyActiveError("group already has an active vote session")
        options = self.projects.resolve_options(project_name)
        recursive = bool(options.get("recursive", self.config.recursive_scan))
        snapshot = self.projects.inspect(project_name, recursive)
        if not snapshot.candidates:
            raise ValueError("project contains no supported images")
        output_root = Path(self.config.output_root).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_root.is_dir() or not os.access(str(output_root), os.W_OK):
            raise PermissionError("output directory is not writable")
        session_id = uuid.uuid4().hex
        interval_seconds = int(options.get("interval_seconds") or self.config.default_interval_seconds)
        session = Session(
            id=session_id,
            short_id=secrets.token_hex(4).upper(),
            group_id=group_id,
            umo=umo,
            project_name=project_name.strip() or snapshot.project_name,
            project_path=snapshot.project_path,
            status=SessionStatus.PREPARING,
            interval_seconds=interval_seconds,
            final_grace_seconds=max(self.config.effective_final_grace_seconds, interval_seconds),
            score_min=self.config.score_min,
            score_max=self.config.score_max,
            candidate_count=len(snapshot.candidates),
            character_count=len({character_of(item) for item in snapshot.candidates}),
            created_at=utc_now(),
        )
        candidates = tuple(
            Candidate(
                id="%s:%s" % (session.id, item.id),
                session_id=session.id,
                display_index=item.display_index,
                source_relative_path=item.source_relative_path,
                source_filename=item.source_filename,
                display_title=item.display_title,
                sequence_number=item.sequence_number,
                source_size=item.source_size,
                character=item.character,
            )
            for item in snapshot.candidates
        )
        await self.store.save_session(session)
        await self.store.save_candidates(candidates)
        for warning in snapshot.warnings:
            logger.warning("项目 %s：%s", snapshot.project_name, warning)
        logger.info(
            "创建 session %s（群 %s，项目 %s，图片 %d 张，排序 %s）",
            session.short_id,
            group_id,
            session.project_name,
            len(candidates),
            snapshot.sort_mode,
        )
        return session

    async def start_session(self, group_id: str, umo: str, project_name: str) -> Session:
        if self.sender is None:
            raise RuntimeError("a platform sender is required to start a session")
        session = await self.prepare_session(group_id, umo, project_name)
        try:
            await self._start_existing_session(session)
        except SessionAlreadyActiveError:
            session.status = SessionStatus.CANCELLED
            session.error_message = "another session became active for this group"
            session.finished_at = utc_now()
            await self.store.save_session(session)
            raise
        return session

    async def _start_existing_session(self, session: Session, finish_immediately: bool = False) -> None:
        candidates = await self.store.list_candidates(session.id)

        async def runner(current_session: Session, control) -> None:
            if finish_immediately:
                control.request_finish()
            await self.run_session(current_session, candidates, control)

        await self.sessions.start(session, runner)

    async def run_session(self, session: Session, candidates: Sequence[Candidate], control) -> None:
        await self._heal_project_name(session)
        session.status = SessionStatus.RUNNING
        session.started_at = session.started_at or utc_now()
        await self.store.save_session(session)
        logger.info(
            "session %s 开始轮播：从第 %d 张继续，共 %d 张，间隔 %d 秒",
            session.short_id,
            session.current_index + 1,
            len(candidates),
            session.interval_seconds,
        )
        try:
            consecutive_failures = 0
            merge_character_images = bool(getattr(self.config, "merge_character_images", False))
            merge_limit = int(getattr(self.config, "merge_character_images_max", 0) or 0)
            layout = character_layout(candidates)
            sent_through = session.current_index
            for index in range(session.current_index, len(candidates)):
                if index < sent_through:
                    continue
                await control.wait_if_paused()
                if control.stop_requested:
                    await self._cancel_session(session)
                    return
                if control.finish_requested:
                    logger.info("session %s 收到 finish，停止后续图片发送", session.short_id)
                    break
                candidate = candidates[index]
                candidate_character = character_of(candidate)
                previous_character = character_of(candidates[index - 1]) if index > 0 else None
                if candidate_character != previous_character:
                    # 上个人物的窗口已结束；下一人物首张成功前不接收普通数字票。
                    session.active_candidate_id = None
                    session.active_character = None
                    await self.store.save_session(session)
                group = (
                    self._character_image_group(candidates, index)
                    if merge_character_images
                    else [candidate]
                )
                if merge_character_images and merge_limit > 0:
                    # 一条消息里的图片数有上限：帧太大时 NapCat/QQ 会直接断开连接。
                    group = group[:merge_limit]
                candidate.send_context = self._send_context(
                    layout, index, len(group), merge_character_images, merge_limit
                )
                paths = [
                    PathGuard(Path(session.project_path)).ensure_within(
                        Path(session.project_path) / member.source_relative_path, allow_root=False
                    )
                    for member in group
                ]
                started_at = asyncio.get_event_loop().time()
                try:
                    timeout = float(getattr(self.config, "send_timeout_seconds", 0) or 0)
                    if timeout > 0:
                        await asyncio.wait_for(
                            self.sender(session, candidate, paths), timeout=timeout
                        )
                    else:
                        await self.sender(session, candidate, paths)
                    for member in group:
                        member.send_status = SendStatus.SENT
                        member.sent_at = utc_now()
                    session.active_candidate_id = candidate.id
                    session.active_character = candidate_character
                    consecutive_failures = 0
                    logger.debug(
                        "session %s 已发送第 %d-%d/%d 张（%s）：%s",
                        session.short_id,
                        candidate.display_index,
                        group[-1].display_index,
                        len(candidates),
                        candidate_character,
                        "、".join(member.source_relative_path for member in group),
                    )
                except Exception as exc:
                    detail = (
                        "发送超时（超过 %s 秒未返回）" % timeout
                        if isinstance(exc, asyncio.TimeoutError)
                        else str(exc)
                    )
                    for member in group:
                        member.send_status = SendStatus.SEND_FAILED
                    session.error_message = detail
                    consecutive_failures += 1
                    logger.warning(
                        "session %s 第 %d-%d 张这一条发送失败（连续第 %d 条）；本人物已有成功图片时仍继续接收人物票：%s",
                        session.short_id,
                        candidate.display_index,
                        group[-1].display_index,
                        consecutive_failures,
                        detail,
                    )
                elapsed = asyncio.get_event_loop().time() - started_at
                logger.debug(
                    "session %s 第 %d-%d 张发送耗时 %.1f 秒",
                    session.short_id,
                    candidate.display_index,
                    group[-1].display_index,
                    elapsed,
                )
                session.current_index = index + len(group)
                sent_through = session.current_index
                is_last = session.current_index >= len(candidates)
                next_is_same_character = (
                    not merge_character_images
                    and not is_last
                    and character_of(candidates[session.current_index]) == candidate_character
                )
                if session.interval_seconds > 0 and not next_is_same_character and not is_last:
                    self._log_send_pace(session, candidate, group, elapsed)
                await self.store.save_candidates(group)
                await self.store.save_session(session)
                limit = self.config.send_failure_pause_threshold
                if limit and consecutive_failures >= limit:
                    await self._pause_after_send_failures(session, consecutive_failures)
                    return
                if control.stop_requested:
                    await self._cancel_session(session)
                    return
                if control.finish_requested:
                    break
                # 同一人物的图片连续发送；最后一张成功发送后才开始完整人物投票间隔。
                if not next_is_same_character:
                    await control.wait_for_interval(self._next_wait_seconds(session, is_last))

            session.status = SessionStatus.FINALIZING
            session.finished_at = utc_now()
            await self.store.save_session(session)
            logger.info("session %s 进入 FINALIZING，已发送 %d 张", session.short_id, session.current_index)
            if self.config.notify_on_finish:
                await self._notify_cutoff(session)
            votes = await self.store.list_votes(session.id)
            statistics = calculate_statistics(
                candidates,
                votes,
                score_min=session.score_min,
                score_max=session.score_max,
            )
            if self.ai_summary_service is not None and self.config.ai_summary_enabled:
                summary = await self.ai_summary_service.summarize(
                    build_summary_statistics(
                        session.project_name,
                        statistics,
                        top_n=self.config.ai_top_n,
                        bottom_n=self.config.ai_bottom_n,
                        score_min=session.score_min,
                        score_max=session.score_max,
                    ),
                    umo=session.umo,
                )
                if summary:
                    session.ai_summary = summary
                    logger.info("session %s AI 总结完成（%d 字）", session.short_id, len(summary))
                else:
                    logger.warning("session %s AI 总结为空，继续按纯统计生成报告", session.short_id)
            session.status = SessionStatus.COMPLETED
            await self.store.save_session(session)
            report_enabled = (
                self.config.auto_report_on_finish
                and self.report_generator is not None
                and self.image_processor is not None
            )
            if self.config.notify_on_finish:
                await self._notify_finish(session, statistics, report_enabled)
            if report_enabled:
                logger.info("session %s 生成报告：模式=%s", session.short_id, self.config.report_mode)
                try:
                    report_path = await self._generate_report(session, candidates, statistics)
                    session.output_path = str(report_path)
                    if session.error_message and session.error_message.startswith('report generation failed:'):
                        session.error_message = None
                    await self.store.save_session(session)
                    logger.info("session %s 报告已生成：%s", session.short_id, report_path)
                    if self.config.send_report_html and self.config.report_mode == "single_html":
                        await self._send_report_file(session, report_path)
                    if self.config.notify_on_finish:
                        await self._notify(
                            session.umo,
                            "报告已生成：%s/%s" % (report_path.parent.name, report_path.name),
                        )
                except Exception as exc:
                    session.error_message = "report generation failed: %s" % exc
                    await self.store.save_session(session)
                    logger.error("session %s 报告生成失败，可用 /vote export 重试：%s", session.short_id, exc)
                    if self.config.notify_on_finish:
                        await self._notify(session.umo, "报告生成失败，可由管理员执行 /vote export 重试。")
        except asyncio.CancelledError:
            if control.stop_requested:
                await self._cancel_session(session)
                logger.info("session %s 已按 /vote stop 取消", session.short_id)
            else:
                await self._pause_for_recovery(session)
            raise
        except Exception as exc:
            session.status = SessionStatus.FAILED
            session.error_message = str(exc)
            session.finished_at = utc_now()
            await self.store.save_session(session)
            logger.error("session %s 运行失败：%s", session.short_id, exc)
            raise

    async def _cancel_session(self, session: Session) -> None:
        session.status = SessionStatus.CANCELLED
        session.finished_at = utc_now()
        await self.store.save_session(session)

    async def _pause_for_recovery(self, session: Session) -> None:
        """插件卸载/重载导致的停止：留下可恢复的暂停态，等管理员 /vote resume。"""
        session.status = SessionStatus.PAUSED
        session.error_message = "插件卸载或重载导致轮播中断，已暂停；执行 /vote resume 可继续。"
        await self.store.save_session(session)
        logger.info(
            "session %s 因插件卸载/重载暂停在第 %d 张，可用 /vote resume 继续",
            session.short_id,
            session.current_index,
        )

    async def _pause_after_send_failures(self, session: Session, failures: int) -> None:
        session.status = SessionStatus.PAUSED
        session.error_message = "连续 %d 条消息发送失败，已自动暂停" % failures
        await self.store.save_session(session)
        logger.error("session %s 连续 %d 条消息发送失败，已自动暂停", session.short_id, failures)
        await self._notify(
            session.umo,
            "投票已自动暂停：连续 %d 条消息发送失败（一条消息可能含多张图）。\n"
            "请检查机器人状态，由管理员执行 /vote resume 继续。" % failures,
        )

    async def _notify(self, umo: str, text: str) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier(umo, text)
        except Exception as exc:
            logger.warning("通知发送失败：%s", exc)

    async def _notify_cutoff(self, session: Session) -> None:
        """截止符号：这条消息之后发送的数字与引用票都不再计入。"""
        await self._notify(
            session.umo,
            "⏹ 投票截止：%s\n已发送 %d/%d 张。此刻起发送的数字与引用票不再计入，正在结算…"
            % (session.project_name, session.current_index, session.candidate_count),
        )

    async def _notify_finish(self, session: Session, statistics, report_enabled: bool) -> None:
        hint = "报告生成中，完成后会再提示一次。" if report_enabled else "报告未生成，需要时执行 /vote export。"
        await self._notify(
            session.umo,
            "📊 结算完成：%s\n有效票：%d，参与人数：%d\n%s"
            % (
                session.project_name,
                statistics.total_valid_votes,
                statistics.unique_voters,
                hint,
            ),
        )

    async def _send_report_file(self, session: Session, report_dir: Path) -> None:
        """把单文件报告作为附件发到投票群。"""
        if self.file_sender is None:
            return
        html = Path(report_dir) / "index.html"
        if not html.is_file():
            return
        try:
            await self.file_sender(session.umo, html, "%s-报告.html" % session.project_name)
            logger.info("session %s 单文件报告已发到群里", session.short_id)
        except Exception as exc:
            logger.warning("单文件报告发送失败，可到报告目录自行取用：%s", exc)

    async def recover_incomplete_sessions(self) -> None:
        for session in await self.store.list_incomplete_sessions():
            session.status = SessionStatus.PAUSED
            session.error_message = "插件重启后暂停，未自动继续；执行 /vote resume 可继续。"
            await self.store.save_session(session)
            logger.info(
                "恢复未完成 session %s（群 %s）为 PAUSED，进度 %d/%d",
                session.short_id,
                session.group_id,
                session.current_index,
                session.candidate_count,
            )
            if self.config.auto_resume_after_restart and self.sender is not None:
                try:
                    await self._start_existing_session(session)
                    logger.info("session %s 已按 auto_resume_after_restart 自动继续", session.short_id)
                except Exception as exc:
                    logger.error("session %s 自动恢复失败：%s", session.short_id, exc)

    async def resume_recovered_session(self, group_id: str) -> Session:
        if self.sender is None:
            raise RuntimeError("a platform sender is required to resume a session")
        session = await self.store.latest_session_for_group(group_id)
        if session is None or session.status != SessionStatus.PAUSED:
            raise RuntimeError("no recoverable paused session for this group")
        await self._start_existing_session(session)
        return session

    async def pause(self, group_id: str) -> Session:
        await self.sessions.pause(group_id)
        managed = await self.sessions.active_for_group(group_id)
        await self.store.save_session(managed.session)
        logger.info("session %s 已暂停", managed.session.short_id)
        return managed.session

    async def resume(self, group_id: str) -> Session:
        managed = await self.sessions.active_for_group(group_id)
        if managed is None:
            return await self.resume_recovered_session(group_id)
        await self.sessions.resume(group_id)
        await self.store.save_session(managed.session)
        logger.info("session %s 已继续", managed.session.short_id)
        return managed.session

    async def finish(self, group_id: str) -> Session:
        managed = await self.sessions.active_for_group(group_id)
        if managed is None:
            session = await self.store.latest_session_for_group(group_id)
            if session is None or session.status != SessionStatus.PAUSED:
                raise SessionNotFoundError(group_id)
            await self._start_existing_session(session, finish_immediately=True)
            return session
        await self.sessions.finish(group_id)
        managed = await self.sessions.active_for_group(group_id)
        await self.store.save_session(managed.session)
        logger.info("session %s 收到 finish 请求", managed.session.short_id)
        return managed.session

    async def stop(self, group_id: str) -> Session:
        managed = await self.sessions.active_for_group(group_id)
        if managed is None:
            session = await self.store.latest_session_for_group(group_id)
            if session is None or session.status != SessionStatus.PAUSED:
                raise SessionNotFoundError(group_id)
            await self._cancel_session(session)
            return session
        session = await self.sessions.stop(group_id)
        await self._cancel_session(session)
        logger.info("session %s 已停止并保留已收投票（进度 %d/%d）", session.short_id, session.current_index, session.candidate_count)
        return session

    async def export_latest(self, group_id: str, regenerate_ai: bool = False) -> Path:
        if self.report_generator is None or self.image_processor is None:
            raise RuntimeError("report generation is not configured")
        session = await self.store.latest_session_for_group(group_id)
        if session is None or session.status not in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
            raise RuntimeError("no completed or cancelled session can be exported")
        self.report_activity.reserve_export(session.id)
        try:
            return await self.export_session(session.id, regenerate_ai=regenerate_ai)
        finally:
            self.report_activity.release_export(session.id)

    async def start_report_export(self, session_id: str, regenerate_ai: bool = False) -> None:
        """占位后把报告生成放到后台任务；生成期间拒绝重复生成、读取与清理。"""
        if self.report_generator is None or self.image_processor is None:
            raise RuntimeError('report generation is not configured')
        self.report_activity.reserve_export(session_id)
        try:
            session = await self.store.get_session(session_id)
            if session is None or session.status not in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
                raise ValueError('只有已完成或已取消的场次可以导出')
            managed = await self.sessions.active_for_group(session.group_id)
            if managed and managed.session.id == session_id:
                raise ValueError('该场次尚在收尾，请稍后重试')
        except BaseException:
            self.report_activity.release_export(session_id)
            raise
        task = asyncio.create_task(self._run_report_export(session_id, regenerate_ai))
        self.report_activity.attach_task(session_id, task)

    async def _run_report_export(self, session_id: str, regenerate_ai: bool) -> None:
        try:
            await self.export_session(session_id, regenerate_ai=regenerate_ai)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            current = await self.store.get_session(session_id)
            if current is not None:
                current.error_message = 'report generation failed: ' + str(exc)
                await self.store.save_session(current)
        finally:
            self.report_activity.release_export(session_id)

    async def export_session(self, session_id: str, regenerate_ai: bool = False) -> Path:
        """报告的生成实现；入口调用前必须先用 report_activity 占位（见 export_latest / start_report_export）。"""
        if self.report_generator is None or self.image_processor is None:
            raise RuntimeError('report generation is not configured')
        session = await self.store.get_session(session_id)
        if session is None or session.status not in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
            raise RuntimeError('only completed or cancelled sessions can be exported')
        await self._heal_project_name(session)
        candidates = await self.store.list_candidates(session.id)
        votes = await self.store.list_votes(session.id)
        statistics = calculate_statistics(
            candidates,
            votes,
            score_min=session.score_min,
            score_max=session.score_max,
        )
        if regenerate_ai:
            if self.ai_summary_service is None:
                raise RuntimeError('AI summary is disabled or unavailable')
            summary = await self.ai_summary_service.summarize(build_summary_statistics(
                session.project_name, statistics, top_n=self.config.ai_top_n,
                bottom_n=self.config.ai_bottom_n, score_min=session.score_min,
                score_max=session.score_max), umo=session.umo)
            if summary:
                session.ai_summary = summary
        report_path = await self._generate_report(session, candidates, statistics)
        session.output_path = str(report_path)
        if session.error_message and session.error_message.startswith('report generation failed:'):
            session.error_message = None
        await self.store.save_session(session)
        logger.info("session %s 重新导出报告：%s", session.short_id, report_path)
        return report_path

    def cleanup_reports(self, selector: str, confirmed: bool = False) -> CleanupResult:
        result = ReportCleanupService(Path(self.config.output_root)).cleanup(
            selector, confirmed=confirmed, activity=self.report_activity
        )
        logger.info("清理报告：selector=%s，删除 %d 个目录，跳过 %d 个使用中的报告",
                    selector, result.removed, result.skipped)
        return result

    def cleanup_expired_reports(self) -> CleanupResult:
        if not self.config.auto_cleanup_reports:
            return CleanupResult()
        result = ReportCleanupService(Path(self.config.output_root)).cleanup_expired(
            self.config.report_retention_days, activity=self.report_activity
        )
        logger.info("自动清理：删除 %d 个超过 %d 天的报告目录，跳过 %d 个使用中的报告",
                    result.removed, self.config.report_retention_days, result.skipped)
        return result

    async def purge_session(self, session_id: str, confirm: bool = False) -> PurgeResult:
        """彻底删除一场投票：报告目录 + 数据库里的票与候选，不可恢复。原图不受影响。"""
        if not confirm:
            raise ValueError('彻底删除需要确认')
        session = await self.store.get_session(session_id)
        if session is None:
            raise FileNotFoundError('场次不存在，可能已被删除')
        managed = await self.sessions.active_for_group(session.group_id)
        if managed is not None and managed.session.id == session.id:
            raise ValueError('该场次仍在运行或收尾，先结束再彻底删除')
        reports = 0
        if session.output_path:
            cleanup = ReportCleanupService(Path(self.config.output_root)).cleanup(
                session.id, activity=self.report_activity
            )
            reports = cleanup.removed
        deleted = await self.store.purge_session(session.id)
        logger.warning(
            "彻底删除场次 %s：报告 %d 个，票 %d 条，候选 %d 条",
            session.short_id,
            reports,
            deleted.get('votes', 0),
            deleted.get('candidates', 0),
        )
        return PurgeResult(
            session_id=session.id,
            short_id=session.short_id,
            reports=reports,
            votes=deleted.get('votes', 0),
            candidates=deleted.get('candidates', 0),
        )

    def _warn_range_mismatch(self, session: Session) -> None:
        """运行中改了评分范围时提醒一次：计票以会话快照为准，新范围下个会话生效。"""
        if session.id in self._range_warned:
            return
        self._range_warned.add(session.id)
        logger.warning(
            "session %s 的评分范围是 %d-%d，当前配置是 %d-%d；本次投票按会话范围计票，新范围从下一个会话开始生效",
            session.short_id,
            session.score_min,
            session.score_max,
            self.config.score_min,
            self.config.score_max,
        )

    @staticmethod
    def _character_image_group(candidates: Sequence[Candidate], start: int) -> list:
        """合并发送时，把从 start 开始连续同人物的图片合成一组。"""
        character = character_of(candidates[start])
        group = [candidates[start]]
        index = start + 1
        while index < len(candidates) and character_of(candidates[index]) == character:
            group.append(candidates[index])
            index += 1
        return group

    @staticmethod
    def _send_context(layout, index: int, span: int, merged: bool, merge_limit: int):
        """把「第几位人物、第几张、这条含几张」整理成群消息文案用的上下文。"""
        character_ordinal, image_ordinal, image_count = layout[index]
        character_total = max(item[0] for item in layout)
        if merged and merge_limit > 0:
            group_total = max(1, -(-image_count // merge_limit))
            group_ordinal = (image_ordinal - 1) // merge_limit + 1
        else:
            group_total = image_count
            group_ordinal = image_ordinal
        return SendContext(
            character_ordinal=character_ordinal,
            character_total=character_total,
            image_ordinal=image_ordinal,
            image_span=span,
            image_count=image_count,
            group_ordinal=group_ordinal,
            group_total=group_total,
        )

    def _next_wait_seconds(self, session: Session, is_last: bool) -> int:
        """A character window always starts after its final image finishes sending."""
        if is_last:
            return session.final_grace_seconds
        return session.interval_seconds

    @staticmethod
    def _log_send_pace(session: Session, candidate: Candidate, group: Sequence[Candidate], elapsed: float) -> None:
        """发送耗时与人物间隔的关系：逐张按单张判定，合并按平均每张判定。

        合并发送一条消息里有多张图，整条耗时必然超过人物间隔，按整条 WARN 只会每个
        人物刷一条；真正值得提示的是「平均每张都追不上间隔」。
        """
        interval = session.interval_seconds
        span = "%d-%d" % (candidate.display_index, group[-1].display_index)
        if len(group) > 1:
            per_image = elapsed / len(group)
            if per_image > interval:
                logger.warning(
                    "session %s 第 %s 张合并发送耗时 %.1f 秒（平均每张 %.1f 秒），超过设定间隔 %d 秒；"
                    "合并发送按整条消息计时，本人物全部图片发完后会等待完整间隔",
                    session.short_id,
                    span,
                    elapsed,
                    per_image,
                    interval,
                )
            return
        if elapsed > interval:
            logger.warning(
                "session %s 第 %s 张发送耗时 %.1f 秒，超过设定间隔 %d 秒；"
                "人物内部仍连续发送；本人物全部图片发完后会等待完整间隔",
                session.short_id,
                span,
                elapsed,
                interval,
            )

    async def _heal_project_name(self, session: Session) -> None:
        """老会话可能存的是文件夹名；若路径已在登记表里，改用登记名，报告目录随之统一。"""
        registry = getattr(self.projects, "registry", None)
        if registry is None:
            return
        matched = None
        for name in registry.names():
            try:
                if registry.resolve(name) == Path(session.project_path):
                    matched = name
                    break
            except Exception:
                continue
        if matched is None or matched == session.project_name:
            return
        logger.info(
            "会话 %s 的项目名从 %s 更正为登记名 %s", session.short_id, session.project_name, matched
        )
        session.project_name = matched
        await self.store.save_session(session)

    async def _generate_report(self, session: Session, candidates: Sequence[Candidate], statistics) -> Path:
        votes = await self.store.list_votes(session.id)
        if self.config.report_mode == "single_html" and hasattr(self.report_generator, "generate_single_html"):
            return await self.report_generator.generate_single_html(
                session,
                candidates,
                statistics,
                Path(session.project_path),
                Path(self.config.output_root),
                self.image_processor,
                self.config.single_html_max_mb,
                ai_summary=session.ai_summary,
                votes=votes,
                include_participants=self.config.report_include_participants,
            )
        return await self.report_generator.generate(
            session,
            candidates,
            statistics,
            Path(session.project_path),
            Path(self.config.output_root),
            self.image_processor,
            ai_summary=session.ai_summary,
            votes=votes,
            include_participants=self.config.report_include_participants,
        )

    async def record_vote(
        self,
        session: Session,
        candidates: Sequence[Candidate],
        text: str,
        voter_id: str,
        voter_name: str,
        active_candidate: Optional[Candidate],
        reply: Optional[ReplyPayload] = None,
        message_id: Optional[str] = None,
    ) -> Optional[VoteDecision]:
        if not voter_id:
            return None
        if (session.score_min, session.score_max) != (self.config.score_min, self.config.score_max):
            self._warn_range_mismatch(session)
        decision, skip_reason = self.router.route_with_reason(
            text, session, active_candidate, {item.display_index: item for item in candidates}, reply
        )
        if decision is None:
            if skip_reason:
                logger.info(
                    "忽略 %s(%s) 的「%s」：%s（session=%s）",
                    voter_name,
                    voter_id,
                    (text or "").strip(),
                    skip_reason,
                    session.short_id,
                )
            return None
        now = utc_now()
        previous = await self.store.upsert_vote(
            Vote(
                id=None,
                session_id=session.id,
                candidate_id=decision.candidate_id,
                voter_id=voter_id,
                voter_name=voter_name,
                score=decision.score,
                source_type=decision.source_type,
                message_id=message_id,
                created_at=now,
                updated_at=now,
                character=decision.character,
            ),
            policy=self.config.same_user_vote_policy,
        )
        candidate = next((item for item in candidates if item.id == decision.candidate_id), None)
        logger.info(
            "记录投票 session=%s 人物=%s（来源图片第%s张 %s）：%s(%s) %s分 来源=%s%s",
            session.short_id,
            decision.character,
            candidate.display_index if candidate is not None else "?",
            candidate.display_title if candidate is not None else decision.candidate_id,
            voter_name,
            voter_id,
            decision.score,
            decision.source_type.value,
            "" if previous is None else "，覆盖旧票 %d 分" % previous,
        )
        return decision
