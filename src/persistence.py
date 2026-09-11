from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Candidate, SendStatus, Session, SessionStatus, Vote, VoteSource


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    short_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    umo TEXT NOT NULL,
    project_name TEXT NOT NULL,
    project_path TEXT NOT NULL,
    status TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    final_grace_seconds INTEGER NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    output_path TEXT,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    ai_summary TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_group_status ON sessions(group_id, status);

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    display_index INTEGER NOT NULL,
    source_relative_path TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    display_title TEXT NOT NULL,
    sequence_number INTEGER,
    source_size INTEGER NOT NULL,
    send_status TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(session_id, display_index)
);
CREATE INDEX IF NOT EXISTS idx_candidates_session ON candidates(session_id);

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    voter_id TEXT NOT NULL,
    voter_name TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 9),
    source_type TEXT NOT NULL,
    message_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(session_id, candidate_id, voter_id)
);
CREATE INDEX IF NOT EXISTS idx_votes_session_candidate ON votes(session_id, candidate_id);
"""


class SQLiteStore:
    """Small async facade over SQLite, keeping SQL out of application services."""

    def __init__(self, database_path: Path):
        self.database_path = database_path.expanduser()
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        if self._connection is None:
            self._connection = sqlite3.connect(str(self.database_path), check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await asyncio.to_thread(self._connection.close)
                self._connection = None

    async def save_session(self, session: Session) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_session_sync, session)

    def _save_session_sync(self, session: Session) -> None:
        connection = self._require_connection()
        connection.execute(
            """INSERT INTO sessions (
                id, short_id, group_id, umo, project_name, project_path, status,
                interval_seconds, final_grace_seconds, current_index, candidate_count,
                output_path, created_at, started_at, finished_at, ai_summary, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                interval_seconds=excluded.interval_seconds,
                final_grace_seconds=excluded.final_grace_seconds,
                current_index=excluded.current_index,
                candidate_count=excluded.candidate_count,
                output_path=excluded.output_path,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                ai_summary=excluded.ai_summary,
                error_message=excluded.error_message""",
            (
                session.id,
                session.short_id,
                session.group_id,
                session.umo,
                session.project_name,
                session.project_path,
                session.status.value,
                session.interval_seconds,
                session.final_grace_seconds,
                session.current_index,
                session.candidate_count,
                session.output_path,
                session.created_at,
                session.started_at,
                session.finished_at,
                session.ai_summary,
                session.error_message,
            ),
        )
        connection.commit()

    async def save_candidates(self, candidates: Iterable[Candidate]) -> None:
        candidates_list = list(candidates)
        async with self._lock:
            await asyncio.to_thread(self._save_candidates_sync, candidates_list)

    def _save_candidates_sync(self, candidates: List[Candidate]) -> None:
        connection = self._require_connection()
        connection.executemany(
            """INSERT INTO candidates (
                id, session_id, display_index, source_relative_path, source_filename,
                display_title, sequence_number, source_size, send_status, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                send_status=excluded.send_status,
                sent_at=excluded.sent_at""",
            [
                (
                    candidate.id,
                    candidate.session_id,
                    candidate.display_index,
                    candidate.source_relative_path,
                    candidate.source_filename,
                    candidate.display_title,
                    candidate.sequence_number,
                    candidate.source_size,
                    candidate.send_status.value,
                    candidate.sent_at,
                )
                for candidate in candidates
            ],
        )
        connection.commit()

    async def upsert_vote(self, vote: Vote) -> None:
        async with self._lock:
            await asyncio.to_thread(self._upsert_vote_sync, vote)

    def _upsert_vote_sync(self, vote: Vote) -> None:
        connection = self._require_connection()
        connection.execute(
            """INSERT INTO votes (
                session_id, candidate_id, voter_id, voter_name, score, source_type,
                message_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, candidate_id, voter_id) DO UPDATE SET
                voter_name=excluded.voter_name,
                score=excluded.score,
                source_type=excluded.source_type,
                message_id=excluded.message_id,
                updated_at=excluded.updated_at""",
            (
                vote.session_id,
                vote.candidate_id,
                vote.voter_id,
                vote.voter_name,
                vote.score,
                vote.source_type.value,
                vote.message_id,
                vote.created_at,
                vote.updated_at,
            ),
        )
        connection.commit()

    async def list_votes(self, session_id: str) -> List[Vote]:
        async with self._lock:
            return await asyncio.to_thread(self._list_votes_sync, session_id)

    def _list_votes_sync(self, session_id: str) -> List[Vote]:
        connection = self._require_connection()
        rows = connection.execute("SELECT * FROM votes WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [
            Vote(
                id=row["id"],
                session_id=row["session_id"],
                candidate_id=row["candidate_id"],
                voter_id=row["voter_id"],
                voter_name=row["voter_name"],
                score=row["score"],
                source_type=VoteSource(row["source_type"]),
                message_id=row["message_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def list_candidates(self, session_id: str) -> List[Candidate]:
        async with self._lock:
            return await asyncio.to_thread(self._list_candidates_sync, session_id)

    def _list_candidates_sync(self, session_id: str) -> List[Candidate]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT * FROM candidates WHERE session_id = ? ORDER BY display_index", (session_id,)
        ).fetchall()
        return [
            Candidate(
                id=row["id"],
                session_id=row["session_id"],
                display_index=row["display_index"],
                source_relative_path=row["source_relative_path"],
                source_filename=row["source_filename"],
                display_title=row["display_title"],
                sequence_number=row["sequence_number"],
                source_size=row["source_size"],
                send_status=SendStatus(row["send_status"]),
                sent_at=row["sent_at"],
            )
            for row in rows
        ]

    async def get_session(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            return await asyncio.to_thread(self._get_session_sync, session_id)

    def _get_session_sync(self, session_id: str) -> Optional[Session]:
        connection = self._require_connection()
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_from_row(row) if row is not None else None

    async def latest_session_for_group(self, group_id: str) -> Optional[Session]:
        async with self._lock:
            return await asyncio.to_thread(self._latest_session_for_group_sync, group_id)

    def _latest_session_for_group_sync(self, group_id: str) -> Optional[Session]:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT * FROM sessions WHERE group_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (group_id,)
        ).fetchone()
        return self._session_from_row(row) if row is not None else None

    async def list_incomplete_sessions(self) -> List[Session]:
        async with self._lock:
            return await asyncio.to_thread(self._list_incomplete_sessions_sync)

    def _list_incomplete_sessions_sync(self) -> List[Session]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT * FROM sessions WHERE status IN (?, ?, ?) ORDER BY created_at",
            (SessionStatus.PREPARING.value, SessionStatus.RUNNING.value, SessionStatus.PAUSED.value),
        ).fetchall()
        return [self._session_from_row(row) for row in rows]

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            short_id=row["short_id"],
            group_id=row["group_id"],
            umo=row["umo"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            status=SessionStatus(row["status"]),
            interval_seconds=row["interval_seconds"],
            final_grace_seconds=row["final_grace_seconds"],
            current_index=row["current_index"],
            candidate_count=row["candidate_count"],
            output_path=row["output_path"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            ai_summary=row["ai_summary"],
            error_message=row["error_message"],
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteStore.initialize() must be awaited first")
        return self._connection
