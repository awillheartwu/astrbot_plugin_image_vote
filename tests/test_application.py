import asyncio
import tempfile
import unittest
from pathlib import Path

from src.application import VoteApplication
from src.config import VoteConfig
from src.models import SessionStatus
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter


class ApplicationTest(unittest.TestCase):
    def test_runner_sends_snapshot_in_order_and_finalizes(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "screenshot0002 - B - b.png").write_bytes(b"b")
            (project_root / "screenshot0001 - A - a.png").write_bytes(b"a")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            sent = []

            async def sender(session, candidate, image_path):
                sent.append((candidate.display_index, image_path.name))

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)
            managed = application.sessions
            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)
            await managed.start(session, runner)
            task = await managed.active_for_group("g1")
            await asyncio.wait_for(task.task, timeout=1)
            persisted = await store.get_session(session.id)
            self.assertEqual(sent, [(1, "screenshot0001 - A - a.png"), (2, "screenshot0002 - B - b.png")])
            self.assertEqual(persisted.status, SessionStatus.COMPLETED)
            self.assertEqual(persisted.current_index, 2)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_runner_continues_after_one_send_failure(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"1")
            (project_root / "two.png").write_bytes(b"2")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            sent = []

            async def sender(session, candidate, image_path):
                if candidate.display_index == 1:
                    raise RuntimeError("temporary send failure")
                sent.append(candidate.display_index)

            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender)
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)
            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)
            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=1)
            persisted_candidates = await store.list_candidates(session.id)
            self.assertEqual(sent, [2])
            self.assertEqual(persisted_candidates[0].send_status.value, "send_failed")
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.COMPLETED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_pause_freezes_countdown_until_resume(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"1")
            (project_root / "two.png").write_bytes(b"2")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            first_sent = asyncio.Event()
            sent = []

            async def sender(session, candidate, image_path):
                sent.append(candidate.display_index)
                first_sent.set()

            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender)
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 1
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)
            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)
            await application.sessions.start(session, runner)
            await asyncio.wait_for(first_sent.wait(), timeout=1)
            await application.pause("g1")
            await asyncio.sleep(0.05)
            self.assertEqual(sent, [1])
            await application.resume("g1")
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)
            self.assertEqual(sent, [1, 2])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_recovered_session_resumes_from_persisted_index(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"1")
            (project_root / "two.png").write_bytes(b"2")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            sent = []

            async def sender(session, candidate, image_path):
                sent.append(candidate.display_index)

            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender)
            session = await application.prepare_session("g1", "umo", "demo")
            session.current_index = 1
            session.status = SessionStatus.RUNNING
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            await store.save_session(session)
            await application.recover_incomplete_sessions()
            recovered = await application.resume_recovered_session("g1")
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=1)
            self.assertEqual(recovered.current_index, 2)
            self.assertEqual(sent, [2])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_finish_stops_after_current_candidate_and_finalizes(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png", "three.png"):
                (project_root / name).write_bytes(name.encode("ascii"))
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            sent = []
            application = None

            async def sender(session, candidate, image_path):
                sent.append(candidate.display_index)
                if candidate.display_index == 1:
                    await application.finish("g1")

            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender)
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)
            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)
            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=1)
            self.assertEqual(sent, [1])
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.COMPLETED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_finish_during_interval_does_not_send_another_image(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png", "three.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            sent = []
            box = {}

            async def sender(session, candidate, image_path):
                sent.append(candidate.display_index)
                if candidate.display_index == 1:
                    asyncio.get_event_loop().call_later(
                        0.05, lambda: asyncio.ensure_future(box["app"].finish("g1"))
                    )

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            box["app"] = application
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 5
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=5)
            self.assertEqual(sent, [1])
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.COMPLETED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))
