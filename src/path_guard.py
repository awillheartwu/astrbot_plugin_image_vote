from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .logging_utils import get_logger


logger = get_logger()


class UnsafePathError(ValueError):
    """Raised when a user-controlled path escapes its configured root."""


class PathGuard:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def ensure_within(self, path: Path, allow_root: bool = True) -> Path:
        resolved = path.expanduser().resolve()
        try:
            common = Path(os.path.commonpath([str(self.root), str(resolved)]))
        except ValueError as exc:
            raise UnsafePathError("path is on a different filesystem root") from exc
        if common != self.root or (not allow_root and resolved == self.root):
            logger.error("路径安全检查失败：%s 不在 %s 内", resolved, self.root)
            raise UnsafePathError("path is outside the configured root")
        return resolved

    def resolve_child(self, user_value: str, allow_root: bool = False) -> Path:
        if not user_value or "\x00" in user_value:
            raise UnsafePathError("path is empty or contains a NUL byte")
        candidate = Path(user_value)
        if candidate.is_absolute():
            raise UnsafePathError("absolute paths are not accepted")
        if any(part == ".." for part in candidate.parts):
            raise UnsafePathError("parent traversal is not accepted")
        return self.ensure_within(self.root / candidate, allow_root=allow_root)

    def ensure_report_directory(self, report_path: Path, marker_name: str, plugin_name: str) -> Path:
        resolved = self.ensure_within(report_path, allow_root=False)
        marker = resolved / marker_name
        if report_path.is_symlink() or marker.is_symlink():
            logger.error("报告路径是符号链接，已拒绝：%s", report_path)
            raise UnsafePathError("symlink report paths are not accepted")
        if not marker.is_file():
            logger.error("报告目录缺少 marker，已拒绝：%s", report_path)
            raise UnsafePathError("report marker is missing")
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UnsafePathError("report marker is invalid") from exc
        if payload.get("plugin") != plugin_name:
            logger.error("报告 marker 属于其他插件，已拒绝：%s", report_path)
            raise UnsafePathError("report marker belongs to another plugin")
        return resolved

    @staticmethod
    def write_report_marker(
        report_path: Path,
        marker_name: str,
        plugin_name: str,
        session_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        report_path.mkdir(parents=True, exist_ok=True)
        marker = report_path / marker_name
        payload: Dict[str, Any] = {"plugin": plugin_name, "session_id": session_id}
        if extra:
            payload.update(extra)
        marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def cleanup_report(self, report_path: Path, marker_name: str, plugin_name: str) -> None:
        validated = self.ensure_report_directory(report_path, marker_name, plugin_name)
        if validated == self.root:
            raise UnsafePathError("output root itself cannot be deleted")
        shutil.rmtree(str(validated))
