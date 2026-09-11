import asyncio
import unittest
from pathlib import Path

from src.astrbot_adapter import AstrBotAdapter
from src.message_sender import build_vote_message
from src.models import Candidate, Session, SessionStatus


class Reply:
    def __init__(self):
        self.message_str = "[投票 003/010 · A7F3]"
        self.chain = []
        self.id = 123


class MessageObject:
    def __init__(self):
        self.message = [Reply()]
        self.message_id = 456


class Event:
    message_obj = MessageObject()


class AstrBotAdapterTest(unittest.TestCase):
    def test_reply_is_normalized_without_importing_astrbot(self):
        payload = AstrBotAdapter(object()).resolve_reply(Event())
        self.assertEqual(payload.message_str, "[投票 003/010 · A7F3]")
        self.assertEqual(payload.message_id, "123")

    def test_vote_message_contains_both_human_and_machine_markers(self):
        session = Session("s1", "A7F3", "g1", "umo", "demo", "/tmp/demo", SessionStatus.RUNNING, candidate_count=10)
        candidate = Candidate("c1", "s1", 3, "three.png", "three.png", "Three", None, 1)
        text = build_vote_message(session, candidate)
        self.assertIn("[投票 003/010 · A7F3]", text)
        self.assertIn("[VOTE:A7F3:3]", text)

    def test_vote_message_follows_configured_score_range(self):
        session = Session(
            "s1", "A7F3", "g1", "umo", "demo", "/tmp/demo", SessionStatus.RUNNING,
            candidate_count=10, score_min=1, score_max=10,
        )
        candidate = Candidate("c1", "s1", 3, "three.png", "three.png", "Three", None, 1)
        self.assertIn("回复 1-10 评分", build_vote_message(session, candidate))
