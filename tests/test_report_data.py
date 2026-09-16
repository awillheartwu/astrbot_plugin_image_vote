import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from src.models import Candidate, SendStatus, Session, SessionStatus, Vote, VoteSource
from src.report_generator import DirectoryReportGenerator, ReportGenerationError
from src.statistics_service import calculate_statistics
from tests.test_report_generator import FakeImageProcessor


class ReportDataTest(unittest.TestCase):
    def test_legacy_report_without_score_snapshot_still_renders(self):
        payload={'session':{'id':'old','short_id':'OLD','project_name':'legacy','group_id':'g','status':'COMPLETED'},
                 'statistics':{'total_candidates':0,'total_valid_votes':0,'unique_voters':0,'overall_average_score':None},
                 'candidates':[]}
        page=DirectoryReportGenerator._render_html(payload)
        self.assertIn('评分范围 1-4',page)
        self.assertNotIn('score_min',payload['session'])

    def fixture(self, root):
        source = root / 'input'
        source.mkdir()
        candidates = []
        for index in range(1, 4):
            name = '%s.png' % index
            (source / name).write_bytes(b'original')
            candidates.append(Candidate('c%s' % index, 's1', index, name, name,
                                        'Title </script><script>alert(1)</script>' if index == 1 else name,
                                        None, 8, send_status=SendStatus.SENT if index < 3 else SendStatus.PENDING))
        session = Session('s1', 'SHORT', 'private-group', 'umo', 'project', str(source),
                          status=SessionStatus.COMPLETED, candidate_count=3, score_max=10)
        votes = [Vote(None, 's1', 'c1', '123456789', 'Name </script>', 10,
                      VoteSource.CURRENT_WINDOW, message_id='private-message')]
        return source, candidates, session, votes, calculate_statistics(candidates, votes, 1, 10)

    def test_real_votes_project_to_safe_offline_data_and_correct_denominators(self):
        async def run(root):
            source, candidates, session, votes, stats = self.fixture(root)
            report = await DirectoryReportGenerator().generate(session, candidates, stats, source,
                root / 'out', FakeImageProcessor(), votes=votes)
            payload = json.loads((report / 'data.json').read_text())
            self.assertEqual(payload['schema_version'], 3)
            self.assertEqual(payload['participants'][0]['coverage'], .5)
            self.assertEqual(payload['metrics']['filling_coverage'], .5)
            self.assertEqual(payload['metrics']['unrated_count'], 1)
            self.assertEqual(payload['metrics']['pending_count'], 1)
            self.assertNotIn('average_score', payload['candidates'][0])
            voted_character = next(item for item in payload['characters'] if item['vote_count'])
            self.assertIsNone(voted_character['standard_deviation'])
            self.assertTrue(voted_character['low_sample'])
            self.assertEqual(payload['votes'][0]['character'], voted_character['character'])
            self.assertEqual(payload['votes'][0]['participant_id'], 'p1')
            self.assertNotIn('123456789', json.dumps(payload))
            self.assertNotIn('private-message', json.dumps(payload))
            page = (report / 'index.html').read_text()
            embedded = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', page, re.S).group(1)
            self.assertNotIn('</script>', embedded)
            self.assertEqual(json.loads(embedded)['participants'][0]['name'], 'Name </script>')
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))

    def test_share_report_removes_personal_data_from_html_and_json(self):
        async def run(root):
            source, candidates, session, votes, stats = self.fixture(root)
            report = await DirectoryReportGenerator().generate(session, candidates, stats, source,
                root / 'out', FakeImageProcessor(), votes=votes, include_participants=False)
            for name in ('index.html', 'data.json'):
                content = (report / name).read_text()
                for secret in ('123456789', 'Name', 'private-group', 'private-message'):
                    self.assertNotIn(secret, content)
            payload = json.loads((report / 'data.json').read_text())
            self.assertEqual(payload['votes'], [])
            self.assertFalse(payload['participant_details_available'])
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))

    def test_reexport_failure_preserves_previous_report(self):
        class BrokenProcessor:
            def process(self, *args):
                raise RuntimeError('fixture compression failure')
        async def run(root):
            source, candidates, session, votes, stats = self.fixture(root)
            generator = DirectoryReportGenerator()
            report = await generator.generate(session, candidates, stats, source, root / 'out', FakeImageProcessor(), votes=votes)
            before = {str(p.relative_to(report)): p.read_bytes() for p in report.rglob('*') if p.is_file()}
            with self.assertRaises(ReportGenerationError):
                await generator.generate(session, candidates, stats, source, root / 'out', BrokenProcessor(), votes=votes)
            after = {str(p.relative_to(report)): p.read_bytes() for p in report.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse(list((root / 'out').glob('.image-vote-*')))
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))

    def test_single_html_contains_people_and_no_external_asset_references(self):
        async def run(root):
            source, candidates, session, votes, stats = self.fixture(root)
            report = await DirectoryReportGenerator().generate_single_html(session, candidates, stats, source,
                root / 'out', FakeImageProcessor(), 2, votes=votes)
            content = (report / 'index.html').read_text()
            self.assertIn('data:image/webp;base64', content)
            self.assertNotIn('src="./report.js"', content)
            self.assertNotIn('href="./report.css"', content)
            self.assertIn('Name', content)
            payload = json.loads((report / 'data.json').read_text())
            self.assertEqual(payload['report_mode'], 'single_html')
            self.assertTrue(all(r['main_image'] is None for r in payload['candidates']))
            self.assertFalse((report / 'images').exists())
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))


