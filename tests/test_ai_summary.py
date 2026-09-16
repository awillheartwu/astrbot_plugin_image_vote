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


class SummaryObservationTest(unittest.TestCase):
    def test_full_distribution_and_sample_evidence_not_only_top_n(self):
        from src.ai_summary_service import distribution_metrics
        stats = SessionStatistics(4, 4, 2, 1, 5, (), (
            CharacterStatistics('First', 2, 2, 5, {0: 1, 10: 1}, 1),
            CharacterStatistics('Second', 1, 1, 5, {5: 1}, 2),
            CharacterStatistics('Third', 1, 1, 5, {5: 1}, 3),
            CharacterStatistics('Unrated', 1, 0, None, {}, None),
        ), total_characters=4)
        payload = build_summary_statistics('demo', stats, top_n=1, score_min=0, score_max=10)
        self.assertEqual(len(payload['top']), 1)
        self.assertEqual(len(payload['characters']), 4)
        self.assertEqual(payload['overall']['median'], 5)
        self.assertEqual(payload['overall']['high_score_ratio'], .25)
        self.assertEqual(payload['overall']['maximum_score_count'], 1)
        self.assertEqual(payload['characters'][0]['std'], 5)
        self.assertEqual(payload['characters'][0]['coverage'], 1)
        self.assertIsNone(payload['characters'][1]['std'])
        self.assertIsNone(payload['characters'][3]['median'])
        self.assertTrue(payload['characters'][1]['low_sample'])
        self.assertEqual(distribution_metrics({0: 1, 4: 1})['median'], 2)
        self.assertEqual(distribution_metrics({1: 1, 3: 2})['median'], 3)

    def test_structured_and_legacy_summaries(self):
        import json
        from src.ai_summary_service import parse_summary, summary_text
        value = {'headline': '<高分>', 'insights': [{'title': '样本', 'text': '仅1票'}], 'closing': '谨慎参考'}
        raw = json.dumps(value, ensure_ascii=False)
        self.assertEqual(parse_summary('```json\n' + raw + '\n```'), value)
        self.assertEqual(summary_text(raw), '<高分>\n\n样本：仅1票\n\n谨慎参考')
        for raw in ['旧的纯文本总结', '{broken', '{"headline":"X","insights":[1]}']:
            self.assertIsNone(parse_summary(raw))
            self.assertEqual(summary_text(raw), raw)

    def test_prompt_guardrails_and_custom_template_compatibility(self):
        default = build_statistics_prompt({'project':'demo','score_min':1,'score_max':4})
        self.assertIn('数据解说员', default)
        self.assertIn('只有一位参与者', default)
        self.assertIn('JSON', default)
        custom = build_statistics_prompt({'project':'demo','score_min':1,'score_max':4}, '自定义：{project_name}')
        self.assertIn('自定义：demo', custom)
        self.assertIn('统计数据：', custom)
        self.assertNotIn('仅输出 JSON', custom)

    def test_no_votes_and_zero_only_scale(self):
        stats = SessionStatistics(0, 0, 0, 0, None, ())
        payload = build_summary_statistics('empty', stats, score_min=0, score_max=0)
        self.assertIsNone(payload['overall']['high_score_ratio'])
        self.assertIsNone(payload['overall']['median'])
