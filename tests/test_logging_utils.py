import logging
import sys
import types
import unittest

from src import logging_utils


class LoggingUtilsTest(unittest.TestCase):
    def test_prefers_astrbot_plugin_logger(self):
        stub = logging.getLogger("astrbot.plugin.astrbot_plugin_image_vote")

        class LogManager:
            @staticmethod
            def get_plugin_logger(name):
                return stub

        module = types.ModuleType("astrbot.core.log")
        module.LogManager = LogManager
        core = types.ModuleType("astrbot.core")
        core.log = module
        astrbot = types.ModuleType("astrbot")
        astrbot.core = core
        keys = ("astrbot", "astrbot.core", "astrbot.core.log")
        saved = {key: sys.modules.get(key) for key in keys}
        sys.modules.update({"astrbot": astrbot, "astrbot.core": core, "astrbot.core.log": module})
        try:
            self.assertIs(logging_utils.get_logger(), stub)
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value

    def test_falls_back_to_plain_named_logger(self):
        keys = ("astrbot", "astrbot.core", "astrbot.core.log")
        saved = {key: sys.modules.get(key) for key in keys}
        for key in keys:
            sys.modules.pop(key, None)
        try:
            self.assertEqual(logging_utils.get_logger().name, "astrbot_plugin_image_vote")
        finally:
            for key, value in saved.items():
                if value is not None:
                    sys.modules[key] = value


if __name__ == "__main__":
    unittest.main()
