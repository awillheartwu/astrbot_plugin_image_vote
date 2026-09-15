import asyncio
import tempfile
import unittest
from pathlib import Path

from src.application import VoteApplication
from src.config import VoteConfig
from src.models import SendStatus, SessionStatus
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter


class MergedSendingTest(unittest.TestCase):
    async def _run(self, root, files, config_extra, sender, interval_seconds=0):
        input_root = root / "projects"
        project_root = input_root / "demo"
        project_root.mkdir(parents=True)
        for name in files:
            (project_root / name).write_bytes(b"x")
        values = {"input_root": str(input_root), "output_root": str(root / "reports")}
        values.update(config_extra)
        config = VoteConfig.from_mapping(values)
        store = SQLiteStore(root / "state" / "vote.db")
        await store.initialize()
        application = VoteApplication(
            config, ProjectService(input_root), store, SessionManager(), VoteRouter(), sender=sender
        )
        session = await application.prepare_session("g1", "umo", "demo")
        session.interval_seconds = interval_seconds
        session.final_grace_seconds = 0
        candidates = await store.list_candidates(session.id)

        async def runner(current_session, control):
            await application.run_session(current_session, candidates, control)

        await application.sessions.start(session, runner)
        managed = await application.sessions.active_for_group("g1")
        await asyncio.wait_for(managed.task, timeout=6)
        return store, session

    def test_merged_sending_respects_the_per_message_image_limit(self):
        async def scenario(root):
            calls = []

            async def sender(session, candidate, image_paths):
                calls.append([path.name for path in image_paths])

            files = ["screenshot%04d - Elis - hash%04d.png" % (index, index) for index in range(1, 6)]
            store, _session = await self._run(
                root, files, {"merge_character_images": True, "merge_character_images_max": 2}, sender
            )
            self.assertEqual([len(paths) for paths in calls], [2, 2, 1], calls)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_send_timeout_is_recorded_as_a_send_failure(self):
        async def scenario(root):
            async def sender(session, candidate, image_paths):
                await asyncio.sleep(5)

            store, session = await self._run(
                root, ["screenshot0001 - Elis - aaaa1111.png"], {"send_timeout_seconds": 1}, sender
            )
            persisted = await store.list_candidates(session.id)
            self.assertEqual(persisted[0].send_status, SendStatus.SEND_FAILED)
            current = await store.get_session(session.id)
            self.assertIn("发送超时", current.error_message or "")
            self.assertEqual(current.status, SessionStatus.COMPLETED)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_merged_sending_does_not_warn_about_the_character_interval(self):
        """合并发送一条多张图，整条耗时必然超过人物间隔，不该按整条刷 WARN。"""
        async def scenario(root):
            async def sender(session, candidate, image_paths):
                calls.append(len(image_paths))
                if len(calls) == 1:
                    await asyncio.sleep(1.2)

            calls = []
            files = ["screenshot%04d - Elis - hash%04d.png" % (i, i) for i in (1, 2)]
            files.append("screenshot0003 - Bob - hash0003.png")
            with self.assertLogs("astrbot_plugin_image_vote", level="DEBUG") as captured:
                store, _session = await self._run(
                    root, files, {"merge_character_images": True, "merge_character_images_max": 3}, sender,
                    interval_seconds=1,
                )
            self.assertEqual(calls[0], 2)
            warnings = [r.getMessage() for r in captured.records if "超过设定间隔" in r.getMessage()]
            self.assertEqual(warnings, [])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_single_image_sending_still_warns_when_it_exceeds_the_interval(self):
        async def scenario(root):
            async def sender(session, candidate, image_paths):
                await asyncio.sleep(1.2)

            files = ["screenshot0001 - Elis - hash0001.png", "screenshot0002 - Bob - hash0002.png"]
            with self.assertLogs("astrbot_plugin_image_vote", level="DEBUG") as captured:
                store, _session = await self._run(
                    root, files, {"merge_character_images": False}, sender, interval_seconds=1
                )
            warnings = [r.getMessage() for r in captured.records if "超过设定间隔" in r.getMessage()]
            self.assertEqual(len(warnings), 1, warnings)
            self.assertIn("第 1-1 张发送耗时", warnings[0])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_merged_sending_warns_when_the_per_image_pace_exceeds_the_interval(self):
        async def scenario(root):
            async def sender(session, candidate, image_paths):
                calls.append(len(image_paths))
                if len(calls) == 1:
                    await asyncio.sleep(2.2)

            calls = []
            files = ["screenshot%04d - Elis - hash%04d.png" % (i, i) for i in (1, 2)]
            files.append("screenshot0003 - Bob - hash0003.png")
            with self.assertLogs("astrbot_plugin_image_vote", level="DEBUG") as captured:
                store, _session = await self._run(
                    root, files, {"merge_character_images": True, "merge_character_images_max": 3}, sender,
                    interval_seconds=1,
                )
            warnings = [r.getMessage() for r in captured.records if "超过设定间隔" in r.getMessage()]
            self.assertEqual(len(warnings), 1, warnings)
            self.assertIn("平均每张 1.1 秒", warnings[0])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))


if __name__ == "__main__":
    unittest.main()
