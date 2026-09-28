"""Canonical character identity shared by sending, voting, and reports."""
from __future__ import annotations

import random
from dataclasses import replace
from typing import List, Sequence, Tuple

from .models import Candidate
from .project_scanner import derive_character


def character_of(candidate: Candidate) -> str:
    return candidate.character or derive_character(candidate.display_title) or candidate.display_title


def select_character_images(
    candidates: Sequence[Candidate], maximum: int, random_select: bool = False,
) -> Tuple[Candidate, ...]:
    """创建会话时抽选一次；保留人物与图的相对顺序，不修改扫描缓存。"""
    groups = {}
    for candidate in candidates:
        groups.setdefault(character_of(candidate), []).append(candidate)
    selected = []
    for group in groups.values():
        if maximum > 0 and len(group) > maximum:
            indexes = sorted(random.sample(range(len(group)), maximum)) if random_select else range(maximum)
            group = [group[index] for index in indexes]
        selected.extend(group)
    return tuple(replace(candidate, display_index=index) for index, candidate in enumerate(selected, 1))


def image_selection_label(maximum: int, random_select: bool) -> str:
    if maximum == 0:
        return "每个人物图片不限"
    return "每个人物最多 %d 张，%s；开始投票时确定，预览为原图库" % (
        maximum, "不重复随机抽选" if random_select else "按原排序取前 N 张",
    )


def character_layout(candidates: Sequence[Candidate]) -> List[Tuple[int, int, int]]:
    """每张图片的位置：(第几位人物, 该人物第几张, 该人物共几张)。

    人物按首次出现顺序编号，与预检、报告和群消息里的「第 N 位人物」一致。
    """
    totals = {}
    for item in candidates:
        character = character_of(item)
        totals[character] = totals.get(character, 0) + 1
    ordinals = {}
    seen = {}
    layout: List[Tuple[int, int, int]] = []
    for item in candidates:
        character = character_of(item)
        if character not in ordinals:
            ordinals[character] = len(ordinals) + 1
        seen[character] = seen.get(character, 0) + 1
        layout.append((ordinals[character], seen[character], totals[character]))
    return layout
