import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from main import ImageVotePlugin
from src.models import Candidate, Session, SessionStatus


class FakeContext:
    def get_config(self):
        return {"input_root": "./projects", "output_root": "./reports"}


class TempContext:
    """把 input_root / output_root 指到临时目录，避免测试写进仓库。"""

    def __init__(self, root):
        self._root = Path(root)

    def get_config(self):
        return {
            "input_root": str(self._root / "projects"),
            "output_root": str(self._root / "reports"),
        }


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


class AdminEvent(FakeEvent):
    def is_admin(self):
        return True

    def get_group_id(self):
        return "g1"


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
            self.assertIn("暂无项目", replies[0])

        asyncio.run(scenario())

    def test_register_unregister_and_projects_commands(self):
        async def scenario(root):
            deep = root / "deep" / "人物图"
            deep.mkdir(parents=True)
            plugin = ImageVotePlugin(TempContext(root))

            denied = [item async for item in plugin.vote_command(FakeEvent("/vote projects"))]
            self.assertIn("管理员", denied[0])

            registered = [
                item async for item in plugin.vote_command(AdminEvent("/vote register 海滨之家 %s" % deep))
            ]
            self.assertIn("已登记：海滨之家", registered[0])

            listing = [item async for item in plugin.vote_command(AdminEvent("/vote projects"))]
            self.assertIn("海滨之家", listing[0])
            self.assertIn(str(deep), listing[0])

            merged = [item async for item in plugin.vote_command(AdminEvent("/vote list"))]
            self.assertIn("注册项目：海滨之家", merged[0])

            removed = [item async for item in plugin.vote_command(AdminEvent("/vote unregister 海滨之家"))]
            self.assertIn("已取消登记", removed[0])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_reloadconfig_reports_effective_values(self):
        async def scenario(root):
            plugin = ImageVotePlugin(TempContext(root))
            await plugin.store.initialize()

            replies = [item async for item in plugin.vote_command(AdminEvent("/vote reloadconfig"))]
            self.assertIn("已重新读取配置", replies[0])
            self.assertIn("发送间隔：20 秒", replies[0])
            self.assertIn("报告模式：directory", replies[0])

            denied = [item async for item in plugin.vote_command(FakeEvent("/vote reloadconfig"))]
            self.assertIn("管理员", denied[0])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_config_file_wins_over_stale_instance_attribute(self):
        async def scenario(root):
            plugin = ImageVotePlugin(TempContext(root))
            await plugin.store.initialize()
            plugin.config = {"default_interval_seconds": 20}
            config_file = (
                Path(plugin.store.database_path).parent.parent
                / "config"
                / "astrbot_plugin_image_vote_config.json"
            )
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(
                json.dumps({"default_interval_seconds": 5, "report_mode": "single_html"}), encoding="utf-8"
            )

            plugin._ensure_config()
            self.assertEqual(plugin.settings.default_interval_seconds, 5)
            self.assertEqual(plugin.settings.report_mode, "single_html")
            self.assertIn("配置文件", plugin._config_source)

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

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

    def test_control_replies_describe_the_action(self):
        session = Session(
            "s1", "A1B2C3D4", "g1", "umo", "海滨之家", "/pictures/x", SessionStatus.RUNNING,
            candidate_count=19, current_index=7,
        )
        paused = ImageVotePlugin._control_reply("pause", session)
        self.assertIn("已暂停：海滨之家", paused)
        self.assertIn("进度：7 / 19", paused)
        self.assertIn("/vote resume", paused)
        self.assertIn("项目：海滨之家 · Session：A1B2C3D4 · 状态：RUNNING", paused)

        resumed = ImageVotePlugin._control_reply("resume", session)
        self.assertIn("已继续：海滨之家", resumed)
        self.assertIn("从第 8 张接着发送", resumed)

        finished = ImageVotePlugin._control_reply("finish", session)
        self.assertIn("已请求提前结束", finished)
        self.assertIn("按现有票数结算", finished)

        stopped = ImageVotePlugin._control_reply("stop", session)
        self.assertIn("已取消本次投票", stopped)
        self.assertIn("/vote export", stopped)

    def test_control_command_without_session_replies_clearly(self):
        async def scenario(root):
            plugin = ImageVotePlugin(TempContext(root))
            await plugin.store.initialize()
            replies = [item async for item in plugin.vote_command(AdminEvent("/vote pause"))]
            self.assertIn("当前群没有进行中的投票", replies[0])
            replies = [item async for item in plugin.vote_command(AdminEvent("/vote resume"))]
            self.assertIn("可恢复", replies[0])

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))
