import asyncio
import tempfile
import unittest
from pathlib import Path

from src.models import Candidate, Session, SessionStatus, Vote, VoteSource
from src.persistence import SQLiteStore


class PersistenceTest(unittest.TestCase):
    def test_vote_upsert_keeps_one_vote_per_user_and_candidate(self):
        async def scenario(database_path):
            store = SQLiteStore(database_path)
            await store.initialize()
            await store.save_session(
                Session("s1", "A7F3", "g1", "umo", "project", "/tmp/project", SessionStatus.RUNNING, candidate_count=1)
            )
            await store.save_candidates([Candidate("c1", "s1", 1, "one.png", "one.png", "One", None, 1)])
            await store.upsert_vote(Vote(None, "s1", "c1", "u1", "Alice", 2, VoteSource.CURRENT_WINDOW))
            await store.upsert_vote(Vote(None, "s1", "c1", "u1", "Alice", 4, VoteSource.QUOTED_REPLY))
            votes = await store.list_votes("s1")
            self.assertEqual(len(votes), 1)
            self.assertEqual(votes[0].score, 4)
            self.assertEqual(votes[0].source_type, VoteSource.QUOTED_REPLY)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))