class StructuredSummaryProjectionTest(unittest.TestCase):
    def test_summary_projection_and_no_script_fallback(self):
        from src.report_data import enrich_report
        summary = {'headline':'<样本高分>', 'insights':[{'title':'观察', 'text':'仅有一位参与者。'}]}
        payload = {'session': {'id':'s','short_id':'S','project_name':'P','score_min':0,'score_max':10,
                              'status':'COMPLETED'},
                   'statistics': {'unique_voters':0,'total_candidates':0,'total_valid_votes':0,'overall_average_score':None},
                   'characters':[], 'candidates':[], 'ai_summary':json.dumps(summary,ensure_ascii=False)}
        enrich_report(payload, include_participants=False)
        self.assertEqual(payload['ai_analysis']['headline'], '<样本高分>')
        html = DirectoryReportGenerator._render_html(payload)
        fallback = html.split('<script id="report-data"')[0]
        self.assertIn('&lt;样本高分&gt;', fallback)
        self.assertIn('观察：仅有一位参与者。', fallback)
        self.assertNotIn('"headline"', fallback)


class CompactImageReportTest(unittest.TestCase):
    fixture = ReportDataTest.fixture
    def test_compact_covers_and_asset_pool(self):
        async def run(root):
            source, candidates, session, votes, _ = self.fixture(root)
            candidates[0].character = candidates[1].character = 'Alice'
            candidates[2].character = 'Iris'
            candidates[0].send_status = SendStatus.SEND_FAILED
            stats = calculate_statistics(candidates, votes, 1, 10)
            generator = DirectoryReportGenerator()
            directory = await generator.generate(session, candidates, stats, source, root/'directory', FakeImageProcessor(), votes=votes)
            data = json.loads((directory/'data.json').read_text())
            self.assertEqual([r['image_quality'] for r in data['candidates']], ['thumbnail','main','main'])
            self.assertFalse((directory/'images/0001.webp').exists())
            self.assertEqual(len(list((directory/'images').glob('*.webp'))), 5)
            self.assertEqual(data['candidates'][0]['main_image'], data['candidates'][0]['thumbnail'])
            single = await generator.generate_single_html(session, candidates, stats, source, root/'single', FakeImageProcessor(), 5, votes=votes)
            html = (single/'index.html').read_text()
            inline = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>',html,re.S).group(1))
            self.assertEqual(len(inline['image_assets']),2)  # Fake processor writes identical main / thumb bytes.
            for uri in inline['image_assets'].values():
                self.assertEqual(html.count(uri),1)
            for row in inline['candidates']:
                self.assertIn(row['main_image'],inline['image_assets'])
                self.assertIn(row['thumbnail'],inline['image_assets'])
            self.assertNotIn('href="asset:',html)
            all_images = await DirectoryReportGenerator(image_policy='all').generate(session,candidates,stats,source,root/'all',FakeImageProcessor())
            self.assertEqual(len(list((all_images/'images').glob('*.webp'))),6)
            self.assertTrue(all(p.read_bytes()==b'original' for p in source.iterdir()))
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))
