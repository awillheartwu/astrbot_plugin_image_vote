import asyncio
import tempfile
import unittest
from pathlib import Path

from src.models import Candidate, CandidateStatistics, Session, SessionStatistics, SessionStatus, VoteSource
from src.path_guard import PathGuard, UnsafePathError
from src.report_generator import DirectoryReportGenerator, PLUGIN_NAME, REPORT_MARKER
from src.report_generator import ReportCleanupService


class FakeImageProcessor:
    def process(self, source_path, main_path, thumbnail_path):
        main_path.write_bytes(b"derived-main")
        thumbnail_path.write_bytes(b"derived-thumb")


class ReportGeneratorTest(unittest.TestCase):
    def test_directory_report_uses_derivatives_and_safe_marker(self):
        async def scenario(root):
            source_root = root / "input"
            output_root = root / "output"
            source_root.mkdir()
            source = source_root / "<unsafe>.png"
            source.write_bytes(b"original")
            candidate = Candidate("c1", "s1", 1, source.name, source.name, "<unsafe>", None, source.stat().st_size)
            statistics = SessionStatistics(
                total_candidates=1,
                total_valid_votes=1,
                unique_voters=1,
                average_votes_per_candidate=1.0,
                overall_average_score=4.0,
                candidates=(CandidateStatistics("c1", 1, "<unsafe>", 1, 4.0, {1: 0, 2: 0, 3: 0, 4: 1}, 1),),
            )
            session = Session("s1", "A7F3", "g1", "umo", "project", str(source_root), SessionStatus.COMPLETED, candidate_count=1)
            report = await DirectoryReportGenerator().generate(
                session, [candidate], statistics, source_root, output_root, FakeImageProcessor()
            )
            self.assertTrue((report / "index.html").is_file())
            self.assertTrue((report / "data.json").is_file())
            self.assertTrue((report / "images/0001.webp").is_file())
            self.assertEqual(source.read_bytes(), b"original")
            guard = PathGuard(output_root)
            self.assertEqual(guard.ensure_report_directory(report, REPORT_MARKER, PLUGIN_NAME), report.resolve())
            guard.cleanup_report(report, REPORT_MARKER, PLUGIN_NAME)
            self.assertFalse(report.exists())
            self.assertTrue(source.exists())

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_cleanup_ignores_foreign_report_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            own = root / "project" / "own"
            foreign = root / "project" / "foreign"
            own.mkdir(parents=True)
            foreign.mkdir(parents=True)
            (own / REPORT_MARKER).write_text('{"plugin":"%s","session_id":"s1"}' % PLUGIN_NAME, encoding="utf-8")
            (foreign / REPORT_MARKER).write_text('{"plugin":"other","session_id":"s2"}', encoding="utf-8")
            self.assertEqual(ReportCleanupService(root).cleanup("s1"), 1)
            self.assertFalse(own.exists())
            self.assertTrue(foreign.exists())
            with self.assertRaises(PermissionError):
                ReportCleanupService(root).cleanup("all")

    def test_cleanup_matches_short_id_and_report_directory_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "slug" / "A7F3-abcdef12"
            second = root / "slug" / "B1C2-deadbeef"
            for path, short_id in ((first, "A7F3"), (second, "B1C2")):
                path.mkdir(parents=True)
                (path / REPORT_MARKER).write_text(
                    '{"plugin":"%s","session_id":"ff","short_id":"%s"}' % (PLUGIN_NAME, short_id),
                    encoding="utf-8",
                )
            self.assertEqual(ReportCleanupService(root).cleanup("a7f3"), 1)
            self.assertEqual(ReportCleanupService(root).cleanup("B1C2-deadbeef"), 1)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_cleanup_expired_removes_only_old_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "slug" / "OLD1-00000000"
            fresh = root / "slug" / "NEW1-11111111"
            old.mkdir(parents=True)
            fresh.mkdir(parents=True)
            (old / REPORT_MARKER).write_text(
                '{"plugin":"%s","session_id":"a","short_id":"OLD1","created_at":"2020-01-01T00:00:00+00:00"}'
                % PLUGIN_NAME,
                encoding="utf-8",
            )
            (fresh / REPORT_MARKER).write_text(
                '{"plugin":"%s","session_id":"b","short_id":"NEW1"}' % PLUGIN_NAME, encoding="utf-8"
            )
            self.assertEqual(ReportCleanupService(root).cleanup_expired(30), 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_report_renders_configured_score_range(self):
        async def scenario(root):
            source_root = root / "input"
            output_root = root / "output"
            source_root.mkdir()
            source = source_root / "one.png"
            source.write_bytes(b"original")
            candidate = Candidate("c1", "s1", 1, source.name, source.name, "One", None, source.stat().st_size)
            distribution = {score: 0 for score in range(1, 11)}
            distribution[10] = 2
            statistics = SessionStatistics(
                total_candidates=1,
                total_valid_votes=2,
                unique_voters=2,
                average_votes_per_candidate=2.0,
                overall_average_score=10.0,
                candidates=(CandidateStatistics("c1", 1, "One", 2, 10.0, distribution, 1),),
            )
            session = Session(
                "s1", "A7F3", "g1", "umo", "project", str(source_root), SessionStatus.COMPLETED,
                candidate_count=1, score_min=1, score_max=10,
            )
            report = await DirectoryReportGenerator().generate(
                session, [candidate], statistics, source_root, output_root, FakeImageProcessor()
            )
            page = (report / "index.html").read_text(encoding="utf-8")
            self.assertIn("评分范围 1-10", page)
            self.assertIn("10分 2", page)
            self.assertIn("5分 0", page)

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_single_html_embeds_derivatives_and_falls_back_when_too_large(self):
        async def scenario(root):
            source_root = root / "input"
            output_root = root / "output"
            source_root.mkdir()
            source = source_root / "one.png"
            source.write_bytes(b"original")
            candidate = Candidate("c1", "s1", 1, source.name, source.name, "One", None, source.stat().st_size)
            statistics = SessionStatistics(
                total_candidates=1,
                total_valid_votes=0,
                unique_voters=0,
                average_votes_per_candidate=0.0,
                overall_average_score=None,
                candidates=(CandidateStatistics("c1", 1, "One", 0, None, {1: 0, 2: 0, 3: 0, 4: 0}, None),),
            )
            session = Session("s1", "A7F3", "g1", "umo", "project", str(source_root), SessionStatus.COMPLETED, candidate_count=1)
            report = DirectoryReportGenerator().generate_single_html
            small = await report(session, [candidate], statistics, source_root, output_root, FakeImageProcessor(), 1)
            self.assertIn("data:image/webp;base64", (small / "index.html").read_text(encoding="utf-8"))
            fallback = await DirectoryReportGenerator().generate_single_html(
                session, [candidate], statistics, source_root, output_root, FakeImageProcessor(), 0
            )
            fallback_payload = (fallback / "data.json").read_text(encoding="utf-8")
            self.assertIn('"fallback_reason"', fallback_payload)
            self.assertNotIn("data:image/", fallback_payload)

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))
