import asyncio
import unittest
from types import SimpleNamespace

from main import ImageVotePlugin
from src.models import Candidate, Session, SessionStatus


class FakeContext:
    def get_config(self):
        return {"input_root": "./projects", "output_root": "./reports"}


class FakeEvent:
    def __init__(self, text):
        self.message_str = text

    def plain_result(self, text):
        return text


class SelfMessageEvent:
    """机器人自己发出的消息：self_id 与发送者一致。"""

    def __init__(self):
        self.message_str = "3"
        self.message_obj = SimpleNamespace(
            self_id="999",
            message_id="m1",
            group_id="g1",
            sender=SimpleNamespace(user_id="999", nickname="bot"),
        )

    def get_group_id(self):
        return "g1"

    def get_sender_id(self):
        return "999"

    def get_sender_name(self):
        return "bot"


class MainTest(unittest.TestCase):
    def test_command_parser_preserves_project_name_spaces(self):
        self.assertEqual(ImageVotePlugin._parse_command("/vote check My Project"), ("check", "My Project"))
        self.assertEqual(ImageVotePlugin._parse_command("My Project"), ("start", "My Project"))

    def test_command_parser_accepts_text_without_leading_slash(self):
        """AstrBot 会把消息开头的 / 去掉再交给命令处理器。"""
        self.assertEqual(ImageVotePlugin._parse_command("vote list"), ("list", ""))
        self.assertEqual(ImageVotePlugin._parse_command("vote check sample"), ("check", "sample"))
        self.assertEqual(ImageVotePlugin._parse_command("vote sample"), ("start", "sample"))
        self.assertEqual(ImageVotePlugin._parse_command("vote"), ("", ""))
        self.assertEqual(ImageVotePlugin._parse_command("/vote"), ("", ""))

    def test_list_command_is_an_async_generator_response(self):
        async def scenario():
            plugin = ImageVotePlugin(FakeContext())
            replies = [item async for item in plugin.vote_command(FakeEvent("/vote list"))]
            self.assertEqual(len(replies), 1)
            self.assertIn("可用项目", replies[0])

        asyncio.run(scenario())

    def test_start_command_requires_group_context(self):
        async def scenario():
            plugin = ImageVotePlugin(FakeContext())
            replies = [item async for item in plugin.vote_command(FakeEvent("/vote demo"))]
            self.assertEqual(replies, ["该插件只支持 QQ 群消息。"])

        asyncio.run(scenario())

    def test_active_candidate_prefers_last_successful_send(self):
        candidates = [
            Candidate("c1", "s1", 1, "1.png", "1.png", "One", None, 1),
            Candidate("c2", "s1", 2, "2.png", "2.png", "Two", None, 1),
            Candidate("c3", "s1", 3, "3.png", "3.png", "Three", None, 1),
        ]
        session = Session(
            "s1", "A7F3", "g1", "umo", "demo", "/tmp/demo", SessionStatus.RUNNING,
            candidate_count=3, active_candidate_id="c1", current_index=3,
        )
        self.assertEqual(ImageVotePlugin._active_candidate(session, candidates).id, "c1")
        session.active_candidate_id = None
        self.assertEqual(ImageVotePlugin._active_candidate(session, candidates).id, "c3")

    def test_self_messages_are_ignored(self):
        async def scenario():
            plugin = ImageVotePlugin(FakeContext())
            self.assertIsNone(await plugin.on_group_message(SelfMessageEvent()))

        asyncio.run(scenario())
