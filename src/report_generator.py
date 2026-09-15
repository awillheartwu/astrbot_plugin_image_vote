from __future__ import annotations

import asyncio
import base64
import html
import json
import mimetypes
import os
import tempfile
import uuid
import weakref
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol

from .character_service import character_of
from .logging_utils import get_logger
from .models import Candidate, Session, SessionStatistics, Vote
from .report_data import enrich_report
from .path_guard import PathGuard, UnsafePathError
from .report_activity import ReportBusyError


REPORT_MARKER = ".astrbot_image_vote_report"
PLUGIN_NAME = "astrbot_plugin_image_vote"
logger = get_logger()
_report_locks = weakref.WeakValueDictionary()


class ImageProcessor(Protocol):
    def process(self, source_path: Path, main_path: Path, thumbnail_path: Path):
        """Create report-only derivatives without modifying source_path."""


class ReportGenerationError(RuntimeError):
    pass


class DirectoryReportGenerator:
    def __init__(self, asset_root: Optional[Path] = None, image_extension: str = "webp", avatar_service=None):
        self.asset_root = asset_root or Path(__file__).resolve().parent.parent / "assets"
        self.image_extension = image_extension.lstrip(".").lower()
        self.avatar_service = avatar_service

    async def _generate_directory(
        self,
        session: Session,
        candidates: Iterable[Candidate],
        statistics: SessionStatistics,
        source_root: Path,
        output_root: Path,
        image_processor: ImageProcessor,
        ai_summary: Optional[str] = None,
        votes: Optional[Iterable[Vote]] = None,
        include_participants: bool = True,
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
        if votes is not None:
            votes = tuple(votes)
        stats_by_id = {item.candidate_id: item for item in statistics.candidates}
        rows: List[Dict[str, object]] = []
        for candidate in candidate_list:
            source_path = source_guard.ensure_within(source_root / candidate.source_relative_path, allow_root=False)
            stem = "%04d" % candidate.display_index
            main_path = images_dir / (stem + "." + self.image_extension)
            thumb_path = images_dir / (stem + "_thumb." + self.image_extension)
            try:
                # A cancelled task must wait for its worker before removing staging files.
                worker = asyncio.create_task(asyncio.to_thread(image_processor.process, source_path, main_path, thumb_path))
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            except Exception as exc:
                raise ReportGenerationError("failed to process %s: %s" % (candidate.source_filename, exc)) from exc
            item = stats_by_id[candidate.id]
            rows.append(
                {
                    "candidate_id": candidate.id,
                    "display_index": candidate.display_index,
                    "display_title": candidate.display_title,
                    "character": character_of(candidate),
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
                "character_count": session.character_count,
                "status": session.status.value,
                "score_min": session.score_min,
                "score_max": session.score_max,
                "started_at": session.started_at,
                "finished_at": session.finished_at,
            },
            "statistics": {
                "total_candidates": statistics.total_candidates,
                "total_valid_votes": statistics.total_valid_votes,
                "unique_voters": statistics.unique_voters,
                "average_votes_per_candidate": statistics.average_votes_per_candidate,
                "overall_average_score": statistics.overall_average_score,
                "total_characters": statistics.total_characters,
                "average_votes_per_character": statistics.average_votes_per_character,
            },
            "characters": [
                {
                    "character": item.character,
                    "candidate_ids": [
                        candidate.id for candidate in candidate_list
                        if character_of(candidate) == item.character
                    ],
                    "candidate_count": item.candidate_count,
                    "vote_count": item.vote_count,
                    "average_score": item.average_score,
                    "score_distribution": item.score_distribution,
                    "rank": item.rank,
                }
                for item in statistics.characters
            ],
            "candidates": rows,
            "ai_summary": ai_summary,
        }
        rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0, row["display_index"]))
        payload["candidates"] = rows
        enrich_report(payload, votes, include_participants)
        if include_participants and self.avatar_service is not None and votes is not None:
            candidate_ids = {c.id for c in candidate_list}
            voter_ids = sorted({v.voter_id for v in votes if v.session_id == session.id
                                and v.candidate_id in candidate_ids and session.score_min <= v.score <= session.score_max})
            async def attach(index, voter_id):
                content = await self.avatar_service.get(voter_id)
                if content:
                    relative = 'images/avatars/p%d.webp' % (index + 1)
                    path = report_dir / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    payload['participants'][index]['avatar'] = relative
            # Process a bounded batch instead of creating a task for every voter at once.
            for offset in range(0, len(voter_ids), 4):
                await asyncio.gather(*(attach(i, voter_ids[i]) for i in range(offset, min(offset + 4, len(voter_ids)))))
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

    async def generate(self, session, candidates, statistics, source_root, output_root,
                       image_processor, ai_summary=None, votes=None, include_participants=True):
        return await self._publish(session, candidates, statistics, source_root, output_root,
                                   image_processor, ai_summary, votes, include_participants, None)

    async def generate_single_html(self, session, candidates, statistics, source_root, output_root,
                                   image_processor, max_mb, ai_summary=None, votes=None,
                                   include_participants=True):
        return await self._publish(session, candidates, statistics, source_root, output_root,
                                   image_processor, ai_summary, votes, include_participants, max_mb)

    async def _publish(self, session, candidates, statistics, source_root, output_root,
                       image_processor, ai_summary, votes, include_participants, max_mb):
        key = str(Path(output_root).expanduser().resolve()) + ':' + session.id
        lock = _report_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await self._publish_locked(session, candidates, statistics, source_root, output_root,
                                             image_processor, ai_summary, votes, include_participants, max_mb)

    async def _publish_locked(self, session, candidates, statistics, source_root, output_root,
                             image_processor, ai_summary, votes, include_participants, max_mb):
        # Complete in a staging directory. An unsuccessful re-export leaves the previous report intact.
        output_root = Path(output_root).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.image-vote-', dir=output_root) as temporary:
            staged = await self._generate_directory(
                session, candidates, statistics, source_root, Path(temporary), image_processor,
                ai_summary=ai_summary, votes=votes, include_participants=include_participants)
            data_path = staged / 'data.json'
            payload = json.loads(data_path.read_text(encoding='utf-8'))
            if max_mb is not None:
                inline = json.loads(json.dumps(payload))
                for row in inline['candidates']:
                    row['main_image'] = self._data_uri(staged / row['main_image'])
                    row['thumbnail'] = self._data_uri(staged / row['thumbnail'])
                for person in inline['participants']:
                    if person.get('avatar'):
                        person['avatar'] = self._data_uri(staged / person['avatar'])
                inline['report_mode'] = 'single_html'
                page = self._render_inline_html(inline)
                if len(page.encode('utf-8')) <= max_mb * 1024 * 1024:
                    (staged / 'index.html').write_text(page, encoding='utf-8')
                    payload['report_mode'] = 'single_html'
                    # No dangling file references in the companion JSON after removing assets.
                    for row in payload['candidates']:
                        row['main_image'] = None
                        row['thumbnail'] = None
                    for person in payload['participants']:
                        person['avatar'] = None
                    self._remove_directory_only_assets(staged)
                else:
                    payload['fallback_reason'] = 'single_html_max_mb exceeded'
                    (staged / 'index.html').write_text(self._render_html(payload), encoding='utf-8')
                    logger.warning('单文件报告超过体积上限，已回退目录模式')
                data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            guard = PathGuard(output_root)
            target = guard.ensure_within(output_root / self._slug(session.project_name) / staged.name, allow_root=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if target.exists():
                guard.ensure_report_directory(target, REPORT_MARKER, PLUGIN_NAME)
                marker = json.loads((target / REPORT_MARKER).read_text(encoding='utf-8'))
                if marker.get('session_id') != session.id:
                    raise ReportGenerationError('report directory belongs to another session')
                backup = target.with_name('.backup-' + uuid.uuid4().hex)
                os.replace(target, backup)
            try:
                os.replace(staged, target)
            except BaseException:
                if backup is not None:
                    os.replace(backup, target)
                raise
            if backup is not None:
                shutil.rmtree(backup)
            return target

    @staticmethod
    def _remove_directory_only_assets(report_dir: Path) -> None:
        """单文件模式已把图片内嵌进 index.html，清掉目录模式的附属文件，避免看起来像目录报告。"""
        for name in ("report.css", "report.js"):
            target = report_dir / name
            if target.is_file():
                target.unlink()
        images = report_dir / "images"
        if images.is_dir():
            shutil.rmtree(str(images), ignore_errors=True)

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
        session = {"score_min": 1, "score_max": 4, **payload["session"]}
        payload = {**payload, "session": session}
        statistics = payload["statistics"]
        rows = payload["candidates"]
        characters = payload.get("characters") or []
        character_section = ""
        if characters:
            character_rows = []
            for item in characters:
                rank = "—" if item["rank"] is None else str(item["rank"])
                average = "无投票" if item["average_score"] is None else "%.2f" % item["average_score"]
                character_rows.append(
                    "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (
                        rank,
                        html.escape(str(item["character"])),
                        item["candidate_count"],
                        item["vote_count"],
                        average,
                    )
                )
            character_section = (
                '<section class="characters"><h2>人物排名（同一人物的图片合并展示）</h2>'
                "<table><thead><tr><th>排名</th><th>人物</th><th>图片数</th><th>票数</th><th>平均分</th></tr></thead>"
                "<tbody>%s</tbody></table></section>" % "".join(character_rows)
            )
        cards = []
        for row in rows:
            failure = (
                '<p class="send-failed">这张图发送失败，未计入有效统计</p>'
                if row.get("send_status") == "send_failed"
                else ""
            )
            cards.append(
                """<article class=\"candidate-card\" data-title=\"%s\" data-index=\"%s\">
  <a href=\"%s\"><img loading=\"lazy\" src=\"%s\" alt=\"%s\"></a>
  <div class=\"candidate-content\"><h2>#%s %s</h2><p class=\"score\">人物：%s</p>
  %s<p class=\"filename\">%s</p></div></article>"""
                % (
                    html.escape(str(row["display_title"]), quote=True),
                    row["display_index"],
                    html.escape(str(row["main_image"]), quote=True),
                    html.escape(str(row["thumbnail"]), quote=True),
                    html.escape(str(row["display_title"]), quote=True),
                    row["display_index"],
                    html.escape(str(row["display_title"])),
                    html.escape(str(row.get("character") or row["display_title"])),
                    failure,
                    html.escape(str(row["source_filename"])),
                )
            )
        summary = payload.get("ai_summary") or "未启用 AI 总结，以上为纯统计结果。"
        embedded = json.dumps(payload, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        return """<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>%s · 图片投票报告</title><link rel=\"stylesheet\" href=\"./report.css\"></head>
<body><div id=\"report-app\"></div><main id=\"report-fallback\" class=\"container\"><header><div class=\"eyebrow\">ASTRBOT IMAGE VOTE</div><h1>%s</h1>
<p class=\"meta\">Session %s · 群 %s · 状态 %s · 评分范围 %s-%s</p>
<p class=\"meta\">开始 %s · 结束 %s</p><section class=\"summary-grid\">
<div><strong>%s</strong><span>图片</span></div><div><strong>%s</strong><span>有效票</span></div><div><strong>%s</strong><span>参与人数</span></div><div><strong>%s</strong><span>总体平均分</span></div></section>
<section class=\"ai-summary\"><h2>总结</h2><p>%s</p></section></header>
%s
<section class=\"toolbar\"><span class=\"hint\">图片按人物归类；图片本身不单独计票或排名</span></section>
<section id=\"candidates\" class=\"candidate-grid\">%s</section></main><script id=\"report-data\" type=\"application/json\">%s</script><script src=\"./report.js\"></script></body></html>""" % (
            html.escape(str(session["project_name"])),
            html.escape(str(session["project_name"])),
            html.escape(str(session["short_id"])),
            html.escape(str(session.get("group_id", "汇总分享版"))),
            html.escape(str(session["status"])),
            session["score_min"],
            session["score_max"],
            html.escape(_format_time(session.get("started_at"))),
            html.escape(_format_time(session.get("finished_at"))),
            statistics["total_candidates"],
            statistics["total_valid_votes"],
            statistics["unique_voters"],
            "无" if statistics["overall_average_score"] is None else "%.2f" % statistics["overall_average_score"],
            html.escape(str(summary)),
            character_section,
            "".join(cards),
            embedded,
        )


def _format_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


@dataclass
class CleanupResult:
    """清理结果：removed 为删除数，skipped 为因正在使用而跳过的数量。"""

    removed: int = 0
    skipped: int = 0


class ReportCleanupService:
    def __init__(self, output_root: Path):
        self.output_root = output_root.expanduser()
        self.guard = PathGuard(self.output_root)

    def cleanup(self, selector: str, confirmed: bool = False, activity=None) -> "CleanupResult":
        """删除匹配的报告目录；activity 给定时跳过或拒绝正在生成、读取的报告。"""
        if selector == "all":
            if not confirmed:
                raise PermissionError("cleaning all reports requires explicit confirmation")
            target_project = None
            target_session = None
        else:
            target_project = DirectoryReportGenerator.project_slug(selector)
            target_session = selector
        if not self.output_root.is_dir():
            return CleanupResult()
        removed = 0
        skipped = 0
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
                    if activity is None:
                        self.guard.cleanup_report(report_dir, REPORT_MARKER, PLUGIN_NAME)
                        removed += 1
                        continue
                    try:
                        with activity.cleaning(session_id):
                            self.guard.cleanup_report(report_dir, REPORT_MARKER, PLUGIN_NAME)
                    except ReportBusyError:
                        # 清理全部报告时跳过使用中的目录，定向清理则直接报错。
                        if selector != "all":
                            raise
                        skipped += 1
                        logger.warning("报告 %s 正在生成或读取，跳过清理", session_id or report_dir.name)
                        continue
                    removed += 1
        return CleanupResult(removed=removed, skipped=skipped)

    def cleanup_expired(self, retention_days: int, activity=None) -> CleanupResult:
        if retention_days <= 0 or not self.output_root.is_dir():
            return CleanupResult()
        cutoff = time.time() - retention_days * 86400
        removed = 0
        skipped = 0
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
                session_id = str(payload.get("session_id") or "")
                if activity is not None and activity.busy(session_id):
                    skipped += 1
                    logger.warning("报告 %s 正在生成或读取，跳过自动清理", session_id or report_dir.name)
                    continue
                try:
                    self.guard.cleanup_report(report_dir, REPORT_MARKER, PLUGIN_NAME)
                    removed += 1
                except UnsafePathError:
                    logger.error("自动清理跳过不安全的报告目录：%s", report_dir)
        return CleanupResult(removed=removed, skipped=skipped)

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
