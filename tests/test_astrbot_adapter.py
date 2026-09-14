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

    def test_vote_message_shows_project_and_title_without_duplicate_id(self):
        session = Session(
            "s1", "A7F3", "g1", "umo", "海滨之家", "/tmp/demo", SessionStatus.RUNNING, candidate_count=10
        )
        candidate = Candidate("c1", "s1", 3, "three.png", "three.png", "Three", None, 1)
        text = build_vote_message(session, candidate)
        self.assertIn("[投票 003/010 · A7F3]", text)
        self.assertIn("海滨之家 · Three", text)
        self.assertNotIn("[VOTE:", text)
        self.assertEqual(text.count("A7F3"), 1)

    def test_vote_message_follows_configured_score_range(self):
        session = Session(
            "s1", "A7F3", "g1", "umo", "demo", "/tmp/demo", SessionStatus.RUNNING,
            candidate_count=10, score_min=1, score_max=10,
        )
        candidate = Candidate("c1", "s1", 3, "three.png", "three.png", "Three", None, 1)
        self.assertIn("回复 1-10 评分", build_vote_message(session, candidate))

    def test_send_file_wraps_components_in_a_message_chain(self):
        import sys
        import types

        captured = {}

        class FakeMessageChain:
            def __init__(self, chain=None):
                self.chain = list(chain or [])

        class FakeFile:
            def __init__(self, name=None, file=None):
                self.name = name
                self.file_ = file

        class FakePlain:
            def __init__(self, text=""):
                self.text = text

        event_module = types.ModuleType("astrbot.api.event")
        event_module.MessageChain = FakeMessageChain
        components_module = types.ModuleType("astrbot.api.message_components")
        components_module.File = FakeFile
        components_module.Plain = FakePlain
        api_module = types.ModuleType("astrbot.api")
        api_module.event = event_module
        api_module.message_components = components_module
        astrbot_module = types.ModuleType("astrbot")
        astrbot_module.api = api_module
        keys = ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.message_components")
        saved = {key: sys.modules.get(key) for key in keys}
        sys.modules.update(
            {
                "astrbot": astrbot_module,
                "astrbot.api": api_module,
                "astrbot.api.event": event_module,
                "astrbot.api.message_components": components_module,
            }
        )
        try:
            class Context:
                async def send_message(self, umo, chain):
                    captured["umo"] = umo
                    captured["chain"] = chain
                    return True

            adapter = AstrBotAdapter(Context())
            asyncio.run(
                adapter.send_file("group:1", Path("/tmp/reports/demo/index.html"), name="demo.html")
            )
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value

        chain = captured["chain"]
        self.assertIsInstance(chain, FakeMessageChain)
        self.assertEqual([type(item).__name__ for item in chain.chain], ["FakePlain", "FakeFile"])
        self.assertEqual(chain.chain[0].text, "demo.html")
        self.assertEqual(chain.chain[1].file_, "/tmp/reports/demo/index.html")
