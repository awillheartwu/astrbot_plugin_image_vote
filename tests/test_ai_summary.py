import asyncio
import unittest

from src.ai_summary_service import AiSummaryService, build_statistics_prompt, build_summary_statistics
from src.models import CandidateStatistics, CharacterStatistics, SessionStatistics


class AiSummaryTest(unittest.TestCase):
    def test_payload_contains_statistics_only(self):
        statistics = SessionStatistics(
            total_candidates=2,
            total_valid_votes=3,
            unique_voters=2,
            average_votes_per_candidate=1.5,
            overall_average_score=3.0,
            candidates=(
                CandidateStatistics("c1", 1, "Top", 2, 4.0, {1: 0, 2: 0, 3: 0, 4: 2}, 1),
                CandidateStatistics("c2", 2, "Bottom", 1, 1.0, {1: 1, 2: 0, 3: 0, 4: 0}, 2),
            ),
            characters=(
                CharacterStatistics("Top", 1, 2, 4.0, {1: 0, 2: 0, 3: 0, 4: 2}, 1),
                CharacterStatistics("Bottom", 1, 1, 1.0, {1: 1, 2: 0, 3: 0, 4: 0}, 2),
            ),
            total_characters=2,
        )
        payload = build_summary_statistics("demo", statistics)
        self.assertEqual(payload["project"], "demo")
        self.assertEqual(payload["top"][0]["name"], "Top")
        self.assertEqual(payload["bottom"][0]["name"], "Bottom")
        self.assertNotIn("images", payload)
        self.assertIn("demo", build_statistics_prompt(payload))

    def test_ai_failure_returns_none(self):
        async def generate(prompt, umo=None):
            raise RuntimeError("provider unavailable")

        self.assertIsNone(asyncio.run(AiSummaryService(generate).summarize({"project": "demo"})))

    def test_disagreement_uses_vote_distribution(self):
        statistics = SessionStatistics(
            total_candidates=2,
            total_valid_votes=6,
            unique_voters=3,
            average_votes_per_candidate=3.0,
            overall_average_score=3.0,
            candidates=(
                CandidateStatistics("c1", 1, "Split", 3, 3.0, {1: 1, 2: 1, 3: 0, 4: 1}, 1),
                CandidateStatistics("c2", 2, "Agreed", 3, 3.0, {1: 0, 2: 0, 3: 3, 4: 0}, 2),
            ),
            characters=(
                CharacterStatistics("Split", 1, 3, 3.0, {1: 1, 2: 1, 3: 0, 4: 1}, 1),
                CharacterStatistics("Agreed", 1, 3, 3.0, {1: 0, 2: 0, 3: 3, 4: 0}, 2),
            ),
            total_characters=2,
        )
        payload = build_summary_statistics("demo", statistics)
        self.assertEqual(payload["high_disagreement"][0]["name"], "Split")
        self.assertGreater(payload["high_disagreement"][0]["std"], payload["high_disagreement"][1]["std"])

    def test_umo_is_forwarded_to_the_provider(self):
        seen = {}

        async def generate(prompt, umo=None):
            seen["umo"] = umo
            return "ok"

        result = asyncio.run(AiSummaryService(generate).summarize({"project": "demo"}, umo="aiocqhttp:GroupMessage:1"))
        self.assertEqual(result, "ok")
        self.assertEqual(seen["umo"], "aiocqhttp:GroupMessage:1")
