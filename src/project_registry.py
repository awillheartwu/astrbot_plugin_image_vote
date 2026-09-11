from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logging_utils import get_logger

logger = get_logger()

REGISTRY_VERSION = 1
_INVALID_NAME_PARTS = {".", ".."}


class ProjectRegistryError(ValueError):
    """登记表内容不合法。"""


def _validate_name(project_name: str) -> str:
    name = (project_name or "").strip()
    if not name or name in _INVALID_NAME_PARTS:
        raise ProjectRegistryError("项目名不能为空")
    if any(separator in name for separator in ("/", "\\")):
        raise ProjectRegistryError("项目名不能包含路径分隔符：%s" % project_name)
    if len(name) > 64:
        raise ProjectRegistryError("项目名过长：%s" % project_name)
    return name


class ProjectRegistry:
    """项目名 → 任意目录的登记表，管理员维护，不依赖图形界面。

    文件位置由调用方给出（默认是插件数据目录下的 projects.json），
    每次读取按 (mtime, size) 判断是否需要重载，所以外部编辑后无需重载插件。
    """

    def __init__(self, path: Path):
        self.path = path.expanduser()
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._stamp: Optional[tuple] = None
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        try:
            stat = self.path.stat()
            stamp: Optional[tuple] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if not force and stamp == self._stamp:
            return
        self._stamp = stamp
        if stamp is None:
            self._entries = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("项目登记表无法解析：%s（%s）", self.path, exc)
            self._entries = {}
            return
        projects = payload.get("projects") if isinstance(payload, dict) else None
        if not isinstance(projects, dict):
            logger.error('项目登记表格式应为 {"projects": {...}}：%s', self.path)
            self._entries = {}
            return
        self._entries = {
            str(name): dict(value)
            for name, value in projects.items()
            if isinstance(name, str) and isinstance(value, dict)
        }

    def names(self) -> List[str]:
        self.reload()
        return sorted(self._entries)

    def entries(self) -> Dict[str, Dict[str, Any]]:
        self.reload()
        return {name: dict(value) for name, value in self._entries.items()}

    def resolve(self, project_name: str) -> Optional[Path]:
        self.reload()
        entry = self._entries.get(project_name)
        if entry is None:
            return None
        raw = entry.get("path")
        if not isinstance(raw, str) or not raw.strip():
            raise ProjectRegistryError("项目 %s 缺少 path" % project_name)
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute():
            raise ProjectRegistryError("项目 %s 的 path 必须是容器内绝对路径：%s" % (project_name, raw))
        path = path.resolve()
        if not path.is_dir():
            raise ProjectRegistryError("项目 %s 的目录不存在或不是目录：%s" % (project_name, path))
        return path

    def settings(self, project_name: str) -> Dict[str, Any]:
        """返回该项目的覆盖项：recursive / interval_seconds / description。"""
        self.reload()
        entry = self._entries.get(project_name) or {}
        settings: Dict[str, Any] = {}
        if isinstance(entry.get("recursive"), bool):
            settings["recursive"] = entry["recursive"]
        interval = entry.get("interval_seconds")
        if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
            settings["interval_seconds"] = interval
        description = entry.get("description")
        if isinstance(description, str) and description.strip():
            settings["description"] = description.strip()
        return settings

    def register(self, project_name: str, path: Path, interval_seconds: Optional[int] = None,
                 recursive: Optional[bool] = None, description: Optional[str] = None) -> None:
        name = _validate_name(project_name)
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise ProjectRegistryError("path 必须是容器内绝对路径：%s" % path)
        candidate = candidate.resolve()
        if not candidate.is_dir():
            raise ProjectRegistryError("目录不存在或不是目录：%s" % candidate)
        entry: Dict[str, Any] = {"path": str(candidate)}
        if interval_seconds:
            entry["interval_seconds"] = int(interval_seconds)
        if recursive is not None:
            entry["recursive"] = bool(recursive)
        if description:
            entry["description"] = str(description)
        projects = self.entries()
        projects[name] = entry
        self._write(projects)
        logger.info("登记项目 %s → %s", name, candidate)

    def unregister(self, project_name: str) -> bool:
        name = _validate_name(project_name)
        projects = self.entries()
        if name not in projects:
            return False
        projects.pop(name)
        self._write(projects)
        logger.info("取消登记项目 %s", name)
        return True

    def _write(self, projects: Dict[str, Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": REGISTRY_VERSION, "projects": projects}
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(temp), str(self.path))
        self._stamp = None
        self.reload(force=True)

