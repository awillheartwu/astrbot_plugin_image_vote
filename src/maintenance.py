"""插件自有产物清理：头像缓存与中断导出留下的临时目录。

插件写入磁盘的位置只有两处：AstrBot 数据目录下的 `plugin_data/<插件名>/`
（vote.db、projects.json、avatar_cache）与配置的报告输出目录（报告与 staging）。
这个模块负责把这两处里过期的、不再需要的文件清掉，避免长跑实例无限膨胀。
"""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Tuple

from .logging_utils import get_logger

logger = get_logger()

STALE_TEMP_SECONDS = 24 * 3600
TEMP_PREFIXES = ('.image-vote-', 'image-vote-download-')


def prune_avatar_cache(cache_root: Path, retention_days: int) -> int:
    """删除超过保留期的头像缓存文件（仅文件，不递归、不跟随符号链接）。"""
    cache_root = Path(cache_root)
    if retention_days <= 0 or not cache_root.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for entry in cache_root.iterdir():
        try:
            if entry.is_file() and not entry.is_symlink() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def prune_stale_temp_dirs(bases: Iterable[Tuple[Path, Tuple[str, ...]]], age_seconds: int = STALE_TEMP_SECONDS) -> int:
    """删除中断的导出/下载在报告目录与系统临时目录里留下的 staging 目录。"""
    cutoff = time.time() - max(60, age_seconds)
    removed = 0
    for base, prefixes in bases:
        base = Path(base)
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            if not entry.name.startswith(tuple(prefixes)):
                continue
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                shutil.rmtree(entry)
                removed += 1
                logger.info("清理残留临时目录：%s", entry)
            except OSError as exc:
                logger.warning("清理临时目录失败 %s：%s", entry, exc)
    return removed


def temp_scan_bases(output_root: Path) -> List[Tuple[Path, Tuple[str, ...]]]:
    """需要扫描的两处：报告根目录（导出 staging）与系统临时目录（下载打包）。"""
    return [(Path(output_root), ('.image-vote-',)), (Path(tempfile.gettempdir()), TEMP_PREFIXES)]
