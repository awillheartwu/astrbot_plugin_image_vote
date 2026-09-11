import asyncio
import tempfile
import unittest
from pathlib import Path

from src.application import VoteApplication
from src.config import VoteConfig
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter


class SessionIdentityTest(unittest.TestCase):
    def test_repeated_project_sessions_do_not_reuse_candidate_primary_keys(self):
        async def scenario(root):
            project = root / "projects" / "demo"
            project.mkdir(parents=True)
            (project / "one.png").write_bytes(b"one")
            config = VoteConfig.from_mapping({"input_root": str(root / "projects"), "output_root": str(root / "reports")})
            store = SQLiteStore(root / "state" / "vote.db")
            await store.initialize()
            app = VoteApplication(config, ProjectService(root / "projects"), store, SessionManager(), VoteRouter())
            first = await app.prepare_session("g1", "u1", "demo")
            second = await app.prepare_session("g2", "u2", "demo")
            first_candidate = (await store.list_candidates(first.id))[0]
            second_candidate = (await store.list_candidates(second.id))[0]
            self.assertNotEqual(first_candidate.id, second_candidate.id)
            self.assertEqual(first_candidate.session_id, first.id)
            self.assertEqual(second_candidate.session_id, second.id)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))
