from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Optional, Tuple

from .character_service import character_of
from .models import Candidate, Session, SessionStatus, VoteDecision, VoteSource
from .reply_resolver import ReplyPayload, ReplyResolver


class VoteParser:
    _SCORE_PATTERN = re.compile(r"^([0-9]+)(?:\s*分)?$")
    # AstrBot 会把「@其他用户」拼进 message_str，形如 " @昵称(qq) "，投票时应忽略
    _AT_FRAGMENT = re.compile(r"@[^\s@]*\(\d+\)")

    def __init__(self, score_min: int = 1, score_max: int = 4):
        self.score_min = score_min
        self.score_max = score_max
        self.score_digits = max(1, len(str(max(score_max, 0))))

    def extract_digits(self, text: str) -> Optional[str]:
        """整条消息是分数形式时返回数字部分（支持 8 与 8分 两种写法），否则 None。"""
        value = unicodedata.normalize("NFKC", text or "").strip()
        if self._AT_FRAGMENT.search(value):
            value = self._AT_FRAGMENT.sub(" ", value).strip()
        if not value:
            return None
        match = self._SCORE_PATTERN.match(value)
        return match.group(1) if match else None

    def parse(self, text: str) -> Optional[int]:
        digits = self.extract_digits(text)
        if digits is None or len(digits) > self.score_digits:
            return None
        if len(digits) > 1 and digits.startswith("0"):
            return None
        score = int(digits)
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
        return self.route_with_reason(text, session, active_candidate, candidates_by_index, reply)[0]

    def route_with_reason(
        self,
        text: str,
        session: Session,
        active_candidate: Optional[Candidate],
        candidates_by_index: Mapping[int, Candidate],
        reply: Optional[ReplyPayload] = None,
    ) -> Tuple[Optional[VoteDecision], Optional[str]]:
        """返回 (决策, 忽略原因)。原因只在「看起来像投票但没收下」时给出，方便事后对账。"""
        parser = self._parser_for(session)
        digits = parser.extract_digits(text)
        score = parser.parse(text)
        if score is None:
            if digits is None:
                return None, None
            if len(digits) > 1 and digits.startswith("0"):
                return None, "前导零不识别"
            return None, "超出评分范围 %d-%d" % (session.score_min, session.score_max)
        if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
            return None, "本场不在收票状态（%s）" % session.status.value
        if reply is not None:
            if not self.allow_quoted_vote_after_window:
                return None, "引用投票已关闭"
            quoted_candidate = self.reply_resolver.resolve_candidate(reply, session.short_id, candidates_by_index)
            if quoted_candidate is None:
                return None, "引用的消息不是本场投票图"
            return VoteDecision(
                quoted_candidate.id, character_of(quoted_candidate), score, VoteSource.QUOTED_REPLY
            ), None
        if active_candidate is None:
            return None, "还没有成功发送的图片"
        character = getattr(session, "active_character", None) or character_of(active_candidate)
        return VoteDecision(active_candidate.id, character, score, VoteSource.CURRENT_WINDOW), None

    def _parser_for(self, session: Session) -> VoteParser:
        """计票范围以会话为准；运行中改配置只影响以后新建的会话。"""
        session_min = getattr(session, "score_min", self.parser.score_min)
        session_max = getattr(session, "score_max", self.parser.score_max)
        if (session_min, session_max) == (self.parser.score_min, self.parser.score_max):
            return self.parser
        return VoteParser(session_min, session_max)
