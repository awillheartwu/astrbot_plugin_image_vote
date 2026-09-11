import unittest

from src.models import Candidate, Session, Vote, VoteSource
from src.statistics_service import calculate_statistics


class StatisticsTest(unittest.TestCase):
    def test_zero_vote_candidates_are_unranked(self):
        candidates = [
            Candidate("c1", "s1", 1, "1.png", "1.png", "One", None, 1),
            Candidate("c2", "s1", 2, "2.png", "2.png", "Two", None, 1),
        ]
        votes = [Vote(None, "s1", "c1", "u1", "Alice", 4, VoteSource.CURRENT_WINDOW)]
        result = calculate_statistics(candidates, votes)
        self.assertEqual(result.candidates[0].rank, 1)
        self.assertIsNone(result.candidates[1].rank)
        self.assertEqual(result.unique_voters, 1)
        self.assertEqual(result.overall_average_score, 4.0)

