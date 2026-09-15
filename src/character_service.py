"""Canonical character identity shared by sending, voting, and reports."""
from __future__ import annotations

from typing import List, Sequence, Tuple

from .models import Candidate
from .project_scanner import derive_character


def character_of(candidate: Candidate) -> str:
    return candidate.character or derive_character(candidate.display_title) or candidate.display_title


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
