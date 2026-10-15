"""Run inside the existing AstrBot container; never restart the bot container."""
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


PLUGIN = 'astrbot_plugin_image_vote'
ACTIVE = ('PREPARING', 'RUNNING', 'PAUSED', 'FINALIZING')


def git(root, *args):
    result = subprocess.run(['git', '-c', 'safe.directory=' + str(root), '-C', str(root), *args],
                            capture_output=True, text=True)
    if result.returncode:
        # Git diagnostics may include credential-bearing remote URLs.
        raise RuntimeError('Git operation failed: ' + args[0])
    return result.stdout.strip()


@contextmanager
def deployment_lock(data):
    data.mkdir(parents=True, exist_ok=True)
    with (data / 'ci-deploy.lock').open('a') as lock:
        deadline = time.monotonic() + 120
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another plugin deployment is still running')
                time.sleep(2)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def ensure_idle(database):
    if not database.is_file():
        raise RuntimeError('Expected existing vote.db; verify ASTRBOT_DATA_DIR before deploying')
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        active = db.execute('SELECT COUNT(*) FROM sessions WHERE status IN (?,?,?,?)', ACTIVE).fetchone()[0]
    if active:
        raise RuntimeError('Unfinished vote sessions exist; finish or cancel them, then rerun deployment')


def backup(data, config, old_revision):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = data / ('backup-ci-' + stamp)
    target.mkdir(mode=0o700)
    with sqlite3.connect((data / 'vote.db').resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(target / 'vote.db') as dst:
            src.backup(dst)
    shutil.copyfile(config, target / 'plugin_config.json')
    (target / 'previous-commit').write_text(old_revision + '\n')
    for path in target.iterdir():
        path.chmod(0o600)
    return target


def api(base, key, path, method='GET'):
    request = urllib.request.Request(base + path, data=b'{}' if method == 'POST' else None,
                                     headers={'X-API-Key': key, 'Content-Type': 'application/json'}, method=method)
    try:
        # Never follow a redirect with the API key to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(request, timeout=90) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError('AstrBot API HTTP %d (%s)' % (exc.code, path)) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RuntimeError('AstrBot API unavailable or returned invalid JSON') from None
    if payload.get('status') != 'ok':
        raise RuntimeError('AstrBot API rejected ' + path)
    return payload.get('data')


def verify_plugin(detail, version=None):
    if not isinstance(detail, dict) or detail.get('name') != PLUGIN or detail.get('activated') is not True:
        raise RuntimeError('Plugin is missing or disabled; refusing to claim successful deployment')
    if version is not None and str(detail.get('version')) != version:
        raise RuntimeError('Running plugin version does not match ' + version)


def deploy(payload, stage):
    revision, version = payload['revision'], payload['version']
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', version):
        raise RuntimeError('Invalid revision or version')
    base = payload['base'].rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.query or parsed.fragment:
        raise RuntimeError('ASTRBOT_LOCAL_BASE must be the container loopback HTTP address')
    root = Path(payload['plugin_dir']).resolve()
    data_root = Path(payload['data_dir']).resolve()
    data = data_root / 'plugin_data' / PLUGIN
    key = payload.pop('api_key')
    path = '/api/v1/plugins/' + PLUGIN
    with deployment_lock(data):
        if git(root, 'status', '--porcelain'):
            raise RuntimeError('NAS plugin working tree is dirty; preserving changes')
        ensure_idle(data / 'vote.db')
        verify_plugin(api(base, key, path))
        old_revision = git(root, 'rev-parse', 'HEAD')
        git(root, 'fetch', str(stage / 'source.bundle'), 'HEAD')
        if git(root, 'rev-parse', 'FETCH_HEAD') != revision:
            raise RuntimeError('Bundle does not match the verified Actions commit')
        # Refuse divergent history, stale deployments and source rollback.
        git(root, 'merge-base', '--is-ancestor', old_revision, revision)
        saved = backup(data, data_root / 'config' / (PLUGIN + '_config.json'), old_revision)
        print('Backup: ' + str(saved), flush=True)
        print('Deploy: ' + old_revision + ' -> ' + revision + ' (' + version + ')', flush=True)
        ensure_idle(data / 'vote.db')
        git(root, 'merge', '--ff-only', revision)
        if git(root, 'rev-parse', 'HEAD') != revision:
            raise RuntimeError('NAS HEAD does not match the deployment commit')
        # A positive response is required; checking the already-installed version
        # alone could mistake an old process for a successful reload.
        ensure_idle(data / 'vote.db')
        api(base, key, path + '/reload', method='POST')
        deadline = time.monotonic() + 60
        while True:
            try:
                verify_plugin(api(base, key, path), version)
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        if git(root, 'status', '--porcelain'):
            raise RuntimeError('NAS working tree changed during deployment; inspect before retrying')
        record = {'commit': revision, 'version': version, 'previous_commit': old_revision,
                  'backup': str(saved), 'verified_at': datetime.now(timezone.utc).isoformat()}
        temporary = data / 'ci-deployment.json.tmp'
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(data / 'ci-deployment.json')
        print('PASS: plugin enabled, reload acknowledged, running version=' + version + ', commit=' + revision, flush=True)
        print('No automatic database rollback. Backup retained: ' + str(saved), flush=True)


if __name__ == '__main__':
    stage = Path(__file__).resolve().parent
    try:
        deploy(json.load(sys.stdin), stage)
    except Exception as exc:
        # Do not dump response bodies, config, API key or entire tracebacks.
        print('FAIL: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), flush=True)
        sys.exit(1)
    finally:
        if stage.name.startswith('lirating-ci-'):
            shutil.rmtree(stage)
