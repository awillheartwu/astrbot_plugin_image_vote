from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from .config import VoteConfig
from .ai_summary_service import AiSummaryService, build_summary_statistics
from .logging_utils import get_logger
from .models import Candidate, SendStatus, Session, SessionStatus, Vote, VoteDecision
from .path_guard import PathGuard
from .persistence import SQLiteStore
from .project_service import ProjectService
from .reply_resolver import ReplyPayload
from .session_manager import SessionAlreadyActiveError, SessionManager
from .report_generator import ReportCleanupService
from .statistics_service import calculate_statistics
from .vote_collector import VoteRouter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._range_warned: set = set()

    async def prepare_session(self, group_id: str, umo: str, project_name: str) -> Session:
        if self.config.allowed_group_ids and group_id not in self.config.allowed_group_ids:
            raise PermissionError("group is not allowed to use image voting")
        if await self.sessions.active_for_group(group_id) is not None:
            raise SessionAlreadyActiveError("group already has an active vote session")
        snapshot = self.projects.inspect(project_name, self.config.recursive_scan)
        if not snapshot.candidates:
            raise ValueError("project contains no supported images")
        output_root = Path(self.config.output_root).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_root.is_dir() or not os.access(str(output_root), os.W_OK):
            raise PermissionError("output directory is not writable")
        session_id = uuid.uuid4().hex
        session = Session(
            id=session_id,
            short_id=secrets.token_hex(4).upper(),
            group_id=group_id,
            umo=umo,
            project_name=snapshot.project_name,
            project_path=snapshot.project_path,
            status=SessionStatus.PREPARING,
            interval_seconds=self.config.default_interval_seconds,
            final_grace_seconds=self.config.effective_final_grace_seconds,
            score_min=self.config.score_min,
            score_max=self.config.score_max,
            candidate_count=len(snapshot.candidates),
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

    async def _start_existing_session(self, session: Session) -> None:
        candidates = await self.store.list_candidates(session.id)

        async def runner(current_session: Session, control) -> None:
            await self.run_session(current_session, candidates, control)

        await self.sessions.start(session, runner)

    async def run_session(self, session: Session, candidates: Sequence[Candidate], control) -> None:
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
            for index in range(session.current_index, len(candidates)):
                await control.wait_if_paused()
                if control.stop_requested:
                    await self._cancel_session(session)
                    return
                if control.finish_requested:
                    logger.info("session %s 收到 finish，停止后续图片发送", session.short_id)
                    break
                candidate = candidates[index]
                source_path = PathGuard(Path(session.project_path)).ensure_within(
                    Path(session.project_path) / candidate.source_relative_path, allow_root=False
                )
                try:
                    await self.sender(session, candidate, source_path)
                    candidate.send_status = SendStatus.SENT
                    candidate.sent_at = utc_now()
                    session.active_candidate_id = candidate.id
                    consecutive_failures = 0
                    logger.debug(
                        "session %s 已发送第 %d/%d 张：%s",
                        session.short_id,
                        candidate.display_index,
                        len(candidates),
                        candidate.source_relative_path,
                    )
                except Exception as exc:
                    candidate.send_status = SendStatus.SEND_FAILED
                    session.error_message = str(exc)
                    consecutive_failures += 1
                    logger.warning(
                        "session %s 第 %d 张发送失败（连续第 %d 张），窗口投票仍记在上一张成功发送的图片上：%s",
                        session.short_id,
                        candidate.display_index,
                        consecutive_failures,
                        exc,
                    )
                session.current_index = index + 1
                await self.store.save_candidates([candidate])
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
                wait_seconds = session.final_grace_seconds if index == len(candidates) - 1 else session.interval_seconds
                await control.wait_for_interval(wait_seconds)

            session.status = SessionStatus.FINALIZING
            session.finished_at = utc_now()
            await self.store.save_session(session)
            logger.info("session %s 进入 FINALIZING，已发送 %d 张", session.short_id, session.current_index)
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
            if self.report_generator is not None and self.image_processor is not None:
                try:
                    report_path = await self._generate_report(session, candidates, statistics)
                    session.output_path = str(report_path)
                    await self.store.save_session(session)
                    logger.info("session %s 报告已生成：%s", session.short_id, report_path)
                except Exception as exc:
                    session.error_message = "report generation failed: %s" % exc
                    await self.store.save_session(session)
                    logger.error("session %s 报告生成失败，可用 /vote export 重试：%s", session.short_id, exc)
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
        session.error_message = "plugin unloaded while running; resume explicitly"
        await self.store.save_session(session)
        logger.info(
            "session %s 因插件卸载/重载暂停在第 %d 张，可用 /vote resume 继续",
            session.short_id,
            session.current_index,
        )

    async def _pause_after_send_failures(self, session: Session, failures: int) -> None:
        session.status = SessionStatus.PAUSED
        session.error_message = "%d consecutive send failures" % failures
        await self.store.save_session(session)
        logger.error("session %s 连续 %d 张发送失败，已自动暂停", session.short_id, failures)
        if self.notifier is None:
            return
        try:
            await self.notifier(
                session.umo,
                "投票已自动暂停：连续 %d 张图片发送失败。请检查机器人状态，由管理员执行 /vote resume 继续。"
                % failures,
            )
        except Exception as exc:
            logger.warning("自动暂停通知发送失败：%s", exc)

    async def recover_incomplete_sessions(self) -> None:
        for session in await self.store.list_incomplete_sessions():
            session.status = SessionStatus.PAUSED
            session.error_message = "paused after plugin restart; resume explicitly"
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
        await self.sessions.finish(group_id)
        managed = await self.sessions.active_for_group(group_id)
        await self.store.save_session(managed.session)
        logger.info("session %s 收到 finish 请求", managed.session.short_id)
        return managed.session

    async def stop(self, group_id: str) -> Session:
        session = await self.sessions.stop(group_id)
        await self._cancel_session(session)
        logger.info("session %s 已停止并保留已收投票（进度 %d/%d）", session.short_id, session.current_index, session.candidate_count)
        return session

    async def export_latest(self, group_id: str) -> Path:
        if self.report_generator is None or self.image_processor is None:
            raise RuntimeError("report generation is not configured")
        session = await self.store.latest_session_for_group(group_id)
        if session is None or session.status not in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
            raise RuntimeError("no completed or cancelled session can be exported")
        candidates = await self.store.list_candidates(session.id)
        votes = await self.store.list_votes(session.id)
        statistics = calculate_statistics(
            candidates,
            votes,
            score_min=session.score_min,
            score_max=session.score_max,
        )
        report_path = await self._generate_report(session, candidates, statistics)
        session.output_path = str(report_path)
        await self.store.save_session(session)
        logger.info("session %s 重新导出报告：%s", session.short_id, report_path)
        return report_path

    def cleanup_reports(self, selector: str, confirmed: bool = False) -> int:
        removed = ReportCleanupService(Path(self.config.output_root)).cleanup(selector, confirmed=confirmed)
        logger.info("清理报告：selector=%s，删除 %d 个目录", selector, removed)
        return removed

    def cleanup_expired_reports(self) -> int:
        if not self.config.auto_cleanup_reports:
            return 0
        removed = ReportCleanupService(Path(self.config.output_root)).cleanup_expired(
            self.config.report_retention_days
        )
        logger.info("自动清理：删除 %d 个超过 %d 天的报告目录", removed, self.config.report_retention_days)
        return removed

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

    async def _generate_report(self, session: Session, candidates: Sequence[Candidate], statistics) -> Path:
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
            )
        return await self.report_generator.generate(
            session,
            candidates,
            statistics,
            Path(session.project_path),
            Path(self.config.output_root),
            self.image_processor,
            ai_summary=session.ai_summary,
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
        decision = self.router.route(text, session, active_candidate, {item.display_index: item for item in candidates}, reply)
        if decision is None:
            return None
        now = utc_now()
        await self.store.upsert_vote(
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
            )
        )
        logger.debug(
            "记录投票：session=%s candidate=%s voter=%s score=%d source=%s",
            session.short_id,
            decision.candidate_id,
            voter_id,
            decision.score,
            decision.source_type.value,
        )
        return decision
