import json
import tempfile
import unittest
from pathlib import Path

from src.project_registry import ProjectRegistry, ProjectRegistryError
from src.project_service import ProjectService


class ProjectRegistryTest(unittest.TestCase):
    def test_register_resolve_and_external_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deep = root / "08_SLG" / "00XX_海滨之家" / "人物图"
            deep.mkdir(parents=True)
            registry = ProjectRegistry(root / "projects.json")

            registry.register("海滨之家", deep, interval_seconds=5)
            self.assertEqual(registry.names(), ["海滨之家"])
            self.assertEqual(registry.resolve("海滨之家"), deep.resolve())
            self.assertEqual(registry.settings("海滨之家")["interval_seconds"], 5)
            self.assertIsNone(registry.resolve("不存在的项目"))

            payload = json.loads((root / "projects.json").read_text(encoding="utf-8"))
            payload["projects"]["另一个"] = {"path": str(deep)}
            (root / "projects.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(registry.names(), ["另一个", "海滨之家"])

            self.assertTrue(registry.unregister("另一个"))
            self.assertFalse(registry.unregister("另一个"))
            self.assertEqual(registry.names(), ["海滨之家"])

    def test_rejects_invalid_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "here").mkdir()
            registry = ProjectRegistry(root / "projects.json")
            with self.assertRaises(ProjectRegistryError):
                registry.register("相对路径", Path("here"))
            with self.assertRaises(ProjectRegistryError):
                registry.register("不存在", root / "missing")
            with self.assertRaises(ProjectRegistryError):
                registry.register("带/斜杠", root / "here")
            with self.assertRaises(ProjectRegistryError):
                registry.register("..", root / "here")

    def test_project_service_prefers_registry_over_input_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "projects"
            (input_root / "demo").mkdir(parents=True)
            outside = root / "elsewhere" / "人物图"
            outside.mkdir(parents=True)
            registry = ProjectRegistry(root / "projects.json")
            registry.register("人物图", outside, interval_seconds=7)
            service = ProjectService(input_root, registry=registry)

            self.assertEqual(service.resolve_project_path("人物图"), outside.resolve())
            self.assertEqual(service.resolve_project_path("demo"), (input_root / "demo").resolve())
            self.assertEqual(service.list_registered(), ("人物图",))
            self.assertEqual(service.resolve_options("人物图")["interval_seconds"], 7)
            self.assertEqual(service.resolve_options("demo"), {})
