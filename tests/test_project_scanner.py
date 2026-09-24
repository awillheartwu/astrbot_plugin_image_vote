import json
import tempfile
import unittest
from pathlib import Path

from src.project_scanner import parse_image_filename, scan_project
from src.project_service import ProjectService


class ProjectScannerTest(unittest.TestCase):
    def test_numbered_files_sort_by_integer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "screenshot0002 - MC - a.png",
                "screenshot0010 - Alice - b.png",
                "screenshot0001 - MC - c.png",
            ):
                (root / name).write_bytes(b"image")
            snapshot = scan_project(root)
            self.assertEqual([item.display_index for item in snapshot.candidates], [1, 2, 3])
            self.assertEqual(
                [item.source_filename for item in snapshot.candidates],
                [
                    "screenshot0001 - MC - c.png",
                    "screenshot0002 - MC - a.png",
                    "screenshot0010 - Alice - b.png",
                ],
            )

    def test_plain_names_are_deterministic_and_keep_full_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Grace-现代版本.png", "Grace-白色礼服.png", "Carol-Bella的兄弟.png"):
                (root / name).write_bytes(b"image")
            first = scan_project(root)
            second = scan_project(root)
            self.assertEqual(
                [item.source_filename for item in first.candidates],
                [item.source_filename for item in second.candidates],
            )
            self.assertEqual(first.candidates[0].display_title, "Carol-Bella的兄弟")

    def test_mixed_names_emit_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "screenshot0002 - MC - a.png").write_bytes(b"image")
            (root / "plain-1.png").write_bytes(b"image")
            snapshot = scan_project(root)
            self.assertEqual(snapshot.sort_mode, "mixed")
            self.assertTrue(snapshot.warnings)

    def test_project_alias_file_resolves_without_scanning_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real-project").mkdir()
            (root / "project_alias.json").write_text('{"别名": "real-project"}', encoding="utf-8")
            self.assertEqual(ProjectService(root).resolve_project_path("别名"), (root / "real-project").resolve())

    def test_character_is_derived_and_manifest_can_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Aurora-现代版本.png", "Aurora-老年版本.png", "Cass-废土风格.png"):
                (root / name).write_bytes(b"image")

            snapshot = scan_project(root)
            by_name = {item.source_filename: item.character for item in snapshot.candidates}
            self.assertEqual(by_name["Aurora-现代版本.png"], "Aurora")
            self.assertEqual(by_name["Aurora-老年版本.png"], "Aurora")
            self.assertEqual(by_name["Cass-废土风格.png"], "Cass")

            (root / "project.json").write_text(
                json.dumps(
                    {"characters": {"Cassandra": ["Cass-废土风格.png", "Aurora-老年版本.png"]}}
                ),
                encoding="utf-8",
            )
            snapshot = scan_project(root)
            by_name = {item.source_filename: item.character for item in snapshot.candidates}
            self.assertEqual(by_name["Cass-废土风格.png"], "Cassandra")
            self.assertEqual(by_name["Aurora-老年版本.png"], "Cassandra")
            self.assertEqual(by_name["Aurora-现代版本.png"], "Aurora")

    def test_manifest_character_becomes_display_title(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "u4ia_0001 - 亚伦 - 631cd9c5.png",
                "u4ia_0002 - 安娜 - d40a1207.png",
                "u4ia_0003 - 亚伦 - a1eaff85.png",
                "screenshot0004 - Vess - 30279726.png",
            ):
                (root / name).write_bytes(b"image")

            (root / "project.json").write_text(
                json.dumps(
                    {
                        "files": [
                            "u4ia_0001 - 亚伦 - 631cd9c5.png",
                            "u4ia_0002 - 安娜 - d40a1207.png",
                            "u4ia_0003 - 亚伦 - a1eaff85.png",
                        ],
                        "characters": {
                            "亚伦": [
                                "u4ia_0001 - 亚伦 - 631cd9c5.png",
                                "u4ia_0003 - 亚伦 - a1eaff85.png",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            titles = {item.source_filename: item.display_title for item in scan_project(root).candidates}
            self.assertEqual(titles["u4ia_0001 - 亚伦 - 631cd9c5.png"], "亚伦")
            self.assertEqual(titles["u4ia_0003 - 亚伦 - a1eaff85.png"], "亚伦")
            self.assertEqual(titles["u4ia_0002 - 安娜 - d40a1207.png"], "u4ia_0002 - 安娜 - d40a1207")
            self.assertEqual(titles["screenshot0004 - Vess - 30279726.png"], "Vess")

    def test_same_character_images_are_contiguous_by_first_appearance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "screenshot0001 - A - aaaaaa.png",
                "screenshot0002 - B - bbbbbb.png",
                "screenshot0003 - A - cccccc.png",
            ):
                (root / name).write_bytes(b"image")
            snapshot = scan_project(root)
            self.assertEqual([item.character for item in snapshot.candidates], ["A", "A", "B"])
            self.assertEqual([item.sequence_number for item in snapshot.candidates], [1, 3, 2])
            self.assertEqual([item.display_index for item in snapshot.candidates], [1, 2, 3])

    def test_pipeline_markers_are_stripped_from_display_title(self):
        cases = {
            "screenshot0020 - Vess - 30279726 - reset-1.png": ("Vess", 20),
            "screenshot0018 - Jade - da0ee2fb.png": ("Jade", 18),
            "screenshot0007 - Keodele - dbf95d0e - reset-2.png": ("Keodele", 7),
            "screenshot0001 - Celine - 125e896f.png": ("Celine", 1),
        }
        for filename, expected in cases.items():
            self.assertEqual(parse_image_filename(filename), expected, filename)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in cases:
                (root / filename).write_bytes(b"image")
            snapshot = scan_project(root)
            by_name = {item.source_filename: (item.display_title, item.character) for item in snapshot.candidates}
            self.assertEqual(by_name["screenshot0020 - Vess - 30279726 - reset-1.png"], ("Vess", "Vess"))
            self.assertEqual(by_name["screenshot0007 - Keodele - dbf95d0e - reset-2.png"], ("Keodele", "Keodele"))
