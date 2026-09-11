import importlib
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class PackageImportTest(unittest.TestCase):
    def test_main_imports_as_astrbot_plugin_package(self):
        """AstrBot 以 data.plugins.<插件名>.main 加载插件，顶层 src 不在 sys.path 上。"""
        package_name = "astrbot_plugin_image_vote_pkgtest"
        with tempfile.TemporaryDirectory() as directory:
            plugins_dir = Path(directory) / "data" / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / package_name).symlink_to(REPO_ROOT, target_is_directory=True)
            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("data.plugins.%s.main" % package_name)
                self.assertEqual(module.__package__, "data.plugins.%s" % package_name)
                self.assertTrue(callable(module.ImageVotePlugin))
                self.assertTrue(callable(module.VoteApplication))
            finally:
                sys.path.remove(directory)
                for name in [item for item in sys.modules if item.startswith("data.")]:
                    sys.modules.pop(name, None)
