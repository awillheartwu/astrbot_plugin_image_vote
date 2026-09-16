import asyncio
import unittest

from src.ai_summary_service import AiSummaryService, build_statistics_prompt, validate_prompt_template


class PromptTemplateTest(unittest.TestCase):
    def test_template_always_preserves_statistics_and_replaces_only_known_variables(self):
        data={'project':'{statistics}','total_valid_votes':12,'score_min':1,'score_max':10,'top_n':3,'bottom_n':2}
        prompt=build_statistics_prompt(data,'项目 {project_name}，高分项 {top_n}')
        self.assertIn('项目 {statistics}',prompt)
        self.assertIn('"total_valid_votes":12',prompt)
        self.assertIn('高分项 3',prompt)
        with self.assertRaises(ValueError):
            validate_prompt_template('{unknown}')

    def test_timeout_falls_back_without_hanging_report_generation(self):
        async def run():
            async def generate(*args):
                await asyncio.Event().wait()
            service=AiSummaryService(generate,timeout_seconds=.01)
            self.assertIsNone(await service.summarize({'project':'fixture'}))
        asyncio.run(run())

    def test_visible_default_matches_generation_and_preserves_custom_template(self):
        import json
        from pathlib import Path
        from src.ai_summary_service import DEFAULT_PROMPT_TEMPLATE
        from src.config import VoteConfig
        schema = json.loads((Path(__file__).resolve().parents[1] / '_conf_schema.json').read_text())
        self.assertEqual(schema['ai']['items']['ai_prompt_template']['default'], DEFAULT_PROMPT_TEMPLATE)
        settings = VoteConfig.from_mapping({'ai_prompt_template':'  '})
        self.assertEqual(settings.ai_prompt_template, DEFAULT_PROMPT_TEMPLATE)
        self.assertEqual(VoteConfig.from_mapping({'ai_prompt_template':'我的 {statistics}'}).ai_prompt_template, '我的 {statistics}')
        data = {'project':'demo', 'score_min':0, 'score_max':10}
        self.assertEqual(build_statistics_prompt(data), build_statistics_prompt(data, settings.ai_prompt_template))
        self.assertNotIn('{statistics}', build_statistics_prompt(data))
        self.assertNotIn('interval_includes_send_time', schema['voting']['items'])
        self.assertFalse(hasattr(settings, 'interval_includes_send_time'))
