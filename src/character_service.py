"""Canonical character identity shared by sending, voting, and reports."""
from __future__ import annotations

from .models import Candidate
from .project_scanner import derive_character


def character_of(candidate: Candidate) -> str:
    return candidate.character or derive_character(candidate.display_title) or candidate.display_title
