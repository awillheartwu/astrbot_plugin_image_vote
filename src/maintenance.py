"""Bounded maintenance of explicitly owned caches and abandoned temporary directories."""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from .logging_utils import get_logger

logger = get_logger()
STALE_TEMP_SECONDS = 86400
TEMP_MARKER = '.lirating-temp.json'
OWNER = 'astrbot_plugin_image_vote'


def owned_temporary_directory(base: Path, prefix: str):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=base)
    (Path(temporary.name) / TEMP_MARKER).write_text(json.dumps({'owner': OWNER, 'pid': os.getpid()}))
    return temporary


def prune_avatar_cache(cache_root: Path, retention_days: int) -> int:
    cache_root = Path(cache_root)
    if retention_days <= 0 or cache_root.is_symlink() or not cache_root.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    try:
        for entry in cache_root.iterdir():
            try:
                if re.fullmatch(r'[a-f0-9]{64}\.webp', entry.name) and not entry.is_symlink() and entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink(); removed += 1
            except OSError:
                continue
    except OSError as exc:
        logger.warning('头像缓存清理失败：%s', exc)
    return removed


def prune_stale_temp_dirs(bases, age_seconds: int = STALE_TEMP_SECONDS) -> int:
    cutoff = time.time() - max(60, age_seconds)
    removed = 0
    for base, prefixes in bases:
        base = Path(base)
        if base.is_symlink() or not base.is_dir():
            continue
        try:
            for entry in base.iterdir():
                try:
                    if entry.is_symlink() or not entry.is_dir() or not entry.name.startswith(prefixes):
                        continue
                    marker = entry / TEMP_MARKER
                    if marker.is_symlink() or entry.stat().st_mtime >= cutoff:
                        continue
                    data = json.loads(marker.read_text())
                    if data.get('owner') != OWNER or type(data.get('pid')) is not int or data['pid'] <= 0:
                        continue
                    try:
                        os.kill(data['pid'], 0)
                    except ProcessLookupError:
                        pass
                    except OSError:
                        continue  # Unknown/permission-denied owners are never removed.
                    else:
                        continue  # Includes another instance and long-running active jobs.
                    shutil.rmtree(entry); removed += 1
                except (OSError, ValueError, TypeError):
                    continue
        except OSError as exc:
            logger.warning('临时目录清理失败：%s', exc)
    return removed


def temp_scan_bases(output_root: Path, data_root: Path):
    return [(Path(output_root), ('.image-vote-',)),
            (Path(data_root) / 'temp', ('image-vote-download-',))]


def prune_thumbnail_cache(root: Path, retention_days: int, max_mb: int) -> int:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return 0
    entries = []
    removed = 0
    now = time.time()
    try:
        for path in root.iterdir():
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
                if re.fullmatch(r'[a-f0-9]{64}\.[a-f0-9]{32}\.tmp', path.name):
                    if stat.st_mtime < now - 86400:
                        path.unlink(); removed += 1
                elif re.fullmatch(r'[a-f0-9]{64}\.webp', path.name):
                    if stat.st_mtime < now - retention_days * 86400:
                        path.unlink(); removed += 1
                    else:
                        entries.append((stat.st_mtime, path, stat.st_size))
            except OSError:
                continue
        total = sum(size for _, _, size in entries)
        for _, path, size in sorted(entries):
            if total <= max_mb * 1024 * 1024:
                break
            try:
                path.unlink(); total -= size; removed += 1
            except OSError:
                continue
    except OSError as exc:
        logger.warning('缩略图缓存清理失败：%s', exc)
    return removed
