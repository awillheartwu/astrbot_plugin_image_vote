from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

from .models import Candidate


VOTE_MARKER_RE = re.compile(r"\[投票\s+(?P<index>\d+)\s*/\s*(?P<total>\d+)\s+·\s*(?P<short_id>[A-Za-z0-9]+)\]")
INTERNAL_MARKER_RE = re.compile(r"\[VOTE:(?P<short_id>[A-Za-z0-9]+):(?P<index>\d+)\]")


@dataclass(frozen=True)
class ReplyPayload:
    message_str: str = ""
    chain_text: str = ""
    message_id: Optional[str] = None

    @property
    def text(self) -> str:
        return "%s\n%s" % (self.message_str, self.chain_text)


@dataclass(frozen=True)
class VoteMarker:
    session_short_id: str
    display_index: int
    total_candidates: Optional[int] = None


def extract_vote_marker(text: str) -> Optional[VoteMarker]:
    match = VOTE_MARKER_RE.search(text or "")
    if match:
        return VoteMarker(
            session_short_id=match.group("short_id"),
            display_index=int(match.group("index")),
            total_candidates=int(match.group("total")),
        )
    match = INTERNAL_MARKER_RE.search(text or "")
    if match:
        return VoteMarker(session_short_id=match.group("short_id"), display_index=int(match.group("index")))
    return None


class ReplyResolver:
    def resolve_candidate(
        self,
        reply: ReplyPayload,
        session_short_id: str,
        candidates_by_index: Mapping[int, Candidate],
    ) -> Optional[Candidate]:
        marker = extract_vote_marker(reply.text)
        if marker is None or marker.session_short_id != session_short_id:
            return None
        return candidates_by_index.get(marker.display_index)
