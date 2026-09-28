import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.application import VoteApplication
from src.character_service import select_character_images
from src.config import VoteConfig
from src.models import Candidate, SessionStatus
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.session_manager import SessionManager
from src.statistics_service import calculate_statistics
from src.vote_collector import VoteRouter


def images(name, count):
    return [Candidate(f'{name}{i}', 'snapshot', i + 1, f'{name}{i}.png', f'{name}{i}.png',
                      name, i, 1, character=name) for i in range(count)]


class CharacterSelectionTest(unittest.TestCase):
    def test_order_limit_and_original_snapshot_preserved(self):
        original = images('A', 10) + images('B', 2)
        indexes = [c.display_index for c in original]
        selected = select_character_images(original, 3)
        self.assertEqual([c.id for c in selected], ['A0', 'A1', 'A2', 'B0', 'B1'])
        self.assertEqual([c.display_index for c in selected], [1, 2, 3, 4, 5])
        self.assertEqual([c.display_index for c in original], indexes)
        self.assertIsNot(selected[0], original[0])

    def test_random_selection_preserves_order_and_short_groups(self):
        with patch('src.character_service.random.sample', return_value=[9, 1, 5]) as sample:
            selected = select_character_images(images('A', 10) + images('B', 2), 3, True)
        sample.assert_called_once_with(range(10), 3)
        self.assertEqual([c.id for c in selected], ['A1', 'A5', 'A9', 'B0', 'B1'])

    def test_unlimited_and_below_limit_do_not_draw(self):
        original = images('A', 3)
        with patch('src.character_service.random.sample') as sample:
            for limit in (0, 3, 10):
                self.assertEqual(select_character_images(original, limit, True), tuple(original))
            self.assertEqual(select_character_images([], 3, True), ())
        sample.assert_not_called()

    def test_real_sampling_is_unique_and_keeps_every_character(self):
        selected = select_character_images(images('A', 10) + images('B', 10), 3, True)
        self.assertEqual(len({c.id for c in selected}), 6)
        self.assertEqual([c.character for c in selected], ['A'] * 3 + ['B'] * 3)

    def test_config_validation_and_grouped_mapping(self):
        config = VoteConfig.from_mapping({'voting': {'max_images_per_character': 3,
                                                     'random_select_character_images': True}})
        self.assertEqual(config.max_images_per_character, 3)
        self.assertTrue(config.random_select_character_images)
        self.assertEqual(VoteConfig.from_mapping({}).max_images_per_character, 0)
        for value in (-1, 1.5, '3', True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VoteConfig.from_mapping({'max_images_per_character': value})
        with self.assertRaises(ValueError):
            VoteConfig.from_mapping({'random_select_character_images': 'false'})

    def test_persisted_selection_survives_restart_and_config_change(self):
        async def scenario(root, merged):
            project = root / 'input' / 'demo'
            project.mkdir(parents=True)
            for character, count in [('A', 10), ('B', 2)]:
                for i in range(count):
                    (project / f'{character}-{i}.png').write_bytes(b'x')
            config = VoteConfig.from_mapping({
                'input_root': str(root / 'input'), 'output_root': str(root / 'out'),
                'max_images_per_character': 3, 'random_select_character_images': True,
                'show_image_selection_details': True,
                'merge_character_images': merged, 'merge_character_images_max': 2,
            })
            projects = ProjectService(root / 'input')
            store = SQLiteStore(root / 'vote.db')
            await store.initialize()
            app = VoteApplication(config, projects, store, SessionManager(), VoteRouter())
            with patch('src.character_service.random.sample', return_value=[9, 1, 5]):
                session = await app.prepare_session('g', 'umo', 'demo')
            selected = await store.list_candidates(session.id)
            self.assertEqual([c.source_filename for c in selected],
                             ['A-1.png', 'A-5.png', 'A-9.png', 'B-0.png', 'B-1.png'])
            self.assertEqual((session.candidate_count, session.character_count), (5, 2))
            self.assertEqual(len(projects.inspect('demo').candidates), 12)
            # Emulate a restart after the first image was sent; recovery must use the saved list.
            from src.models import SendStatus
            selected[0].send_status = SendStatus.SENT
            await store.save_candidates(selected)
            session.current_index = 1
            session.status = SessionStatus.PAUSED
            session.interval_seconds = session.final_grace_seconds = 0
            await store.save_session(session)
            await store.close()
            store = SQLiteStore(root / 'vote.db')
            await store.initialize()
            calls = []

            async def sender(current, candidate, paths):
                calls.append(([p.name for p in paths], candidate.send_context))

            app = VoteApplication(replace(config, max_images_per_character=1), projects, store,
                                  SessionManager(), VoteRouter(), sender=sender)
            with patch('src.character_service.random.sample', side_effect=AssertionError('redrawn')):
                await app.resume_recovered_session('g')
                managed = await app.sessions.active_for_group('g')
                await asyncio.wait_for(managed.task, 2)
            self.assertEqual([name for paths, _ in calls for name in paths],
                             ['A-5.png', 'A-9.png', 'B-0.png', 'B-1.png'])
            self.assertEqual([len(paths) for paths, _ in calls], [2, 2] if merged else [1, 1, 1, 1])
            self.assertEqual((calls[0][1].image_ordinal, calls[0][1].image_count), (2, 3))
            persisted = await store.get_session(session.id)
            self.assertEqual(persisted.image_selection.original_count, 12)
            self.assertEqual(persisted.image_selection.character_counts, {'A': 10, 'B': 2})
            self.assertEqual(persisted.image_selection.maximum, 3)
            self.assertTrue(persisted.image_selection.show_details)
            self.assertEqual((persisted.status, persisted.current_index), (SessionStatus.COMPLETED, 5))
            candidates = await store.list_candidates(session.id)
            persisted.status = SessionStatus.RUNNING
            persisted.active_character = 'A'
            await app.record_vote(persisted, candidates, '4', 'u', 'User', candidates[0])
            await app.record_vote(persisted, candidates, '3', 'u', 'User', candidates[1])
            votes = await store.list_votes(session.id)
            self.assertEqual([(v.character, v.score) for v in votes], [('A', 3)])
            statistics = calculate_statistics(candidates, votes)
            self.assertEqual((statistics.total_candidates, statistics.total_characters), (5, 2))
            self.assertEqual([(c.character, c.candidate_count) for c in statistics.characters], [('A', 3), ('B', 2)])
            await store.close()

        for merged in (False, True):
            with self.subTest(merged=merged), tempfile.TemporaryDirectory() as directory:
                asyncio.run(scenario(Path(directory), merged))
