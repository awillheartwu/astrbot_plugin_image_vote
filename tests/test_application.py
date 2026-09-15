import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from src.application import VoteApplication
from src.config import VoteConfig
from src.models import Session, SessionStatus, Vote, VoteSource
from src.path_guard import PathGuard
from src.report_generator import PLUGIN_NAME, REPORT_MARKER
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.project_registry import ProjectRegistry
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter


class ApplicationTest(unittest.TestCase):
    def test_character_batch_sends_contiguously_and_waits_after_last_image(self):
        class RecordingControl:
            stop_requested = False
            finish_requested = False

            def __init__(self):
                self.waits = []

            async def wait_if_paused(self):
                return None

            async def wait_for_interval(self, seconds):
                self.waits.append(seconds)

        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in (
                "screenshot0001 - A - aaaaaa.png",
                "screenshot0002 - B - bbbbbb.png",
                "screenshot0003 - A - cccccc.png",
            ):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            observed = []

            async def sender(session, candidate, image_paths):
                observed.append((candidate.character, candidate.sequence_number, session.active_character))

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 7
            session.final_grace_seconds = 9
            candidates = await store.list_candidates(session.id)
            control = RecordingControl()
            await application.run_session(session, candidates, control)
            self.assertEqual(observed, [("A", 1, None), ("A", 3, "A"), ("B", 2, None)])
            self.assertEqual(control.waits, [7, 9])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

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

            async def sender(session, candidate, image_paths):
                sent.append((candidate.display_index, image_paths[0].name))

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

    def test_purge_session_removes_votes_candidates_and_report(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter())
            session = await application.prepare_session("g1", "umo", "demo")
            candidates = await store.list_candidates(session.id)
            await store.upsert_vote(
                Vote(None, session.id, candidates[0].id, "u1", "Alice", 8, VoteSource.CURRENT_WINDOW)
            )
            report_dir = root / "reports" / "demo" / (session.short_id + "-purge")
            PathGuard.write_report_marker(report_dir, REPORT_MARKER, PLUGIN_NAME, session.id, {"short_id": session.short_id})
            (report_dir / "index.html").write_text("<html>x</html>", encoding="utf-8")
            session.output_path = str(report_dir)
            await store.save_session(session)

            with self.assertRaises(ValueError):
                await application.purge_session(session.id)
            result = await application.purge_session(session.id, confirm=True)
            self.assertEqual((result.votes, result.candidates, result.reports), (1, 1, 1))
            self.assertIsNone(await store.get_session(session.id))
            self.assertEqual(await store.list_votes(session.id), [])
            self.assertEqual(await store.list_candidates(session.id), [])
            self.assertFalse(report_dir.exists())
            with self.assertRaises(FileNotFoundError):
                await application.purge_session(session.id, confirm=True)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_merged_sending_groups_a_characters_images_into_one_message(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in (
                "screenshot0001 - Elis - aaaa1111.png",
                "screenshot0002 - Elis - bbbb2222.png",
                "screenshot0003 - Elis - cccc3333.png",
                "screenshot0004 - Solo - dddd4444.png",
            ):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping({
                "input_root": str(input_root),
                "output_root": str(root / "reports"),
                "merge_character_images": True,
            })
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            calls = []

            async def sender(session, candidate, image_paths):
                calls.append((candidate.display_title, [path.name for path in image_paths]))

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)
            self.assertEqual([len(paths) for _, paths in calls], [3, 1], calls)
            self.assertEqual(calls[0][0], "Elis")
            session.status = SessionStatus.RUNNING
            session.active_character = "Elis"
            await application.record_vote(session, candidates, "4", "u1", "Alice", candidates[0])
            votes = await store.list_votes(session.id)
            self.assertEqual([(vote.candidate_id, vote.character, vote.score) for vote in votes],
                             [(candidates[0].id, "Elis", 4)])
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

            async def sender(session, candidate, image_paths):
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

            async def sender(session, candidate, image_paths):
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

            async def sender(session, candidate, image_paths):
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

            async def sender(session, candidate, image_paths):
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

            async def sender(session, candidate, image_paths):
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

    def test_graceful_shutdown_leaves_session_resumable(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping(
                {"input_root": str(input_root), "output_root": str(root / "reports"), "default_interval_seconds": 5}
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            entered = asyncio.Event()

            async def sender(session, candidate, image_paths):
                entered.set()
                await asyncio.Event().wait()

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            session = await application.start_session("g1", "umo", "demo")
            await asyncio.wait_for(entered.wait(), timeout=1)

            await application.sessions.shutdown()
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.PAUSED)

            resumed = await application.resume_recovered_session("g1")
            self.assertEqual(resumed.id, session.id)
            await application.sessions.shutdown()
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.PAUSED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_explicit_stop_still_marks_cancelled(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping(
                {"input_root": str(input_root), "output_root": str(root / "reports"), "default_interval_seconds": 5}
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            entered = asyncio.Event()

            async def sender(session, candidate, image_paths):
                entered.set()
                await asyncio.Event().wait()

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            session = await application.start_session("g1", "umo", "demo")
            await asyncio.wait_for(entered.wait(), timeout=1)

            stopped = await application.stop("g1")
            self.assertEqual(stopped.id, session.id)
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.CANCELLED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_finalizing_session_is_recovered_as_paused(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter())
            session = await application.prepare_session("g1", "umo", "demo")
            session.status = SessionStatus.FINALIZING
            session.current_index = session.candidate_count
            await store.save_session(session)

            await application.recover_incomplete_sessions()
            self.assertEqual((await store.get_session(session.id)).status, SessionStatus.PAUSED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_character_transition_clears_previous_vote_target_before_next_send(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png", "three.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            third = asyncio.Event()

            async def sender(session, candidate, image_paths):
                if candidate.display_index == 2:
                    raise RuntimeError("temporary send failure")
                if candidate.display_index == 3:
                    third.set()
                    await asyncio.Event().wait()

            application = VoteApplication(
                config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            await asyncio.wait_for(third.wait(), timeout=2)
            persisted = await store.get_session(session.id)
            self.assertIsNone(persisted.active_candidate_id)
            self.assertIsNone(persisted.active_character)
            await application.stop("g1")
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_report_is_generated_after_completion_with_end_time(self):
        class RecordingGenerator:
            def __init__(self):
                self.status = None
                self.finished_at = None

            async def generate(
                self, session, candidates, statistics, source_root, output_root, image_processor, ai_summary=None, votes=None, include_participants=True
            ):
                self.status = session.status
                self.finished_at = session.finished_at
                return Path(output_root) / "report"

        async def scenario(root, recorded):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()

            async def sender(session, candidate, image_paths):
                return None

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
                report_generator=recorded,
                image_processor=object(),
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)

            self.assertEqual(recorded.status, SessionStatus.COMPLETED)
            self.assertIsNotNone(recorded.finished_at)
            persisted = await store.get_session(session.id)
            self.assertEqual(persisted.output_path, str(Path(root / "reports") / "report"))
            await store.close()

        recorded = RecordingGenerator()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), recorded))

    def test_session_short_id_has_eight_hex_chars(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter())
            session = await application.prepare_session("g1", "umo", "demo")
            self.assertEqual(len(session.short_id), 8)
            self.assertTrue(all(char in "0123456789ABCDEF" for char in session.short_id))
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_next_wait_seconds_starts_after_character_send(self):
        async def scenario():
            base = VoteConfig.from_mapping({"input_root": "/a", "output_root": "/b"})
            application = VoteApplication(base, ProjectService(Path("/a")), None, SessionManager(), VoteRouter())
            session = Session(
                "s1", "A1B2C3D4", "g1", "umo", "demo", "/tmp/demo", SessionStatus.RUNNING,
                interval_seconds=5, final_grace_seconds=20,
            )
            self.assertEqual(application._next_wait_seconds(session, False, 17.0), 5)
            self.assertEqual(application._next_wait_seconds(session, True, 17.0), 20)

            periodic = VoteConfig.from_mapping(
                {"input_root": "/a", "output_root": "/b", "interval_includes_send_time": True}
            )
            compatibility_app = VoteApplication(
                periodic, ProjectService(Path("/a")), None, SessionManager(), VoteRouter()
            )
            self.assertEqual(compatibility_app._next_wait_seconds(session, False, 3.0), 5)
            self.assertEqual(compatibility_app._next_wait_seconds(session, False, 17.0), 5)
            self.assertEqual(compatibility_app._next_wait_seconds(session, True, 17.0), 20)

        asyncio.run(scenario())

    def test_registered_project_name_is_used_for_session(self):
        async def scenario(root):
            input_root = root / "projects"
            input_root.mkdir(parents=True)
            outside = root / "08_SLG" / "00XX_海滨之家" / "人物图"
            outside.mkdir(parents=True)
            (outside / "one.png").write_bytes(b"x")
            registry = ProjectRegistry(root / "projects.json")
            registry.register("海滨之家", outside)
            config = VoteConfig.from_mapping(
                {"input_root": str(input_root), "output_root": str(root / "reports")}
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(
                config, ProjectService(input_root, registry=registry), store, SessionManager(), VoteRouter()
            )
            session = await application.prepare_session("g1", "umo", "海滨之家")
            self.assertEqual(session.project_name, "海滨之家")
            self.assertEqual(Path(session.project_path), outside.resolve())
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_old_session_project_name_is_healed_from_registry(self):
        async def scenario(root):
            input_root = root / "projects"
            input_root.mkdir(parents=True)
            outside = root / "08_SLG" / "00XX_海滨之家" / "人物图"
            outside.mkdir(parents=True)
            registry = ProjectRegistry(root / "projects.json")
            registry.register("海滨之家", outside)
            config = VoteConfig.from_mapping(
                {"input_root": str(input_root), "output_root": str(root / "reports")}
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(
                config, ProjectService(input_root, registry=registry), store, SessionManager(), VoteRouter()
            )
            legacy = Session(
                "s1", "A1B2C3D4", "g1", "umo", "人物图", str(outside.resolve()),
                SessionStatus.PAUSED, candidate_count=1,
            )
            await store.save_session(legacy)

            await application._heal_project_name(legacy)
            self.assertEqual(legacy.project_name, "海滨之家")
            self.assertEqual((await store.get_session("s1")).project_name, "海滨之家")
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_single_html_report_is_sent_to_group_when_enabled(self):
        class SingleHtmlGenerator:
            def __init__(self):
                self.calls = 0

            async def generate_single_html(
                self, session, candidates, statistics, source_root, output_root, image_processor, max_mb,
                ai_summary=None, votes=None, include_participants=True,
            ):
                self.calls += 1
                report = Path(output_root) / "single-report"
                report.mkdir(parents=True, exist_ok=True)
                (report / "index.html").write_text("<html></html>", encoding="utf-8")
                return report

        async def scenario(root, generator, sent):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            config = VoteConfig.from_mapping(
                {
                    "input_root": str(input_root),
                    "output_root": str(root / "reports"),
                    "report_mode": "single_html",
                    "send_report_html": True,
                    "notify_on_finish": False,
                }
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()

            async def sender(session, candidate, image_paths):
                return None

            async def file_sender(umo, path, name):
                sent.append((umo, Path(path).name, name))

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
                report_generator=generator,
                image_processor=object(),
                file_sender=file_sender,
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)
            await store.close()

        generator = SingleHtmlGenerator()
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), generator, sent))
        self.assertEqual(generator.calls, 1)
        self.assertEqual(sent, [("umo", "index.html", "demo-报告.html")])

    def test_consecutive_send_failures_pause_and_notify(self):
        async def scenario(root, notified):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png", "three.png", "four.png", "five.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping(
                {
                    "input_root": str(input_root),
                    "output_root": str(root / "reports"),
                    "send_failure_pause_threshold": 2,
                    "notify_on_finish": False,
                }
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()

            async def sender(session, candidate, image_paths):
                if candidate.display_index >= 3:
                    raise RuntimeError("send failed")

            async def notifier(umo, text):
                notified.append((umo, text))

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
                notifier=notifier,
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)

            persisted = await store.get_session(session.id)
            self.assertEqual(persisted.status, SessionStatus.PAUSED)
            self.assertEqual(persisted.current_index, 4)
            self.assertEqual(len(notified), 1)
            self.assertIn("连续 2 张", notified[0][1])
            self.assertEqual(notified[0][0], "umo")
            await store.close()

        notified = []
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), notified))

    def test_send_failure_counter_resets_after_success(self):
        async def scenario(root, notified):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            for name in ("one.png", "two.png", "three.png"):
                (project_root / name).write_bytes(b"x")
            config = VoteConfig.from_mapping(
                {
                    "input_root": str(input_root),
                    "output_root": str(root / "reports"),
                    "send_failure_pause_threshold": 2,
                }
            )
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()

            async def sender(session, candidate, image_paths):
                if candidate.display_index in {1, 3}:
                    raise RuntimeError("send failed")

            async def notifier(umo, text):
                notified.append(text)

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
                notifier=notifier,
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)

            persisted = await store.get_session(session.id)
            self.assertEqual(persisted.status, SessionStatus.COMPLETED)
            self.assertEqual(persisted.current_index, 3)
            self.assertFalse(any("自动暂停" in text for text in notified))
            await store.close()

        notified = []
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), notified))

    def test_finish_notification_and_auto_report_toggles(self):
        class RecordingGenerator:
            def __init__(self):
                self.calls = 0

            async def generate(
                self, session, candidates, statistics, source_root, output_root, image_processor, ai_summary=None, votes=None, include_participants=True
            ):
                self.calls += 1
                return Path(output_root) / "report"

        async def scenario(root, notified, generator, config_extra):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "one.png").write_bytes(b"x")
            values = {"input_root": str(input_root), "output_root": str(root / "reports")}
            values.update(config_extra)
            config = VoteConfig.from_mapping(values)
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()

            async def sender(session, candidate, image_paths):
                return None

            async def notifier(umo, text):
                notified.append(text)

            application = VoteApplication(
                config,
                ProjectService(input_root),
                store,
                SessionManager(),
                VoteRouter(),
                sender=sender,
                notifier=notifier,
                report_generator=generator,
                image_processor=object(),
            )
            session = await application.prepare_session("g1", "umo", "demo")
            session.interval_seconds = 0
            session.final_grace_seconds = 0
            candidates = await store.list_candidates(session.id)

            async def runner(current_session, control):
                await application.run_session(current_session, candidates, control)

            await application.sessions.start(session, runner)
            managed = await application.sessions.active_for_group("g1")
            await asyncio.wait_for(managed.task, timeout=2)
            await store.close()

        notified = []
        generator = RecordingGenerator()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), notified, generator, {}))
        self.assertEqual(len(notified), 3)
        self.assertIn("投票截止", notified[0])
        self.assertIn("结算完成", notified[1])
        self.assertIn("报告已生成", notified[2])
        self.assertEqual(generator.calls, 1)

        notified = []
        generator = RecordingGenerator()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), notified, generator, {"auto_report_on_finish": False}))
        self.assertEqual(len(notified), 2)
        self.assertIn("投票截止", notified[0])
        self.assertIn("报告未生成", notified[1])
        self.assertEqual(generator.calls, 0)

        notified = []
        generator = RecordingGenerator()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory), notified, generator, {"notify_on_finish": False}))
        self.assertEqual(notified, [])
        self.assertEqual(generator.calls, 1)

    def test_prepare_session_keeps_manifest_character_for_report_grouping(self):
        async def scenario(root):
            input_root = root / "projects"
            project_root = input_root / "demo"
            project_root.mkdir(parents=True)
            (project_root / "a.png").write_bytes(b"a")
            (project_root / "b.png").write_bytes(b"b")
            (project_root / "project.json").write_text(
                json.dumps({"characters": {"黑白星": ["a.png", "b.png"]}}, ensure_ascii=False),
                encoding="utf-8",
            )
            config = VoteConfig.from_mapping({"input_root": str(input_root), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            application = VoteApplication(config, ProjectService(input_root), store, SessionManager(), VoteRouter())
            session = await application.prepare_session("g1", "umo", "demo")
            candidates = await store.list_candidates(session.id)
            self.assertEqual({item.character for item in candidates}, {"黑白星"})
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))
