from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .models import Candidate, Session


def build_vote_message(session: Session, candidate: Candidate) -> str:
    return (
        "[投票 %03d/%03d · %s]\n"
        "%s · %s · %s\n"
        "本组图片均属于「%s」；回复 %d-%d 评分给该人物，也可引用本场任意图片改评对应人物"
        % (
            candidate.display_index,
            session.candidate_count,
            session.short_id,
            session.project_name,
            candidate.character or candidate.display_title,
            candidate.display_title,
            candidate.character or candidate.display_title,
            session.score_min,
            session.score_max,
        )
    )


SendFunction = Callable[[str, str, Path], Awaitable[Optional[str]]]


class MessageSender:
    def __init__(self, send_function: SendFunction, max_retries: int = 3, retry_base_seconds: int = 2):
        self.send_function = send_function
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds

    async def send_candidate(self, session: Session, candidate: Candidate, image_path: Path) -> Optional[str]:
        text = build_vote_message(session, candidate)
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self.send_function(session.umo, text, image_path)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(self.retry_base_seconds * (attempt + 1))
        raise RuntimeError("failed to send candidate %s: %s" % (candidate.id, last_error))
