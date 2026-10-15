"""Stage a Git bundle through Docker; pass the API key only over exec stdin."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def command(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def find_container():
    name = os.environ.get('ASTRBOT_CONTAINER', '').strip()
    if name:
        detail = json.loads(command('docker', 'inspect', name))[0]
        if not detail['State']['Running']:
            raise RuntimeError('Configured AstrBot container is not running')
        return detail['Id']
    ids = command('docker', 'ps', '-q').split()
    details = json.loads(command('docker', 'inspect', *ids)) if ids else []
    matches = [c for c in details if 'astrbot' in (c['Name'] + ' ' + c['Config']['Image']).lower()]
    if len(matches) != 1:
        raise RuntimeError('Set repository variable ASTRBOT_CONTAINER: expected exactly one running AstrBot container')
    print('AstrBot container: ' + matches[0]['Name'].lstrip('/'), flush=True)
    return matches[0]['Id']


def main():
    key = os.environ.get('ASTRO_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing repository Actions secret ASTRO_KEY')
    revision = command('git', 'rev-parse', 'HEAD', cwd=ROOT)
    metadata = (ROOT / 'metadata.yaml').read_text()
    version = re.search(r'^version:\s*(\S+)', metadata, re.M).group(1)
    container = find_container()
    stage = command('docker', 'exec', container, 'python3', '-c',
                    'import tempfile;print(tempfile.mkdtemp(prefix="lirating-ci-"))')
    handed_off = False
    try:
        with tempfile.TemporaryDirectory(prefix='lirating-ci-bundle-') as temporary:
            bundle = Path(temporary) / 'source.bundle'
            subprocess.run(['git', 'bundle', 'create', str(bundle), 'HEAD'], cwd=ROOT, check=True)
            subprocess.run(['docker', 'cp', str(bundle), container + ':' + stage + '/source.bundle'], check=True)
        subprocess.run(['docker', 'cp', str(Path(__file__).with_name('deploy_worker.py')),
                        container + ':' + stage + '/deploy_worker.py'], check=True)
        payload = {'revision': revision, 'version': version, 'api_key': key,
                   'plugin_dir': os.environ.get('ASTRBOT_PLUGIN_DIR', '/AstrBot/data/plugins/astrbot_plugin_image_vote'),
                   'data_dir': os.environ.get('ASTRBOT_DATA_DIR', '/AstrBot/data'),
                   'base': os.environ.get('ASTRBOT_LOCAL_BASE', 'http://127.0.0.1:6185')}
        # A canceled Actions waiter does not kill the exec worker. It owns the
        # deployment lock, backup, reload and cleanup through completion.
        handed_off = True
        result = subprocess.run(['docker', 'exec', '-i', container, 'python3', '-u', stage + '/deploy_worker.py'],
                                input=json.dumps(payload), text=True)
        if result.returncode:
            raise RuntimeError('NAS deployment failed; see the worker summary above')
    finally:
        if not handed_off:
            subprocess.run(['docker', 'exec', container, 'python3', '-c',
                            'import shutil,sys;shutil.rmtree(sys.argv[1])', stage], check=False)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
