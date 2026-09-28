import asyncio
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.message_sender import build_start_summary, build_vote_message
from src.models import Candidate, ImageSelectionSnapshot, SendContext, Session
from src.persistence import SCHEMA, SQLiteStore
from tests import test_vote_message_progress


class SelectionCopyTest(unittest.TestCase):
    def setUp(self):
        self.selection = ImageSelectionSnapshot(120, {'瑞秋': 10, '海伦': 2}, 3, True, True)
        self.session = Session('s', '1234', 'g', 'umo', '个人助理', '/unused',
                               candidate_count=67, character_count=37, image_selection=self.selection)
        self.candidate = Candidate('c', 's', 1, 'a.png', 'a.png', '瑞秋', None, 1, character='瑞秋')

    def test_start_copy_and_rule_variants(self):
        self.assertEqual(build_start_summary(self.session),
                         '已开始投票：个人助理\n共 37 个人物 · 原有 120 张截图\n本轮规则：每人物最多 3 张，随机抽选\n本轮展示：67 张\n')
        for maximum, random_select, expected in [(0, True, '不限张数，全部展示'), (3, False, '每人物最多 3 张，按原排序选取')]:
            self.session.image_selection = replace(self.selection, maximum=maximum, random_select=random_select)
            self.assertIn(expected, build_start_summary(self.session))

    def test_single_merged_and_short_character_copy(self):
        context = SendContext(character_total=37, image_count=3)
        message = build_vote_message(self.session, self.candidate, context)
        self.assertIn('第 1/37 位人物 · 原有 10 张，本轮展示 3 张\n第 1/3 张 · 之后还有 2 张', message)
        self.assertIn('[投票 001/067 · 1234]', message)
        self.assertIn('本条展示全部 3 张 · 本人物已发完',
                      build_vote_message(self.session, self.candidate, replace(context, image_span=3)))
        self.assertIn('第 1-2/3 张（本条 2 张） · 之后还有 1 张',
                      build_vote_message(self.session, self.candidate, replace(context, image_span=2)))
        self.assertIn('原有 2 张，本轮全部展示', build_vote_message(
            self.session, replace(self.candidate, character='海伦'), replace(context, image_count=2)))

    def test_old_session_and_disabled_switch_keep_old_copy(self):
        self.session.image_selection = None
        old = build_vote_message(self.session, self.candidate)
        start = build_start_summary(self.session)
        self.session.image_selection = replace(self.selection, show_details=False)
        self.assertEqual(build_vote_message(self.session, self.candidate), old)
        self.assertEqual(build_start_summary(self.session), start)
        self.assertNotIn('原有', old)

    def test_real_runner_uses_original_counts_after_selection(self):
        async def scenario(root):
            helper = test_vote_message_progress.VoteMessageProgressTest()
            messages, _ = await helper._messages(root, helper._files('瑞秋', 10), {
                'max_images_per_character': 3, 'show_image_selection_details': True,
            })
            self.assertEqual(len(messages), 3)
            for text in messages:
                self.assertIn('原有 10 张，本轮展示 3 张', text)
            self.assertIn('第 3/3 张 · 本人物已发完', messages[-1])
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_migration_keeps_history_unknown_and_snapshot_immutable(self):
        async def scenario(path):
            # Disposable schema from the previous release, before the new migration.
            with sqlite3.connect(path) as old:
                old.executescript(SCHEMA)
                old.execute("INSERT INTO sessions(id,short_id,group_id,umo,project_name,project_path,status,interval_seconds,final_grace_seconds) VALUES('old','OLD','g','umo','old','/unused','PAUSED',20,20)")
            store = SQLiteStore(path)
            await store.initialize()
            self.assertIsNone((await store.get_session('old')).image_selection)
            await store.save_session(self.session)
            self.session.image_selection = replace(self.selection, original_count=999)
            await store.save_session(self.session)
            await store.close()
            await store.initialize()
            restored = await store.get_session('s')
            self.assertEqual(restored.image_selection, self.selection)
            self.assertEqual(build_start_summary(restored).count('120'), 1)
            await store.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / 'vote.db'))
