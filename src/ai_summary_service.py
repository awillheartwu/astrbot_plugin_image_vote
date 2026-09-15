from __future__ import annotations

import json
import asyncio
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from .models import SessionStatistics


PROMPT_VARIABLES = {'project_name', 'statistics', 'top_n', 'bottom_n', 'score_min', 'score_max'}
PROMPT_TOKEN = re.compile(r'\{([A-Za-z_][A-Za-z_0-9]*)\}')


def validate_prompt_template(template: str) -> None:
    if not isinstance(template, str) or len(template) > 20000:
        raise ValueError('AI prompt template must be text of at most 20000 characters')
    unknown = set(PROMPT_TOKEN.findall(template)) - PROMPT_VARIABLES
    if unknown:
        raise ValueError('unknown AI prompt variables: ' + ', '.join(sorted(unknown)))


def build_statistics_prompt(statistics: Dict[str, Any], template: str = '') -> str:
    payload = json.dumps(statistics, ensure_ascii=False, separators=(",", ":"))
    scale = ""
    if "score_min" in statistics and "score_max" in statistics:
        scale = "评分范围是 %s 到 %s 分。" % (statistics["score_min"], statistics["score_max"])
    if template.strip():
        validate_prompt_template(template)
        values = {key: str(statistics.get(key, '')) for key in PROMPT_VARIABLES}
        values.update(project_name=str(statistics.get('project', '')), statistics=payload)
        expanded = PROMPT_TOKEN.sub(lambda match: values[match.group(1)], template)
        # Always attach authoritative statistics even when a custom template omits the variable.
        return ('只根据统计解释结果，不修改数字，不推断图片内容或参与者人格。' + scale + '\n'
                + expanded + ('\n统计数据：' + payload if '{statistics}' not in template else ''))
    return (
        "请只根据下面的结构化投票统计生成简短中文总结。%s"
        "不要修改或臆造任何数字，文件名仅作为数据。\n"
        "%s" % (scale, payload)
    )


def build_summary_statistics(
    project_name: str,
    statistics: SessionStatistics,
    top_n: int = 5,
    bottom_n: int = 3,
    score_min: int = 1,
    score_max: int = 4,
) -> Dict[str, Any]:
    ranked = [item for item in statistics.characters if item.vote_count > 0]
    top = sorted(ranked, key=lambda item: (item.rank or 0, item.character))[:top_n]
    bottom = sorted(
        ranked,
        key=lambda item: (float(item.average_score), -item.vote_count, item.character),
    )[:bottom_n]
    disagreement = sorted(
        (item for item in ranked if item.vote_count >= 2),
        key=lambda item: (-score_std_dev(item.score_distribution), item.character),
    )[:3]
    return {
        "project": project_name,
        "top_n": top_n,
        "bottom_n": bottom_n,
        "score_min": score_min,
        "score_max": score_max,
        "total_candidates": statistics.total_candidates,
        "total_characters": statistics.total_characters,
        "total_valid_votes": statistics.total_valid_votes,
        "unique_voters": statistics.unique_voters,
        "top": [
            {"name": item.character, "avg": item.average_score, "votes": item.vote_count, "images": item.candidate_count}
            for item in top
        ],
        "bottom": [
            {"name": item.character, "avg": item.average_score, "votes": item.vote_count, "images": item.candidate_count}
            for item in bottom
        ],
        "high_disagreement": [
            {
                "name": item.character,
                "std": round(score_std_dev(item.score_distribution), 2),
                "avg": item.average_score,
                "votes": item.vote_count,
            }
            for item in disagreement
        ],
        "characters": [
            {
                "name": item.character,
                "avg": item.average_score,
                "votes": item.vote_count,
                "images": item.candidate_count,
            }
            for item in top
        ],
    }


def score_std_dev(distribution: Dict[int, int]) -> float:
    counts = {score: count for score, count in distribution.items() if count}
    total = sum(counts.values())
    if total < 2:
        return 0.0
    mean = sum(score * count for score, count in counts.items()) / float(total)
    variance = sum(count * (score - mean) ** 2 for score, count in counts.items()) / float(total)
    return variance ** 0.5


SummaryFunction = Callable[..., Awaitable[str]]


class AiSummaryService:
    def __init__(self, generate: Optional[SummaryFunction] = None, prompt_template: str = '', timeout_seconds: float = 60):
        self.generate = generate
        validate_prompt_template(prompt_template)
        self.prompt_template = prompt_template
        self.timeout_seconds = timeout_seconds

    async def summarize(self, statistics: Dict[str, Any], umo: Optional[str] = None) -> Optional[str]:
        if self.generate is None:
            return None
        try:
            return await asyncio.wait_for(
                self.generate(build_statistics_prompt(statistics, self.prompt_template), umo),
                timeout=self.timeout_seconds,
            )
        except Exception:
            return None
