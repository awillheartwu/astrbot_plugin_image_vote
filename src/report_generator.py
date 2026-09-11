from __future__ import annotations

import asyncio
import base64
import html
import json
import mimetypes
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol

from .logging_utils import get_logger
from .models import Candidate, Session, SessionStatistics
from .path_guard import PathGuard, UnsafePathError


REPORT_MARKER = ".astrbot_image_vote_report"
PLUGIN_NAME = "astrbot_plugin_image_vote"
logger = get_logger()


class ImageProcessor(Protocol):
    def process(self, source_path: Path, main_path: Path, thumbnail_path: Path):
        """Create report-only derivatives without modifying source_path."""


class ReportGenerationError(RuntimeError):
    pass


class DirectoryReportGenerator:
    def __init__(self, asset_root: Optional[Path] = None, image_extension: str = "webp"):
        self.asset_root = asset_root or Path(__file__).resolve().parent.parent / "assets"
        self.image_extension = image_extension.lstrip(".").lower()

    async def generate(
        self,
        session: Session,
        candidates: Iterable[Candidate],
        statistics: SessionStatistics,
        source_root: Path,
        output_root: Path,
        image_processor: ImageProcessor,
        ai_summary: Optional[str] = None,
    ) -> Path:
        source_guard = PathGuard(source_root)
        output_guard = PathGuard(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        project_slug = self._slug(session.project_name)
        report_name = "%s-%s" % (session.short_id, session.id[:8])
        report_dir = output_guard.ensure_within(output_root / project_slug / report_name, allow_root=False)
        report_dir.mkdir(parents=True, exist_ok=True)
        images_dir = report_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        self._copy_assets(report_dir)

        candidate_list = list(candidates)
        stats_by_id = {item.candidate_id: item for item in statistics.candidates}
        rows: List[Dict[str, object]] = []
        for candidate in candidate_list:
            source_path = source_guard.ensure_within(source_root / candidate.source_relative_path, allow_root=False)
            stem = "%04d" % candidate.display_index
            main_path = images_dir / (stem + "." + self.image_extension)
            thumb_path = images_dir / (stem + "_thumb." + self.image_extension)
            try:
                await asyncio.to_thread(image_processor.process, source_path, main_path, thumb_path)
            except Exception as exc:
                raise ReportGenerationError("failed to process %s: %s" % (candidate.source_filename, exc)) from exc
            item = stats_by_id[candidate.id]
            rows.append(
                {
                    "candidate_id": candidate.id,
                    "display_index": candidate.display_index,
                    "display_title": candidate.display_title,
                    "source_filename": candidate.source_filename,
                    "main_image": "images/%s" % main_path.name,
                    "thumbnail": "images/%s" % thumb_path.name,
                    "vote_count": item.vote_count,
                    "average_score": item.average_score,
                    "score_distribution": item.score_distribution,
                    "rank": item.rank,
                    "send_status": candidate.send_status.value,
                }
            )

        payload = {
            "session": {
                "id": session.id,
                "short_id": session.short_id,
                "group_id": session.group_id,
                "project_name": session.project_name,
                "candidate_count": session.candidate_count,
                "status": session.status.value,
                "started_at": session.started_at,
                "finished_at": session.finished_at,
            },
            "statistics": {
                "total_candidates": statistics.total_candidates,
                "total_valid_votes": statistics.total_valid_votes,
                "unique_voters": statistics.unique_voters,
                "average_votes_per_candidate": statistics.average_votes_per_candidate,
                "overall_average_score": statistics.overall_average_score,
            },
            "candidates": rows,
            "ai_summary": ai_summary,
        }
        rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0, row["display_index"]))
        payload["candidates"] = rows
        (report_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_dir / "index.html").write_text(self._render_html(payload), encoding="utf-8")
        PathGuard.write_report_marker(
            report_dir,
            REPORT_MARKER,
            PLUGIN_NAME,
            session.id,
            extra={
                "short_id": session.short_id,
                "project_name": session.project_name,
                "created_at": session.created_at,
            },
        )
        return report_dir

    async def generate_single_html(
        self,
        session: Session,
        candidates: Iterable[Candidate],
        statistics: SessionStatistics,
        source_root: Path,
        output_root: Path,
        image_processor: ImageProcessor,
        max_mb: int,
        ai_summary: Optional[str] = None,
    ) -> Path:
        report_dir = await self.generate(
            session,
            candidates,
            statistics,
            source_root,
            output_root,
            image_processor,
            ai_summary=ai_summary,
        )
        data_path = report_dir / "data.json"
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        inline_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        for row in inline_payload["candidates"]:
            row["main_image"] = self._data_uri(report_dir / row["main_image"])
            row["thumbnail"] = self._data_uri(report_dir / row["thumbnail"])
        standalone_html = self._render_inline_html(inline_payload)
        if len(standalone_html.encode("utf-8")) > max_mb * 1024 * 1024:
            payload["report_mode"] = "directory"
            payload["fallback_reason"] = "single_html_max_mb exceeded"
            data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.warning("单文件报告超过 %d MB 限制，已自动回退目录模式：%s", max_mb, report_dir)
            return report_dir
        payload["report_mode"] = "single_html"
        data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_dir / "index.html").write_text(standalone_html, encoding="utf-8")
        return report_dir

    @staticmethod
    def _data_uri(path: Path) -> str:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return "data:%s;base64,%s" % (media_type, encoded)

    def _render_inline_html(self, payload: Dict[str, object]) -> str:
        rendered = self._render_html(payload)
        css = (self.asset_root / "report.css").read_text(encoding="utf-8") if (self.asset_root / "report.css").is_file() else ""
        javascript = (self.asset_root / "report.js").read_text(encoding="utf-8") if (self.asset_root / "report.js").is_file() else ""
        rendered = rendered.replace('<link rel="stylesheet" href="./report.css">', "<style>%s</style>" % css)
        rendered = rendered.replace('<script src="./report.js"></script>', "<script>%s</script>" % javascript)
        return rendered

    def _copy_assets(self, report_dir: Path) -> None:
        for name in ("report.css", "report.js"):
            source = self.asset_root / name
            if source.is_file():
                shutil.copyfile(str(source), str(report_dir / name))

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^0-9A-Za-z一-龥_-]+", "-", value).strip("-")
        return slug or "project"

    @staticmethod
    def project_slug(value: str) -> str:
        return DirectoryReportGenerator._slug(value)

    @staticmethod
    def _render_html(payload: Dict[str, object]) -> str:
        session = payload["session"]
        statistics = payload["statistics"]
        rows = payload["candidates"]
        cards = []
        for row in rows:
            average = "无投票" if row["average_score"] is None else "%.2f" % row["average_score"]
            rank = "—" if row["rank"] is None else str(row["rank"])
            distribution = row["score_distribution"]
            failure = (
                '<p class="send-failed">这张图发送失败，未计入有效统计</p>'
                if row.get("send_status") == "send_failed"
                else ""
            )
            cards.append(
                """<article class=\"candidate-card\" data-title=\"%s\" data-index=\"%s\" data-rank=\"%s\">
  <a href=\"%s\"><img loading=\"lazy\" src=\"%s\" alt=\"%s\"></a>
  <div class=\"candidate-content\"><h2>#%s %s</h2><p class=\"score\">排名 %s · 平均分 %s · %s 人投票</p>
  <p class=\"distribution\">1分 %s · 2分 %s · 3分 %s · 4分 %s</p>%s<p class=\"filename\">%s</p></div></article>"""
                % (
                    html.escape(str(row["display_title"]), quote=True),
                    row["display_index"],
                    row["rank"] or 0,
                    html.escape(str(row["main_image"]), quote=True),
                    html.escape(str(row["thumbnail"]), quote=True),
                    html.escape(str(row["display_title"]), quote=True),
                    row["display_index"],
                    html.escape(str(row["display_title"])),
                    rank,
                    average,
                    row["vote_count"],
                    distribution.get(1, 0),
                    distribution.get(2, 0),
                    distribution.get(3, 0),
                    distribution.get(4, 0),
                    failure,
                    html.escape(str(row["source_filename"])),
                )
            )
        summary = payload.get("ai_summary") or "未启用 AI 总结，以上为纯统计结果。"
        return """<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>%s · 图片投票报告</title><link rel=\"stylesheet\" href=\"./report.css\"></head>
<body><main class=\"container\"><header><div class=\"eyebrow\">ASTRBOT IMAGE VOTE</div><h1>%s</h1>
<p class=\"meta\">Session %s · 群 %s · 状态 %s</p>
<p class=\"meta\">开始 %s · 结束 %s</p><section class=\"summary-grid\">
<div><strong>%s</strong><span>图片</span></div><div><strong>%s</strong><span>有效票</span></div><div><strong>%s</strong><span>参与人数</span></div><div><strong>%s</strong><span>总体平均分</span></div></section>
<section class=\"ai-summary\"><h2>总结</h2><p>%s</p></section></header>
<section class=\"toolbar\"><input id=\"search\" type=\"search\" placeholder=\"搜索图片名称\"><button id=\"sort\" type=\"button\">切换原始顺序</button><span class=\"hint\">默认按排名显示</span></section>
<section id=\"candidates\" class=\"candidate-grid\">%s</section></main><script src=\"./report.js\"></script></body></html>""" % (
            html.escape(str(session["project_name"])),
            html.escape(str(session["project_name"])),
            html.escape(str(session["short_id"])),
            html.escape(str(session["group_id"])),
            html.escape(str(session["status"])),
            html.escape(_format_time(session.get("started_at"))),
            html.escape(_format_time(session.get("finished_at"))),
            statistics["total_candidates"],
            statistics["total_valid_votes"],
            statistics["unique_voters"],
            "无" if statistics["overall_average_score"] is None else "%.2f" % statistics["overall_average_score"],
            html.escape(str(summary)),
            "".join(cards),
        )


