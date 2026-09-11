from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Optional

from .models import Candidate, Session, SessionStatus, VoteDecision, VoteSource
from .reply_resolver import ReplyPayload, ReplyResolver


class VoteParser:
    def __init__(self, score_min: int = 1, score_max: int = 4):
        self.score_min = score_min
        self.score_max = score_max
        self.score_digits = max(1, len(str(max(score_max, 0))))

    def parse(self, text: str) -> Optional[int]:
        value = unicodedata.normalize("NFKC", text or "").strip()
        if not value or len(value) > self.score_digits:
            return None
        if not re.fullmatch(r"[0-9]+", value):
            return None
        if len(value) > 1 and value.startswith("0"):
            return None
        score = int(value)
        if self.score_min <= score <= self.score_max:
            return score
        return None


class VoteRouter:
    def __init__(
        self,
        parser: VoteParser = None,
        reply_resolver: ReplyResolver = None,
        allow_quoted_vote_after_window: bool = True,
    ):
        self.parser = parser or VoteParser()
        self.reply_resolver = reply_resolver or ReplyResolver()
        self.allow_quoted_vote_after_window = allow_quoted_vote_after_window

    def route(
        self,
        text: str,
        session: Session,
        active_candidate: Optional[Candidate],
        candidates_by_index: Mapping[int, Candidate],
        reply: Optional[ReplyPayload] = None,
    ) -> Optional[VoteDecision]:
        score = self.parser.parse(text)
        if score is None or session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
            return None
        if reply is not None:
            if not self.allow_quoted_vote_after_window:
                return None
            quoted_candidate = self.reply_resolver.resolve_candidate(reply, session.short_id, candidates_by_index)
            if quoted_candidate is None:
                return None
            return VoteDecision(quoted_candidate.id, score, VoteSource.QUOTED_REPLY)
        if active_candidate is None:
            return None
        return VoteDecision(active_candidate.id, score, VoteSource.CURRENT_WINDOW)
