from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from .models import Candidate, SendContext, Session


def build_vote_message(session: Session, candidate: Candidate, context: Optional[SendContext] = None) -> str:
    """群里的投票消息：首行只放「项目 · 人物」，第二行给进度，第三行是打分方法，
    最后一行才是引用投票的定位标记（见 reply_resolver 的 VOTE_MARKER_RE）。

    标记放在末行不会影响引用投票：AstrBot 的 aiocqhttp 适配器收到 reply 段会用
    get_msg 取回被引用消息的完整文本与 chain，解析时扫描整段文本。
    """
    context = context or candidate.send_context or SendContext()
    character = candidate.character or candidate.display_title
    return "\n".join(
        [
            "%s · %s" % (session.project_name, character),
            _position_line(context),
            "回复 %d-%d 给「%s」打分 · 引用本场任意图片可改分"
            % (session.score_min, session.score_max, character),
            "[投票 %03d/%03d · %s]" % (candidate.display_index, session.candidate_count, session.short_id),
        ]
    )


def _position_line(context: SendContext) -> str:
    """第二行：第几位人物 + 该人物第几张；未发完的人物会写明还剩几张。"""
    if context.character_total > 1:
        head = "第 %d/%d 位人物" % (context.character_ordinal, context.character_total)
    else:
        head = "本场唯一人物"
    parts = [head, _image_span(context)]
    marker = _progress_marker(context)
    if marker:
        parts.append(marker)
    return " · ".join(parts)


def _image_span(context: SendContext) -> str:
    total = max(1, context.image_count)
    first = max(1, context.image_ordinal)
    span = max(1, context.image_span)
    if total == 1:
        return "本人物共 1 张"
    if span <= 1:
        return "第 %d/%d 张" % (first, total)
    if span >= total:
        return "共 %d 张（本条全部）" % total
    return "第 %d-%d/%d 张（本条 %d 张）" % (first, min(first + span - 1, total), total, span)


def _progress_marker(context: SendContext) -> str:
    """中继标记：人物还有图没发完时提示剩余张数，发完时明确收尾。"""
    total = max(1, context.image_count)
    sent_through = max(1, context.image_ordinal) + max(1, context.image_span) - 1
    remaining = total - sent_through
    if remaining > 0:
        return "之后还有 %d 张" % remaining
    if context.image_span > 1 or context.group_ordinal > 1:
        return "本人物已发完"
    return ""


SendFunction = Callable[[str, str, Sequence[Path]], Awaitable[Optional[str]]]


class MessageSender:
    def __init__(self, send_function: SendFunction, max_retries: int = 3, retry_base_seconds: int = 2):
        self.send_function = send_function
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds

    async def send_candidate(self, session: Session, candidate: Candidate, image_paths: Sequence[Path]) -> Optional[str]:
        text = build_vote_message(session, candidate)
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self.send_function(session.umo, text, image_paths)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(self.retry_base_seconds * (attempt + 1))
        raise RuntimeError("failed to send candidate %s: %s" % (candidate.id, last_error))