def _format_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


class ReportCleanupService:
    def __init__(self, output_root: Path):
        self.output_root = output_root.expanduser()
        self.guard = PathGuard(self.output_root)

    def cleanup(self, selector: str, confirmed: bool = False) -> int:
        if selector == "all":
            if not confirmed:
                raise PermissionError("cleaning all reports requires explicit confirmation")
            target_project = None
            target_session = None
        else:
            target_project = DirectoryReportGenerator.project_slug(selector)
            target_session = selector
        if not self.output_root.is_dir():
            return 0
        removed = 0
        for project_dir in self.output_root.iterdir():
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue
            for report_dir in project_dir.iterdir():
                if not report_dir.is_dir() or report_dir.is_symlink():
                    continue
                marker = report_dir / REPORT_MARKER
                if not marker.is_file() or marker.is_symlink():
                    continue
                try:
                    payload = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if payload.get("plugin") != PLUGIN_NAME:
                    continue
                session_id = str(payload.get("session_id") or "")
                short_id = str(payload.get("short_id") or "")
                matches = (
                    selector == "all"
                    or session_id == target_session
                    or (short_id and short_id.upper() == selector.upper())
                    or report_dir.name == selector
                    or report_dir.name.startswith("%s-" % selector)
                    or project_dir.name == target_project
                )
                if matches:
                    self.guard.cleanup_report(report_dir, REPORT_MARKER, PLUGIN_NAME)
                    removed += 1
        return removed

    def cleanup_expired(self, retention_days: int) -> int:
        if retention_days <= 0 or not self.output_root.is_dir():
            return 0
        cutoff = time.time() - retention_days * 86400
        removed = 0
        for project_dir in self.output_root.iterdir():
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue
            for report_dir in project_dir.iterdir():
                if not report_dir.is_dir() or report_dir.is_symlink():
                    continue
                marker = report_dir / REPORT_MARKER
                if not marker.is_file() or marker.is_symlink():
                    continue
                try:
                    payload = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if payload.get("plugin") != PLUGIN_NAME:
                    continue
                if self._report_timestamp(payload, marker) >= cutoff:
                    continue
                try:
                    self.guard.cleanup_report(report_dir, REPORT_MARKER, PLUGIN_NAME)
                    removed += 1
                except UnsafePathError:
                    logger.error("自动清理跳过不安全的报告目录：%s", report_dir)
        return removed

    @staticmethod
    def _report_timestamp(payload: Dict[str, object], marker: Path) -> float:
        created_at = payload.get("created_at")
        if isinstance(created_at, str) and created_at:
            try:
                return datetime.fromisoformat(created_at).timestamp()
            except ValueError:
                pass
        try:
            return marker.stat().st_mtime
        except OSError:
            return time.time()
