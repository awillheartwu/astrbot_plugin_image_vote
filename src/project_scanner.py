from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Candidate, ProjectSnapshot


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEMP_SUFFIXES = ("~", ".tmp", ".part", ".crdownload")
IGNORED_NAMES = {"project.json", "manifest.json"}
SCREENSHOT_RE = re.compile(
    r"^screenshot(?P<seq>\d+)\s*-\s*(?P<title>.+?)\s*-\s*(?P<suffix>[0-9A-Za-z]+)\.(?P<ext>png|jpg|jpeg|webp|gif)$",
    re.IGNORECASE,
)
NATURAL_PART_RE = re.compile(r"(\d+)")
# 采集流水线会给重跑/回退的图追加标记，如「- 30279726 - reset」；展示标题应剥掉这些段
_TITLE_SUFFIX_RE = re.compile(r"\s*-\s*(?:reset(?:[-_ ]?\d+)?|[0-9a-f]{6,}|\d{4,})\s*$", re.IGNORECASE)


def natural_key(value: str) -> Tuple[object, ...]:
    parts: List[object] = []
    for part in NATURAL_PART_RE.split(value.casefold()):
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def parse_image_filename(filename: str) -> Optional[Tuple[str, Optional[int]]]:
    match = SCREENSHOT_RE.match(filename)
    if match:
        return clean_display_title(match.group("title")), int(match.group("seq"))
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return None
    return Path(filename).stem, None


def clean_display_title(title: str) -> str:
    """剥掉标题尾部的流水线标记（哈希、reset、重试序号），只在还剩内容时才剥。"""
    value = (title or "").strip()
    while True:
        stripped = _TITLE_SUFFIX_RE.sub("", value).strip()
        if stripped == value or not stripped:
            return value
        value = stripped


def _is_ignored(path: Path) -> bool:
    name = path.name
    return name.startswith(".") or name in IGNORED_NAMES or name.endswith(TEMP_SUFFIXES)


def _candidate_id(relative_path: str, size: int, mtime_ns: int) -> str:
    raw = "%s\0%s\0%s" % (relative_path, size, mtime_ns)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _read_manifest(project_path: Path) -> Dict[str, object]:
    manifest_path = project_path / "project.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _manifest_files(manifest: Dict[str, object]) -> Tuple[str, ...]:
    files = manifest.get("files")
    if not isinstance(files, list):
        return ()
    return tuple(item for item in files if isinstance(item, str))


def _manifest_characters(manifest: Dict[str, object]) -> Dict[str, str]:
    """manifest 里的 角色名 → 文件名列表，反转成 文件名 → 角色名。"""
    mapping = manifest.get("characters")
    if not isinstance(mapping, dict):
        return {}
    by_filename: Dict[str, str] = {}
    for character, files in mapping.items():
        if not isinstance(character, str) or not isinstance(files, list):
            continue
        name = character.strip() or character
        for item in files:
            if isinstance(item, str):
                by_filename[item] = name
    return by_filename


def derive_character(display_title: str) -> str:
    """默认取展示标题里第一个短横线之前的部分作为角色名，贴合常见命名习惯。"""
    head = (display_title or "").split("-")[0].strip()
    return head or (display_title or "").strip()


def scan_project(project_path: Path, recursive: bool = False, session_id: str = "snapshot") -> ProjectSnapshot:
    project_path = project_path.expanduser().resolve()
    if not project_path.is_dir():
        raise FileNotFoundError("project directory does not exist: %s" % project_path)

    iterator: Iterable[Path] = project_path.rglob("*") if recursive else project_path.iterdir()
    entries = [
        item
        for item in iterator
        if item.is_file() and not item.is_symlink() and not _is_ignored(item) and item.suffix.lower() in IMAGE_EXTENSIONS
    ]
    invalid_files = sorted(
        str(item.relative_to(project_path)).replace("\\", "/")
        for item in (project_path.rglob("*") if recursive else project_path.iterdir())
        if item.is_file() and not item.is_symlink() and not _is_ignored(item) and item.suffix.lower() not in IMAGE_EXTENSIONS
    )

    parsed = []
    for path in entries:
        info = parse_image_filename(path.name)
        if info is None:
            continue
        title, sequence = info
        relative = str(path.relative_to(project_path)).replace("\\", "/")
        stat = path.stat()
        parsed.append((path, relative, title, sequence, stat.st_size, stat.st_mtime_ns))

    manifest = _read_manifest(project_path)
    manifest_files = _manifest_files(manifest)
    character_overrides = _manifest_characters(manifest)
    manifest_order = {str(Path(item)).replace("\\", "/"): index for index, item in enumerate(manifest_files)}
    if manifest_order:
        parsed.sort(key=lambda item: (manifest_order.get(item[1], len(manifest_order)), natural_key(item[1])))
        sort_mode = "manifest"
    else:
        has_sequence = any(item[3] is not None for item in parsed)
        has_plain = any(item[3] is None for item in parsed)
        if has_sequence and has_plain:
            parsed.sort(key=lambda item: (0, item[3], natural_key(item[1])) if item[3] is not None else (1, 0, natural_key(item[1])))
            sort_mode = "mixed"
        elif has_sequence:
            parsed.sort(key=lambda item: (item[3], natural_key(item[1])))
            sort_mode = "sequence"
        else:
            parsed.sort(key=lambda item: natural_key(item[1]))
            sort_mode = "natural"

    warnings: List[str] = []
    if sort_mode == "mixed":
        warnings.append("project contains both numbered screenshot names and plain image names")

    candidates = []
    for display_index, item in enumerate(parsed, start=1):
        path, relative, title, sequence, size, mtime_ns = item
        candidates.append(
            Candidate(
                id=_candidate_id(relative, size, mtime_ns),
                session_id=session_id,
                display_index=display_index,
                source_relative_path=relative,
                source_filename=path.name,
                display_title=title,
                sequence_number=sequence,
                source_size=size,
                character=character_overrides.get(path.name) or derive_character(title),
            )
        )

    # 投票以人物为单位：人物按首次出现的位置排序，人物内部保留原扫描顺序。
    character_order: List[str] = []
    by_character: Dict[str, List[Candidate]] = {}
    for candidate in candidates:
        name = candidate.character or candidate.display_title
        if name not in by_character:
            by_character[name] = []
            character_order.append(name)
        by_character[name].append(candidate)
    candidates = [candidate for name in character_order for candidate in by_character[name]]
    for display_index, candidate in enumerate(candidates, start=1):
        candidate.display_index = display_index

    return ProjectSnapshot(
        project_name=project_path.name,
        project_path=str(project_path),
        candidates=tuple(candidates),
        invalid_files=tuple(invalid_files),
        warnings=tuple(warnings),
        sort_mode=sort_mode,
        total_size=sum(item.source_size for item in candidates),
    )
