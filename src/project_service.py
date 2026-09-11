from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Sequence

from .path_guard import PathGuard
from .project_scanner import scan_project


class ProjectService:
    def __init__(self, input_root: Path, aliases: Mapping[str, str] = None):
        self.input_root = input_root.expanduser().resolve()
        self.guard = PathGuard(self.input_root)
        self.aliases = dict(aliases or self._load_aliases())

    def _load_aliases(self) -> Dict[str, str]:
        alias_path = self.input_root / "project_alias.json"
        if not alias_path.is_file() or alias_path.is_symlink():
            return {}
        try:
            payload = json.loads(alias_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)}

    def resolve_project_path(self, project_name: str) -> Path:
        resolved_name = self.aliases.get(project_name, project_name)
        path = self.guard.resolve_child(resolved_name)
        if not path.is_dir():
            raise FileNotFoundError("project directory does not exist: %s" % resolved_name)
        return path

    def list_projects(self) -> Sequence[str]:
        if not self.input_root.is_dir():
            return ()
        projects = []
        for item in self.input_root.iterdir():
            if not item.is_dir() or item.is_symlink() or item.name.startswith("."):
                continue
            try:
                self.guard.ensure_within(item, allow_root=False)
            except Exception:
                continue
            projects.append(item.name)
        return tuple(sorted(projects))

    def inspect(self, project_name: str, recursive: bool = False):
        return scan_project(self.resolve_project_path(project_name), recursive=recursive)
