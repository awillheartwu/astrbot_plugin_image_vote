"""Validate sequential processing of >500 MB valid PNG input in a disposable directory."""
import asyncio
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.image_processor import PillowImageProcessor
from src.models import Session, SessionStatus
from src.project_scanner import scan_project
from src.report_generator import DirectoryReportGenerator
from src.statistics_service import calculate_statistics


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        while chunk:=file.read(1024*1024):
            value.update(chunk)
    return value.hexdigest()


def prepare(root):
    source=root/'input'
    source.mkdir()
    image=Image.frombytes('RGB',(5000,5000),os.urandom(5000*5000*3))
    image.save(source/'1.png','PNG',compress_level=0)
    image.close()
    del image
    for i in range(2,8):
        shutil.copyfile(source/'1.png',source/('%d.png'%i))


async def run(root):
    source=root/'input'
    snapshot=scan_project(source,session_id='large')
    before={p.name:digest(p) for p in source.iterdir()}
    assert snapshot.total_size>500*1024*1024
    session=Session('large','LARGE','fixture','fixture','large-input',str(source),
                    status=SessionStatus.COMPLETED,candidate_count=len(snapshot.candidates))
    statistics=calculate_statistics(snapshot.candidates,[])
    started=time.monotonic()
    output=await DirectoryReportGenerator().generate(session,snapshot.candidates,statistics,source,
                                                      root/'out',PillowImageProcessor(),votes=[])
    elapsed=time.monotonic()-started
    assert len(list((output/'images').glob('*.webp')))==14
    assert before=={p.name:digest(p) for p in source.iterdir()}
    output_bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform!='darwin':
        peak*=1024
    return {'input_bytes':snapshot.total_size,'images':7,'dimensions':[5000,5000],
            'output_bytes':output_bytes,'elapsed_seconds':round(elapsed,2),'process_peak_rss_bytes':peak,
            'original_sha256_unchanged':True,'derived_images':14,
            'fixture':'valid high-entropy PNG images; seven copies, not production photos'}


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--worker':
        print(json.dumps(asyncio.run(run(Path(sys.argv[2]))),indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix='lirating-large-report-') as directory:
            prepare(Path(directory))
            subprocess.run([sys.executable,__file__,'--worker',directory],check=True)
