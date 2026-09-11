from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple


class SessionStatus(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class SendStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    SEND_FAILED = "send_failed"


class VoteSource(str, Enum):
    CURRENT_WINDOW = "current_window"
    QUOTED_REPLY = "quoted_reply"


@dataclass
class Candidate:
    id: str
    session_id: str
    display_index: int
    source_relative_path: str
    source_filename: str
    display_title: str
    sequence_number: Optional[int]
    source_size: int
    send_status: SendStatus = SendStatus.PENDING
    sent_at: Optional[str] = None


@dataclass
class Session:
    id: str
    short_id: str
    group_id: str
    umo: str
    project_name: str
    project_path: str
    status: SessionStatus = SessionStatus.IDLE
    interval_seconds: int = 20
    final_grace_seconds: int = 20
    score_min: int = 1
    score_max: int = 4
    current_index: int = 0
    candidate_count: int = 0
    output_path: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    ai_summary: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class Vote:
    id: Optional[int]
    session_id: str
    candidate_id: str
    voter_id: str
    voter_name: str
    score: int
    source_type: VoteSource
    message_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class ProjectSnapshot:
    project_name: str
    project_path: str
    candidates: Tuple[Candidate, ...]
    invalid_files: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    sort_mode: str = "natural"
    total_size: int = 0


@dataclass(frozen=True)
class VoteDecision:
    candidate_id: str
    score: int
    source_type: VoteSource


@dataclass(frozen=True)
class CandidateStatistics:
    candidate_id: str
    display_index: int
    display_title: str
    vote_count: int
    average_score: Optional[float]
    score_distribution: Dict[int, int] = field(default_factory=dict)
    rank: Optional[int] = None


@dataclass(frozen=True)
class SessionStatistics:
    total_candidates: int
    total_valid_votes: int
    unique_voters: int
    average_votes_per_candidate: float
    overall_average_score: Optional[float]
    candidates: Tuple[CandidateStatistics, ...]
