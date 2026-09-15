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
        self.assertIsNone(result.candidates[0].rank)
        self.assertIsNone(result.candidates[1].rank)
        self.assertEqual(result.characters[0].rank, 1)
        self.assertEqual(result.unique_voters, 1)
        self.assertEqual(result.overall_average_score, 4.0)

    def test_characters_are_aggregated_across_images(self):
        candidates = [
            Candidate("c1", "s1", 1, "1.png", "1.png", "Aurora-现代版本", None, 1, character="Aurora"),
            Candidate("c2", "s1", 2, "2.png", "2.png", "Aurora-老年版本", None, 1, character="Aurora"),
            Candidate("c3", "s1", 3, "3.png", "3.png", "Cass", None, 1, character="Cass"),
        ]
        votes = [
            Vote(None, "s1", "c1", "u1", "n", 4, VoteSource.CURRENT_WINDOW),
            Vote(None, "s1", "c2", "u2", "n", 2, VoteSource.CURRENT_WINDOW),
            Vote(None, "s1", "c3", "u2", "n", 3, VoteSource.CURRENT_WINDOW),
        ]
        result = calculate_statistics(candidates, votes)
        by_character = {item.character: item for item in result.characters}
        self.assertEqual(by_character["Aurora"].candidate_count, 2)
        self.assertEqual(by_character["Aurora"].vote_count, 2)
        self.assertEqual(by_character["Aurora"].average_score, 3.0)
        self.assertEqual(by_character["Aurora"].rank, 1)
        self.assertEqual(by_character["Cass"].rank, 2)
