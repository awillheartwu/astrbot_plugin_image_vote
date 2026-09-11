import json
import tempfile
import unittest
from pathlib import Path

from src.path_guard import PathGuard, UnsafePathError


class PathGuardTest(unittest.TestCase):
    def test_rejects_traversal_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = PathGuard(Path(directory))
            with self.assertRaises(UnsafePathError):
                guard.resolve_child("../../etc")
            with self.assertRaises(UnsafePathError):
                guard.resolve_child("/etc")

    def test_report_marker_is_required_and_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "project" / "session"
            report.mkdir(parents=True)
            (report / ".astrbot_image_vote_report").write_text(
                json.dumps({"plugin": "astrbot_plugin_image_vote"}), encoding="utf-8"
            )
            guard = PathGuard(root)
            self.assertEqual(
                guard.ensure_report_directory(report, ".astrbot_image_vote_report", "astrbot_plugin_image_vote"),
                report.resolve(),
            )
            with self.assertRaises(UnsafePathError):
                guard.ensure_report_directory(report, ".astrbot_image_vote_report", "other-plugin")

