from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Mapping, Tuple
from .ai_summary_service import validate_prompt_template, DEFAULT_PROMPT_TEMPLATE


DEFAULT_CONFIG = {
    "input_root": "./data/projects",
    "output_root": "./data/reports",
    "recursive_scan": False,
    "web_browse_roots": [],
    "default_interval_seconds": 20,
    "final_grace_seconds": 20,
    "merge_character_images": False,
    "merge_character_images_max": 3,
    "send_timeout_seconds": 90,
    "score_min": 1,
    "score_max": 4,
    "same_user_vote_policy": "last_wins",
    "allow_quoted_vote_after_window": True,
    "ack_vote": False,
    "admin_only_start": True,
    "allowed_group_ids": [],
    "report_mode": "directory",
    "report_include_participants": True,
    "report_include_avatars": True,
    "report_image_format": "webp",
    "report_image_max_width": 1920,
    "report_image_max_height": 1920,
    "report_image_quality": 82,
    "thumbnail_width": 480,
    "thumbnail_quality": 72,
    "strip_metadata": True,
    "single_html_max_mb": 50,
    "ai_summary_enabled": True,
    "ai_provider_id": "",
    "ai_prompt_template": DEFAULT_PROMPT_TEMPLATE,
    "ai_top_n": 5,
    "ai_bottom_n": 3,
    "auto_resume_after_restart": False,
    "auto_cleanup_reports": False,
    "report_retention_days": 30,
    "max_send_retries": 3,
    "send_retry_base_seconds": 2,
    "send_failure_pause_threshold": 3,
    "notify_on_finish": True,
    "auto_report_on_finish": True,
    "send_report_html": False,
}


def _flatten_mapping(mapping: Mapping[str, Any]) -> Dict[str, Any]:
    """AstrBot 按 _conf_schema.json 的分组保存配置，这里同时兼容分组与扁平两种结构。"""
    flat: Dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            flat.update(_flatten_mapping(value))
        else:
            flat[key] = value
    return flat


@dataclass(frozen=True)
class VoteConfig:
    input_root: str
    output_root: str
    recursive_scan: bool = False
    web_browse_roots: Tuple[str, ...] = ()
    default_interval_seconds: int = 20
    final_grace_seconds: int = 20
    merge_character_images: bool = False
    merge_character_images_max: int = 3
    send_timeout_seconds: int = 90
    score_min: int = 1
    score_max: int = 4
    same_user_vote_policy: str = "last_wins"
    allow_quoted_vote_after_window: bool = True
    ack_vote: bool = False
    admin_only_start: bool = True
    allowed_group_ids: Tuple[str, ...] = ()
    report_mode: str = "directory"
    report_include_participants: bool = True
    report_include_avatars: bool = True
    report_image_format: str = "webp"
    report_image_max_width: int = 1920
    report_image_max_height: int = 1920
    report_image_quality: int = 82
    thumbnail_width: int = 480
    thumbnail_quality: int = 72
    strip_metadata: bool = True
    single_html_max_mb: int = 50
    ai_summary_enabled: bool = True
    ai_provider_id: str = ""
    ai_prompt_template: str = DEFAULT_PROMPT_TEMPLATE
    ai_top_n: int = 5
    ai_bottom_n: int = 3
    auto_resume_after_restart: bool = False
    auto_cleanup_reports: bool = False
    report_retention_days: int = 30
    max_send_retries: int = 3
    send_retry_base_seconds: int = 2
    send_failure_pause_threshold: int = 3
    notify_on_finish: bool = True
    auto_report_on_finish: bool = True
    send_report_html: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "VoteConfig":
        values: Dict[str, Any] = dict(DEFAULT_CONFIG)
        values.update(_flatten_mapping(mapping))
        field_names = {item.name for item in fields(cls)}
        values = {key: value for key, value in values.items() if key in field_names}
        values["allowed_group_ids"] = tuple(str(item) for item in values.get("allowed_group_ids", []))
        values["web_browse_roots"] = tuple(str(item) for item in values.get("web_browse_roots", []))
        if isinstance(values.get("ai_prompt_template"), str) and not values["ai_prompt_template"].strip():
            values["ai_prompt_template"] = DEFAULT_PROMPT_TEMPLATE
        config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        validate_prompt_template(self.ai_prompt_template)
        if self.score_min < 0 or self.score_max > 100 or self.score_min > self.score_max:
            raise ValueError("score_min/score_max must satisfy 0 <= min <= max <= 100")
        if self.default_interval_seconds <= 0:
            raise ValueError("default_interval_seconds must be positive")
        if self.final_grace_seconds < 0:
            raise ValueError("final_grace_seconds cannot be negative")
        if self.same_user_vote_policy not in {"last_wins", "first_wins", "max_score", "min_score"}:
            raise ValueError(
                "same_user_vote_policy must be one of last_wins / first_wins / max_score / min_score"
            )
        if self.report_mode not in {"directory", "single_html"}:
            raise ValueError("report_mode must be directory or single_html")
        if self.report_image_format.lower() not in {"webp", "jpeg", "jpg", "png"}:
            raise ValueError("unsupported report image format")
        for name in ("report_image_quality", "thumbnail_quality"):
            value = getattr(self, name)
            if not 1 <= value <= 100:
                raise ValueError("%s must be between 1 and 100" % name)
        for name in ("report_image_max_width", "report_image_max_height", "thumbnail_width"):
            if getattr(self, name) <= 0:
                raise ValueError("%s must be positive" % name)
        if self.single_html_max_mb <= 0:
            raise ValueError("single_html_max_mb must be positive")
        if self.ai_top_n < 0 or self.ai_bottom_n < 0:
            raise ValueError("ai_top_n/ai_bottom_n cannot be negative")
        if self.send_failure_pause_threshold < 0:
            raise ValueError("send_failure_pause_threshold cannot be negative")

    @property
    def effective_final_grace_seconds(self) -> int:
        return max(self.final_grace_seconds, self.default_interval_seconds, 20)
