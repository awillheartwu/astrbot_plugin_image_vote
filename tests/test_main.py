import asyncio
import unittest

from main import ImageVotePlugin


class FakeContext:
    def get_config(self):
        return {"input_root": "./projects", "output_root": "./reports"}


class FakeEvent:
    def __init__(self, text):
        self.message_str = text

    def plain_result(self, text):
        return text


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
