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


STATUS_LABELS = {
    SessionStatus.IDLE: "未开始",
    SessionStatus.PREPARING: "准备中",
    SessionStatus.RUNNING: "轮播中",
    SessionStatus.PAUSED: "已暂停",
    SessionStatus.FINALIZING: "正在结算",
    SessionStatus.COMPLETED: "已完成",
    SessionStatus.CANCELLED: "已取消",
    SessionStatus.FAILED: "失败",
}


def status_label(status) -> str:
    """群消息与面板共用的中文状态名；未知状态回退到原始枚举值。"""
    try:
        key = status if isinstance(status, SessionStatus) else SessionStatus(status)
    except ValueError:
        return str(status)
    return STATUS_LABELS.get(key, key.value)


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
    character: Optional[str] = None
    send_status: SendStatus = SendStatus.PENDING
    sent_at: Optional[str] = None
    # 发送时由轮播循环写入的进度上下文，只用于拼群消息文案，不落库。
    send_context: Optional["SendContext"] = None


@dataclass(frozen=True)
class SendContext:
    """一条投票消息在整个项目里的位置：第几位人物、该人物第几张、这条含几张。"""

    character_ordinal: int = 1
    character_total: int = 1
    image_ordinal: int = 1
    image_span: int = 1
    image_count: int = 1
    group_ordinal: int = 1
    group_total: int = 1


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
    active_candidate_id: Optional[str] = None
    active_character: Optional[str] = None
    current_index: int = 0
    candidate_count: int = 0
    character_count: int = 0
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
    character: Optional[str] = None


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
    character: str
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
class CharacterStatistics:
    character: str
    candidate_count: int
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
    characters: Tuple[CharacterStatistics, ...] = ()
    total_characters: int = 0
    average_votes_per_character: float = 0.0
