"""Generate real reports from disposable example votes and synthetic image fixtures."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sample_project import create_sample_project
from src.image_processor import PillowImageProcessor
from src.models import Candidate, SendStatus, Session, SessionStatus, Vote, VoteSource
from src.report_generator import DirectoryReportGenerator
from src.statistics_service import calculate_statistics


async def main():
    root = Path('/tmp/lirating-report-preview')
    source = root / 'assets'
    create_sample_project(source)
    session = Session('preview-session', 'PREVIEW', '示例讨论组', 'preview', '海滨之家 · 示例报告',
                      str(source), status=SessionStatus.COMPLETED, score_max=5, candidate_count=3, character_count=2,
                      started_at='2026-09-12T14:00:00+08:00', finished_at='2026-09-12T14:03:00+08:00')
    candidates = [Candidate('image-%s' % i, session.id, i, name+'.png', name+'.png', title,
                            None, (source/(name+'.png')).stat().st_size, character=character,
                            send_status=SendStatus.SENT)
                  for i, (name, title, character) in enumerate([('alice', 'Alice · 海风与她', 'Alice'),
                  ('grace', 'Alice · 午后小憩', 'Alice'), ('iris', 'Iris · 树荫下的回眸', 'Iris')], 1)]
    names = ['星海与风', '柠檬汽水', '花间旅人', '晚风', 'Mirage', '海盐冰', '青禾', '山间来信']
    scores = [[5, 5, 4, 5, 4, 5, 4, 5], [5, 2, 4, 2, 5, 3, 4, 1]]
    votes = [Vote(None, session.id, c.id, 'demo-%d' % i, names[i], value, VoteSource.CURRENT_WINDOW,
                  created_at=session.started_at, updated_at=session.finished_at, character=c.character)
             for c, values in zip((candidates[1], candidates[2]), scores) for i, value in enumerate(values)]
    statistics = calculate_statistics(candidates, votes, 1, 5)
    generator, processor = DirectoryReportGenerator(), PillowImageProcessor()
    directory = await generator.generate(session, candidates, statistics, source,
                                         root/'generated'/'directory', processor, votes=votes)
    single = await generator.generate_single_html(session, candidates, statistics, source,
                                                  root/'generated'/'single', processor, 50, votes=votes)
    for path in (directory, single):
        print('http://127.0.0.1:8768/' + str((path/'index.html').relative_to(root)))


if __name__ == '__main__':
    asyncio.run(main())
