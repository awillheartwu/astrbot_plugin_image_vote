import asyncio
import unittest

from src.models import Session, SessionStatus
from src.session_manager import SessionManager


class SessionManagerTest(unittest.TestCase):
    def test_shutdown_cancels_runner_and_releases_group(self):
        async def scenario():
            manager = SessionManager()
            started = asyncio.Event()

            async def runner(session, control):
                started.set()
                await asyncio.Event().wait()

            session = Session("s1", "A7F3", "g1", "umo", "project", "/tmp/project", SessionStatus.PREPARING)
            await manager.start(session, runner)
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertIsNotNone(await manager.active_for_group("g1"))
            await manager.shutdown()
            self.assertIsNone(await manager.active_for_group("g1"))

        asyncio.run(scenario())

