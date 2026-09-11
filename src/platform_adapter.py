from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from .reply_resolver import ReplyPayload


class PlatformAdapter(Protocol):
    async def send_vote_message(self, umo: str, text: str, image_path: Path) -> Optional[str]:
        """Send one vote image and return a platform message id when available."""

    def resolve_reply(self, raw_event: object) -> Optional[ReplyPayload]:
        """Return a platform-neutral ReplyPayload or None."""
