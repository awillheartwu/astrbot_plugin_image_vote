from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from .logging_utils import get_logger
from .models import Session, SessionStatus

logger = get_logger()


class SessionAlreadyActiveError(RuntimeError):
    pass


class SessionNotFoundError(KeyError):
    pass


class SessionControl:
    def __init__(self):
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._stop_event = asyncio.Event()
        self._finish_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self.seconds_until_next: Optional[float] = None

    async def wait_if_paused(self) -> None:
        await self._resume_event.wait()

    def pause(self) -> None:
        self._resume_event.clear()
        self._wake_event.set()

    def resume(self) -> None:
        self._resume_event.set()
        self._wake_event.set()

    def request_stop(self) -> None:
        self._stop_event.set()
        self._resume_event.set()
        self._wake_event.set()

    def request_finish(self) -> None:
        self._finish_event.set()
        self._resume_event.set()
        self._wake_event.set()

    async def wait_for_interval(self, seconds: int) -> None:
        loop = asyncio.get_event_loop()
        remaining = float(max(0, seconds))
        self.seconds_until_next = remaining
        try:
            while remaining > 0:
                if self.stop_requested or self.finish_requested:
                    return
                self._wake_event.clear()
                await self.wait_if_paused()
                if self.stop_requested or self.finish_requested:
                    return
                started_at = loop.time()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return
                remaining -= max(0.0, loop.time() - started_at)
                self.seconds_until_next = max(0.0, remaining)
        finally:
            self.seconds_until_next = None

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @property
    def finish_requested(self) -> bool:
        return self._finish_event.is_set()


@dataclass
class ManagedSession:
    session: Session
    control: SessionControl
    task: asyncio.Task


Runner = Callable[[Session, SessionControl], Awaitable[None]]


class SessionManager:
    """Owns one cancellable asyncio task per group and prevents orphan tasks."""

    def __init__(self):
        self._sessions: Dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()

    async def start(self, session: Session, runner: Runner) -> None:
        async with self._lock:
            if session.group_id in self._sessions:
                raise SessionAlreadyActiveError("group already has an active vote session")
            control = SessionControl()
            task = asyncio.create_task(self._run(session, control, runner), name="image-vote-%s" % session.id)
            self._sessions[session.group_id] = ManagedSession(session, control, task)

    async def _run(self, session: Session, control: SessionControl, runner: Runner) -> None:
        try:
            await runner(session, control)
        except asyncio.CancelledError:
            session.status = SessionStatus.CANCELLED
            raise
        except Exception as exc:
            session.status = SessionStatus.FAILED
            session.error_message = str(exc)
        finally:
            async with self._lock:
                current = self._sessions.get(session.group_id)
                if current is not None and current.session.id == session.id:
                    self._sessions.pop(session.group_id, None)

    async def _get(self, group_id: str) -> ManagedSession:
        async with self._lock:
            managed = self._sessions.get(group_id)
        if managed is None:
            raise SessionNotFoundError(group_id)
        return managed

    async def pause(self, group_id: str) -> None:
        managed = await self._get(group_id)
        managed.control.pause()
        managed.session.status = SessionStatus.PAUSED

    async def resume(self, group_id: str) -> None:
        managed = await self._get(group_id)
        managed.control.resume()
        managed.session.status = SessionStatus.RUNNING

    async def finish(self, group_id: str) -> None:
        managed = await self._get(group_id)
        managed.control.request_finish()

    async def stop(self, group_id: str) -> Session:
        managed = await self._get(group_id)
        managed.control.request_stop()
        managed.task.cancel()
        await asyncio.gather(managed.task, return_exceptions=True)
        return managed.session

    async def active_for_group(self, group_id: str) -> Optional[ManagedSession]:
        async with self._lock:
            return self._sessions.get(group_id)

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
        for managed in sessions:
            managed.control.request_stop()
            managed.task.cancel()
        if sessions:
            await asyncio.gather(*(managed.task for managed in sessions), return_exceptions=True)
