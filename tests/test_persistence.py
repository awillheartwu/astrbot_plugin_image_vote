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

    def test_finalizing_sessions_are_recoverable_and_active_candidate_round_trips(self):
        async def scenario(database_path):
            store = SQLiteStore(database_path)
            await store.initialize()
            await store.save_session(
                Session(
                    "s1", "A7F3", "g1", "umo", "project", "/tmp/project",
                    SessionStatus.FINALIZING, candidate_count=1,
                )
            )
            incomplete = [item.id for item in await store.list_incomplete_sessions()]
            self.assertIn("s1", incomplete)

            session = await store.get_session("s1")
            session.active_candidate_id = "c9"
            await store.save_session(session)
            self.assertEqual((await store.get_session("s1")).active_candidate_id, "c9")
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))

    def test_vote_policies(self):
        cases = [
            ("last_wins", 2, 4, 4, VoteSource.QUOTED_REPLY),
            ("first_wins", 2, 4, 2, VoteSource.CURRENT_WINDOW),
            ("max_score", 2, 4, 4, VoteSource.QUOTED_REPLY),
            ("max_score", 4, 2, 4, VoteSource.CURRENT_WINDOW),
            ("min_score", 2, 4, 2, VoteSource.CURRENT_WINDOW),
            ("min_score", 4, 2, 2, VoteSource.QUOTED_REPLY),
        ]

        async def scenario(database_path):
            store = SQLiteStore(database_path)
            await store.initialize()
            for index, (policy, first, second, expected, expected_source) in enumerate(cases):
                session_id = "s%d" % index
                candidate_id = "c%d" % index
                await store.save_session(
                    Session(
                        session_id, "A7F3", "g1", "umo", "p", "/tmp/p",
                        SessionStatus.RUNNING, candidate_count=1,
                    )
                )
                await store.save_candidates(
                    [Candidate(candidate_id, session_id, 1, "one.png", "one.png", "One", None, 1)]
                )
                await store.upsert_vote(
                    Vote(None, session_id, candidate_id, "u1", "n", first, VoteSource.CURRENT_WINDOW),
                    policy=policy,
                )
                await store.upsert_vote(
                    Vote(None, session_id, candidate_id, "u1", "n", second, VoteSource.QUOTED_REPLY),
                    policy=policy,
                )
                votes = await store.list_votes(session_id)
                self.assertEqual(len(votes), 1, policy)
                self.assertEqual(votes[0].score, expected, "%s: %s→%s" % (policy, first, second))
                self.assertEqual(votes[0].source_type, expected_source, policy)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))

    def test_vote_upsert_returns_the_overwritten_score(self):
        async def scenario(database_path):
            store = SQLiteStore(database_path)
            await store.initialize()
            await store.save_session(
                Session("s1", "A7F3", "g1", "umo", "project", "/tmp/project", SessionStatus.RUNNING, candidate_count=1)
            )
            await store.save_candidates([Candidate("c1", "s1", 1, "one.png", "one.png", "One", None, 1)])
            first = await store.upsert_vote(Vote(None, "s1", "c1", "u1", "Alice", 2, VoteSource.CURRENT_WINDOW))
            second = await store.upsert_vote(Vote(None, "s1", "c1", "u1", "Alice", 5, VoteSource.CURRENT_WINDOW))
            third = await store.upsert_vote(Vote(None, "s1", "c1", "u2", "Bob", 3, VoteSource.CURRENT_WINDOW))
            self.assertIsNone(first)
            self.assertEqual(second, 2)
            self.assertIsNone(third)
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))

    def test_legacy_votes_score_bound_is_rebuilt_without_losing_history(self):
        legacy_schema = """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, short_id TEXT NOT NULL, group_id TEXT NOT NULL, umo TEXT NOT NULL,
            project_name TEXT NOT NULL, project_path TEXT NOT NULL, status TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL, final_grace_seconds INTEGER NOT NULL,
            current_index INTEGER NOT NULL, candidate_count INTEGER NOT NULL, output_path TEXT,
            created_at TEXT, started_at TEXT, finished_at TEXT, ai_summary TEXT, error_message TEXT
        );
        CREATE TABLE candidates (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, display_index INTEGER NOT NULL,
            source_relative_path TEXT NOT NULL, source_filename TEXT NOT NULL, display_title TEXT NOT NULL,
            sequence_number INTEGER, source_size INTEGER NOT NULL, send_status TEXT NOT NULL, sent_at TEXT
        );
        CREATE TABLE votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            voter_id TEXT NOT NULL, voter_name TEXT NOT NULL,
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 9),
            source_type TEXT NOT NULL, message_id TEXT, created_at TEXT, updated_at TEXT,
            UNIQUE(session_id, candidate_id, voter_id)
        );
        INSERT INTO sessions (id, short_id, group_id, umo, project_name, project_path, status,
            interval_seconds, final_grace_seconds, current_index, candidate_count)
            VALUES ('s1', 'A7F3', 'g1', 'umo', 'project', '/tmp/project', 'RUNNING', 5, 20, 1, 1);
        INSERT INTO candidates (id, session_id, display_index, source_relative_path, source_filename,
            display_title, sequence_number, source_size, send_status)
            VALUES ('c1', 's1', 1, 'one.png', 'one.png', 'One', NULL, 1, 'sent');
        INSERT INTO votes (session_id, candidate_id, voter_id, voter_name, score, source_type, created_at, updated_at)
            VALUES ('s1', 'c1', 'u1', 'Alice', 9, 'current_window', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
        """

        async def scenario(database_path):
            connection = sqlite3.connect(str(database_path))
            connection.executescript(legacy_schema)
            connection.commit()
            connection.close()
            store = SQLiteStore(database_path)
            await store.initialize()
            self.assertEqual([item.score for item in await store.list_votes("s1")], [9])
            previous = await store.upsert_vote(Vote(None, "s1", "c1", "u2", "Bob", 10, VoteSource.CURRENT_WINDOW))
            self.assertIsNone(previous)
            self.assertEqual(sorted(item.score for item in await store.list_votes("s1")), [9, 10])
            await store.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "vote.db"))
