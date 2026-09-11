from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from .models import Candidate, CandidateStatistics, SessionStatistics, Vote


def calculate_statistics(
    candidates: Iterable[Candidate], votes: Iterable[Vote], score_min: int = 1, score_max: int = 4
) -> SessionStatistics:
    candidates_list = list(candidates)
    votes_list = list(votes)
    by_candidate: Dict[str, List[Vote]] = defaultdict(list)
    for vote in votes_list:
        by_candidate[vote.candidate_id].append(vote)

    preliminary = []
    for candidate in candidates_list:
        candidate_votes = by_candidate.get(candidate.id, [])
        distribution = {score: 0 for score in range(score_min, score_max + 1)}
        for vote in candidate_votes:
            distribution[vote.score] = distribution.get(vote.score, 0) + 1
        average = None
        if candidate_votes:
            average = sum(vote.score for vote in candidate_votes) / float(len(candidate_votes))
        preliminary.append(
            CandidateStatistics(
                candidate_id=candidate.id,
                display_index=candidate.display_index,
                display_title=candidate.display_title,
                vote_count=len(candidate_votes),
                average_score=average,
                score_distribution=distribution,
            )
        )

    ranked = sorted(
        (item for item in preliminary if item.vote_count > 0),
        key=lambda item: (-float(item.average_score), -item.vote_count, item.display_index),
    )
    rank_by_id = {item.candidate_id: index for index, item in enumerate(ranked, start=1)}
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
    )
