import asyncio
import tempfile
import unittest
from pathlib import Path

from src.application import VoteApplication
from src.config import VoteConfig
from src.message_sender import MessageSender
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter


class VoteMessageProgressTest(unittest.TestCase):
    """群消息文案：逐张与合并两种发送方式下都要看得出「第几位人物 / 第几张 / 是否发完」。"""

    async def _messages(self, root, files, config_extra):
        input_root = root / "projects"
        project_root = input_root / "demo"
        project_root.mkdir(parents=True)
        for name in files:
            (project_root / name).write_bytes(b"x")
        values = {
            "input_root": str(input_root),
            "output_root": str(root / "reports"),
            "default_interval_seconds": 1,
            "final_grace_seconds": 1,
        }
        values.update(config_extra)
        config = VoteConfig.from_mapping(values)
        store = SQLiteStore(root / "state" / "vote.db")
        await store.initialize()
        sent = []

        async def transport(umo, text, image_paths):
            sent.append(text)

        application = VoteApplication(
            config,
            ProjectService(input_root),
            store,
            SessionManager(),
            VoteRouter(),
            sender=MessageSender(transport).send_candidate,
        )
        session = await application.prepare_session("g1", "umo", "demo")
        session.interval_seconds = 0
        session.final_grace_seconds = 0
        candidates = await store.list_candidates(session.id)

        async def runner(current_session, control):
            await application.run_session(current_session, candidates, control)

        await application.sessions.start(session, runner)
        managed = await application.sessions.active_for_group("g1")
        await asyncio.wait_for(managed.task, timeout=6)
        await store.close()
        return sent, session.short_id

    @staticmethod
    def _files(character, count, start=1):
        return [
            "screenshot%04d - %s - hash%04d.png" % (start + offset, character, start + offset)
            for offset in range(count)
        ]

    @staticmethod
    def _expected(short_id, index, total, character, position):
        return "\n".join([
            "demo · %s" % character,
            position,
            "回复 1-4 给「%s」打分 · 引用本场任意图片可改分" % character,
            "[投票 %03d/%03d · %s]" % (index, total, short_id),
        ])

    def test_single_image_messages_track_character_and_image_progress(self):
        async def scenario(root):
            files = self._files("Elis", 3) + self._files("Bob", 1, start=4)
            sent, short_id = await self._messages(root, files, {"merge_character_images": False})
            self.assertEqual(sent, [
                self._expected(short_id, 1, 4, "Elis", "第 1/2 位人物 · 第 1/3 张 · 之后还有 2 张"),
                self._expected(short_id, 2, 4, "Elis", "第 1/2 位人物 · 第 2/3 张 · 之后还有 1 张"),
                self._expected(short_id, 3, 4, "Elis", "第 1/2 位人物 · 第 3/3 张 · 本人物已发完"),
                self._expected(short_id, 4, 4, "Bob", "第 2/2 位人物 · 本人物共 1 张"),
            ])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_merged_messages_mark_each_relay_group_and_the_last_one(self):
        async def scenario(root):
            files = self._files("Elis", 7) + self._files("Bob", 1, start=8)
            sent, short_id = await self._messages(
                root, files, {"merge_character_images": True, "merge_character_images_max": 3}
            )
            self.assertEqual(sent, [
                self._expected(short_id, 1, 8, "Elis", "第 1/2 位人物 · 第 1-3/7 张（本条 3 张） · 之后还有 4 张"),
                self._expected(short_id, 4, 8, "Elis", "第 1/2 位人物 · 第 4-6/7 张（本条 3 张） · 之后还有 1 张"),
                self._expected(short_id, 7, 8, "Elis", "第 1/2 位人物 · 第 7/7 张 · 本人物已发完"),
                self._expected(short_id, 8, 8, "Bob", "第 2/2 位人物 · 本人物共 1 张"),
            ])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))


if __name__ == "__main__":
    unittest.main()
