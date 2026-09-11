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
