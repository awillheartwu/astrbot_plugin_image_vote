from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, Sequence

from .models import SendReceipt
from .reply_resolver import ReplyPayload


class PlatformAdapter(Protocol):
    async def send_vote_message(self, umo: str, text: str, image_paths: Sequence[Path]) -> SendReceipt:
        """Send vote images and return acknowledgement and optional platform metadata."""

    def resolve_reply(self, raw_event: object) -> Optional[ReplyPayload]:
        """Return a platform-neutral ReplyPayload or None."""
