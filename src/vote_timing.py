from __future__ import annotations

import asyncio
import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from .character_service import character_of
from .models import Candidate, MessageStamp, SendStatus, Vote, VoteWindow


def timestamp(value) -> Optional[str]:
    """Normalize protocol seconds/milliseconds or an ISO timestamp to UTC."""
    try:
        if isinstance(value, str) and "T" in value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            if isinstance(value, bool):
                return None
            seconds = float(value)
            if not math.isfinite(seconds) or seconds <= 0:
                return None
            if seconds >= 100_000_000_000:
                seconds /= 1000
            dt = datetime.fromtimestamp(seconds, timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def sequence(value) -> Optional[str]:
    text = str(value or "")
    return str(int(text)) if len(text) <= 20 and text.isdecimal() and int(text) > 0 else None


def event_stamp(event) -> Optional[MessageStamp]:
    # AstrBot creates this before its rate limiter. Do not substitute handler time.
    received_at = timestamp(getattr(event, "created_at", None))
    if received_at is None:
        return None
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    getter = getattr(raw, "get", None)
    return MessageStamp(
        received_at,
        timestamp(getter("time")) if callable(getter) else None,
        sequence(getter("real_seq")) if callable(getter) else None,
    )


def after_image(stamp: MessageStamp, candidate: Candidate, opened_at: str) -> bool:
    # QQ can deliver the image before the send API's acknowledgement reaches us.
    # Compare platform order with platform order; local close boundaries use receipt time.
    if stamp.sequence and candidate.message_sequence:
        return int(stamp.sequence) > int(candidate.message_sequence)
    if stamp.message_time and candidate.message_time:
        if stamp.message_time != candidate.message_time:
            return stamp.message_time > candidate.message_time
    return stamp.received_at >= opened_at


def resolve_window(
    windows: Sequence[VoteWindow], candidates: Mapping[str, Candidate], stamp: MessageStamp,
) -> Optional[Candidate]:
    for window in reversed(windows):
        if window.closed_at and stamp.received_at >= window.closed_at:
            continue
        candidate = candidates.get(window.candidate_id)
        if candidate is not None and after_image(stamp, candidate, window.opened_at):
            visible = [item for item in candidates.values() if (
                character_of(item) == character_of(candidate)
                and item.send_status == SendStatus.SENT and item.sent_at
                and after_image(stamp, item, item.sent_at)
            )]
            # Merged images share one acknowledgement; preserve its first image as the source.
            return max(visible, key=lambda item: (item.sent_at, -item.display_index)) if visible else candidate
    return None


def vote_is_later(new: Vote, old: Vote) -> bool:
    if new.message_sequence and old.message_sequence:
        return int(new.message_sequence) > int(old.message_sequence)
    new_time = timestamp(new.message_time or new.updated_at or new.created_at)
    old_time = timestamp(old.message_time or old.updated_at or old.created_at)
    if new_time and old_time and new_time != old_time:
        return new_time > old_time
    if new.received_at and old.received_at and new.received_at != old.received_at:
        return new.received_at > old.received_at
    # Legacy callers without event timestamps retain their original arrival-order policy.
    return True


def vote_wins(new: Vote, old: Vote, policy: str) -> bool:
    if new.message_id and new.message_id == old.message_id:
        return False
    if new.message_sequence and new.message_sequence == old.message_sequence:
        return False
    later = vote_is_later(new, old)
    if policy == "first_wins":
        return not later
    if policy == "max_score" and new.score != old.score:
        return new.score > old.score
    if policy == "min_score" and new.score != old.score:
        return new.score < old.score
    return later


@dataclass
class _GroupActivity:
    pending: int = 0
    idle: asyncio.Event = field(default_factory=asyncio.Event)
    sealed_session: Optional[str] = None
    sending: Optional[asyncio.Event] = None

    def __post_init__(self):
        self.idle.set()


class VoteActivity:
    """Track handlers before their first await; seal only after accepted work drains."""

    def __init__(self):
        self._groups = {}

    def _group(self, group_id):
        return self._groups.setdefault(group_id, _GroupActivity())

    @contextmanager
    def receiving(self, group_id):
        group = self._group(group_id)
        group.pending += 1
        group.idle.clear()
        try:
            yield
        finally:
            group.pending -= 1
            if not group.pending:
                group.idle.set()

    def reopen(self, group_id):
        self._group(group_id).sealed_session = None

    def is_sealed(self, session):
        return self._group(session.group_id).sealed_session == session.id

    async def seal(self, session):
        group = self._group(session.group_id)
        while group.pending:
            await group.idle.wait()
        group.sealed_session = session.id

    def start_send(self, group_id):
        self._group(group_id).sending = asyncio.Event()

    def finish_send(self, group_id):
        group = self._group(group_id)
        if group.sending is not None:
            group.sending.set()
            group.sending = None

    async def wait_for_send(self, group_id):
        sending = self._group(group_id).sending
        if sending is not None:
            await sending.wait()
            return True
        return False
