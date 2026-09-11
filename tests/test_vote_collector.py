import unittest

from src.models import Candidate, Session, SessionStatus, VoteSource
from src.reply_resolver import ReplyPayload
from src.vote_collector import VoteParser, VoteRouter


def candidate(index, candidate_id=None):
    return Candidate(
        id=candidate_id or "candidate-%d" % index,
        session_id="session-1",
        display_index=index,
        source_relative_path="%04d.png" % index,
        source_filename="%04d.png" % index,
        display_title="Candidate %d" % index,
        sequence_number=None,
        source_size=1,
    )


class VoteCollectorTest(unittest.TestCase):
    def test_parser_is_strict(self):
        parser = VoteParser()
        self.assertEqual(parser.parse("1"), 1)
        self.assertEqual(parser.parse(" 4 "), 4)
        for value in ("0", "5", "03", "3分", "评分3", "3.0", "1 2", "👍3"):
            self.assertIsNone(parser.parse(value))

    def test_parser_accepts_two_digits_when_range_allows(self):
        parser = VoteParser(1, 10)
        self.assertEqual(parser.parse("10"), 10)
        self.assertEqual(parser.parse(" 9 "), 9)
        for value in ("11", "05", "0", "100", "10分"):
            self.assertIsNone(parser.parse(value))
        five = VoteParser(1, 5)
        self.assertEqual(five.parse("5"), 5)
        self.assertIsNone(five.parse("6"))
        self.assertIsNone(five.parse("10"))

    def test_parser_normalizes_full_width_digits(self):
        self.assertEqual(VoteParser(1, 4).parse("３"), 3)
        self.assertEqual(VoteParser(1, 10).parse("１０"), 10)
        self.assertIsNone(VoteParser(1, 4).parse("３分"))

    def test_current_window_routes_to_active_candidate(self):
        session = Session("session-1", "A7F3", "group-1", "umo", "project", "/tmp/project", SessionStatus.RUNNING)
        active = candidate(10)
        decision = VoteRouter().route("3", session, active, {10: active})
        self.assertEqual(decision.candidate_id, active.id)
        self.assertEqual(decision.source_type, VoteSource.CURRENT_WINDOW)

    def test_quoted_vote_routes_to_quoted_candidate(self):
        session = Session("session-1", "A7F3", "group-1", "umo", "project", "/tmp/project", SessionStatus.RUNNING)
        active = candidate(10)
        quoted = candidate(3)
        reply = ReplyPayload(message_str="[投票 003/010 · A7F3]")
        decision = VoteRouter().route("4", session, active, {3: quoted, 10: active}, reply)
        self.assertEqual(decision.candidate_id, quoted.id)
        self.assertEqual(decision.source_type, VoteSource.QUOTED_REPLY)
        invalid_reply = ReplyPayload(message_str="[投票 003/010 · OLD1]")
        self.assertIsNone(VoteRouter().route("4", session, active, {3: quoted, 10: active}, invalid_reply))
        self.assertIsNone(
            VoteRouter(allow_quoted_vote_after_window=False).route(
                "4", session, active, {3: quoted, 10: active}, reply
            )
        )

    def test_router_uses_session_score_range(self):
        narrow = Session(
            "session-1", "A7F3", "group-1", "umo", "project", "/tmp/project",
            SessionStatus.RUNNING, score_min=1, score_max=4,
        )
        wide = Session(
            "session-2", "B1C2", "group-1", "umo", "project", "/tmp/project",
            SessionStatus.RUNNING, score_min=1, score_max=10,
        )
        active = candidate(10)
        router = VoteRouter(VoteParser(1, 10))
        self.assertIsNone(router.route("10", narrow, active, {10: active}))
        decision = router.route("10", wide, active, {10: active})
        self.assertIsNotNone(decision)
        self.assertEqual(decision.score, 10)
