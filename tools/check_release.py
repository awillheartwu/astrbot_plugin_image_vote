"""Build and smoke-test the committed Git archive in a disposable directory (Pillow required)."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = r'''
import asyncio, importlib, json
from pathlib import Path
from PIL import Image
plugin=importlib.import_module('astrbot_plugin_image_vote.main')
from astrbot_plugin_image_vote.src.config import VoteConfig
from astrbot_plugin_image_vote.src.models import Candidate, Session, SessionStatus, SendStatus
from astrbot_plugin_image_vote.src.image_processor import PillowImageProcessor
from astrbot_plugin_image_vote.src.report_generator import DirectoryReportGenerator
from astrbot_plugin_image_vote.src.statistics_service import calculate_statistics
from astrbot_plugin_image_vote.src.persistence import SQLiteStore
async def run():
    root=Path('disposable-state');root.mkdir()
    source=root/'input';source.mkdir()
    candidates=[]
    for i in range(2):
        name=f'{i}.png';Image.new('RGB',(640,480),(i*80,70,120)).save(source/name)
        candidates.append(Candidate(str(i),'release',i+1,name,name,name,None,(source/name).stat().st_size,character='Demo',send_status=SendStatus.SENT))
    session=Session('release','REL','fake','fake','fixture',str(source),status=SessionStatus.COMPLETED,candidate_count=2,character_count=1)
    store=SQLiteStore(root/'vote.db');await store.initialize();await store.save_session(session);await store.save_candidates(candidates);await store.close()
    reopened=SQLiteStore(root/'vote.db');await reopened.initialize();assert (await reopened.get_session('release')).status==SessionStatus.COMPLETED;await reopened.close()
    config=VoteConfig.from_mapping({});assert config.ai_prompt_template and config.report_image_policy=='character_cover'
    generator=DirectoryReportGenerator();processor=PillowImageProcessor();stats=calculate_statistics(candidates,[])
    directory=await generator.generate(session,candidates,stats,source,root/'directory',processor,votes=[])
    payload=json.loads((directory/'data.json').read_text());assert len(list((directory/'images').glob('*.webp')))==3
    single=await generator.generate_single_html(session,candidates,stats,source,root/'single',processor,50,votes=[])
    html=(single/'index.html').read_text();assert 'image_assets' in html and 'data:image/webp;base64,' in html
    assert not (single/'images').exists()
    print(json.dumps({'version':plugin.VERSION,'directory_and_single_html':True,'sqlite_reopen':True,'originals_retained':len(list(source.glob('*.png')))==2}))
asyncio.run(run())
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='HEAD');parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    revision=subprocess.check_output(['git','rev-parse','--verify',args.ref+'^{commit}'],cwd=ROOT,text=True).strip()
    data=subprocess.check_output(['git','archive','--format=zip','--prefix=astrbot_plugin_image_vote/',revision],cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=archive.namelist();prefix='astrbot_plugin_image_vote/'
        for file in ['main.py','src/version.py','metadata.yaml','_conf_schema.json','LICENSE','pages/image-vote/app.js','assets/report.js','requirements.txt']:
            assert prefix+file in names,file
        assert not any(n.startswith(prefix+p+'/') for n in names for p in ['prototypes','docs','tests','tools','.git'])
        assert len(data)<16*1024*1024,'Archive exceeds 16 MiB'
        version=re.search(r'^version:\s*(\S+)',archive.read(prefix+'metadata.yaml').decode(),re.M).group(1)
        with tempfile.TemporaryDirectory(prefix='lirating-release-') as temp:
            archive.extractall(temp)
            result=subprocess.check_output([sys.executable,'-B','-c',SMOKE],cwd=temp,text=True)
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/f'astrbot_plugin_image_vote-{version}.zip';target.write_bytes(data)
    digest=hashlib.sha256(data).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n')
    evidence={'commit':revision,'version':version,'bytes':len(data),'sha256':digest,'smoke':json.loads(result),'scope':'clean archive; real Pillow/SQLite; no AstrBot server, real QQ or model calls'}
    target.with_suffix('.checks.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(evidence,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
