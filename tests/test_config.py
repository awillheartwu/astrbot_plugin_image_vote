import json
import unittest
from dataclasses import fields
from pathlib import Path

from src.config import VoteConfig


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "_conf_schema.json"


class ConfigMappingTest(unittest.TestCase):
    def test_grouped_astrbot_config_is_flattened(self):
        config = VoteConfig.from_mapping(
            {
                "paths": {"input_root": "/vote/projects", "output_root": "/AstrBot/data/vote-reports"},
                "voting": {"default_interval_seconds": 5, "score_max": 5},
                "permissions": {"allowed_group_ids": [123, "456"]},
                "report": {"report_mode": "single_html"},
                "ai": {"ai_summary_enabled": False},
            }
        )
        self.assertEqual(config.input_root, "/vote/projects")
        self.assertEqual(config.output_root, "/AstrBot/data/vote-reports")
        self.assertEqual(config.default_interval_seconds, 5)
        self.assertEqual(config.score_max, 5)
        self.assertEqual(config.allowed_group_ids, ("123", "456"))
        self.assertEqual(config.report_mode, "single_html")
        self.assertFalse(config.ai_summary_enabled)

    def test_flat_mapping_still_works(self):
        config = VoteConfig.from_mapping({"input_root": "/a", "output_root": "/b", "score_min": 2})
        self.assertEqual(config.input_root, "/a")
        self.assertEqual(config.score_min, 2)
        self.assertEqual(config.score_max, 4)

    def test_schema_covers_exactly_the_config_fields(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        keys = set()
        for group in schema.values():
            keys.update(group["items"].keys())
        self.assertEqual(keys, {item.name for item in fields(VoteConfig)})

    def test_score_range_validation(self):
        ten = VoteConfig.from_mapping({"input_root": "/a", "output_root": "/b", "score_max": 10})
        self.assertEqual((ten.score_min, ten.score_max), (1, 10))
        with self.assertRaises(ValueError):
            VoteConfig.from_mapping({"input_root": "/a", "output_root": "/b", "score_max": 101})
        with self.assertRaises(ValueError):
            VoteConfig.from_mapping({"input_root": "/a", "output_root": "/b", "score_min": 5, "score_max": 4})
