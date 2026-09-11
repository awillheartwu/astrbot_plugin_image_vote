import asyncio
import sqlite3
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

    def test_session_score_range_round_trip(self):
        async def scenario(database_path):
            store = SQLiteStore(database_path)
            await store.initialize()
            await store.save_session(
                Session(
                    "s1", "A7F3", "g1", "umo", "project", "/tmp/project", SessionStatus.RUNNING,
                    candidate_count=1, score_min=0, score_max=10,
                )
            )
            loaded = await store.get_session("s1")
            self.assertEqual((loaded.score_min, loaded.score_max), (0, 10))
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))

    def test_legacy_database_gains_score_columns(self):
        async def scenario(database_path):
            legacy = sqlite3.connect(str(database_path))
            legacy.executescript(
                "CREATE TABLE sessions ("
                " id TEXT PRIMARY KEY, short_id TEXT NOT NULL, group_id TEXT NOT NULL, umo TEXT NOT NULL,"
                " project_name TEXT NOT NULL, project_path TEXT NOT NULL, status TEXT NOT NULL,"
                " interval_seconds INTEGER NOT NULL, final_grace_seconds INTEGER NOT NULL,"
                " current_index INTEGER NOT NULL DEFAULT 0, candidate_count INTEGER NOT NULL DEFAULT 0,"
                " output_path TEXT, created_at TEXT, started_at TEXT, finished_at TEXT,"
                " ai_summary TEXT, error_message TEXT);"
            )
            legacy.execute(
                "INSERT INTO sessions VALUES ('s1','A7F3','g1','umo','p','/tmp/p','RUNNING',20,20,3,5,"
                "NULL,NULL,NULL,NULL,NULL,NULL)"
            )
            legacy.commit()
            legacy.close()
            store = SQLiteStore(database_path)
            await store.initialize()
            loaded = await store.get_session("s1")
            self.assertEqual((loaded.score_min, loaded.score_max), (1, 4))
            self.assertEqual(loaded.current_index, 3)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))
