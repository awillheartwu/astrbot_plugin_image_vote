from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from .models import Candidate, CandidateStatistics, CharacterStatistics, SessionStatistics, Vote
from .character_service import character_of


def _distribution(votes: Iterable[Vote], score_min: int, score_max: int) -> Dict[int, int]:
    distribution = {score: 0 for score in range(score_min, score_max + 1)}
    for vote in votes:
        distribution[vote.score] = distribution.get(vote.score, 0) + 1
    return distribution


def _average(votes: List[Vote]):
    if not votes:
        return None
    return sum(vote.score for vote in votes) / float(len(votes))


def calculate_statistics(
    candidates: Iterable[Candidate], votes: Iterable[Vote], score_min: int = 1, score_max: int = 4
) -> SessionStatistics:
    candidates_list = list(candidates)
    votes_list = list(votes)
    candidate_by_id = {candidate.id: candidate for candidate in candidates_list}

    preliminary = []
    images_per_character: Dict[str, int] = defaultdict(int)
    votes_per_character: Dict[str, List[Vote]] = defaultdict(list)
    for candidate in candidates_list:
        character = character_of(candidate)
        images_per_character[character] += 1
        preliminary.append(
            CandidateStatistics(
                candidate_id=candidate.id,
                display_index=candidate.display_index,
                display_title=candidate.display_title,
                vote_count=0,
                average_score=None,
                score_distribution=_distribution((), score_min, score_max),
            )
        )
    for vote in votes_list:
        candidate = candidate_by_id.get(vote.candidate_id)
        character = vote.character or (character_of(candidate) if candidate is not None else "")
        if character in images_per_character:
            votes_per_character[character].append(vote)

    rank_by_id = {}
    finalized = tuple(
        CandidateStatistics(
            candidate_id=item.candidate_id,
            display_index=item.display_index,
            display_title=item.display_title,
            vote_count=item.vote_count,
            average_score=item.average_score,
            score_distribution=item.score_distribution,
            rank=rank_by_id.get(item.candidate_id),
        )
        for item in preliminary
    )

    character_items = [
        CharacterStatistics(
            character=name,
            candidate_count=images_per_character[name],
            vote_count=len(items),
            average_score=_average(items),
            score_distribution=_distribution(items, score_min, score_max),
        )
        for name in images_per_character
        for items in (votes_per_character.get(name, []),)
    ]
    ranked_characters = sorted(
        (item for item in character_items if item.vote_count > 0),
        key=lambda item: (-float(item.average_score), -item.vote_count, item.character),
    )
    rank_by_character = {item.character: index for index, item in enumerate(ranked_characters, start=1)}
    first_appearance = {name: index for index, name in enumerate(images_per_character)}
    characters = tuple(
        CharacterStatistics(
            character=item.character,
            candidate_count=item.candidate_count,
            vote_count=item.vote_count,
            average_score=item.average_score,
            score_distribution=item.score_distribution,
            rank=rank_by_character.get(item.character),
        )
        for item in sorted(
            character_items,
            key=lambda entry: (
                rank_by_character.get(entry.character) is None,
                rank_by_character.get(entry.character) or 0,
                first_appearance[entry.character],
            ),
        )
    )

    overall_average = None
    if votes_list:
        overall_average = sum(vote.score for vote in votes_list) / float(len(votes_list))
    return SessionStatistics(
        total_candidates=len(candidates_list),
        total_valid_votes=len(votes_list),
        unique_voters=len({vote.voter_id for vote in votes_list}),
        average_votes_per_candidate=(len(votes_list) / float(len(candidates_list))) if candidates_list else 0.0,
        overall_average_score=overall_average,
        candidates=finalized,
        characters=characters,
        total_characters=len(images_per_character),
        average_votes_per_character=(len(votes_list) / float(len(images_per_character))) if images_per_character else 0.0,
    )
