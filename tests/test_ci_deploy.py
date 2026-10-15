"""Isolated regression tests for tools/ci/deploy_worker.py.

Each test builds a throwaway Git history and a real SQLite ``vote.db`` under a
temporary directory, then drives ``deploy_worker.deploy`` directly.  The
AstrBot HTTP helper (or only its opener) is stubbed, so nothing here touches a
container, a real service or production state.
"""
import contextlib
import io
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.ci.deploy_worker as deploy_worker

PLUGIN = deploy_worker.PLUGIN
VERSION = "0.13.17"
API_KEY = "unit-test-api-key-9f1c2d7e"
BASE = "http://127.0.0.1:6185"

# Minimal vote.db subset the worker contract touches: the session status table
# it must inspect, plus the rows that stand for original image records and the
# historical votes that a deployment must preserve.
VOTE_DB_SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    display_title TEXT NOT NULL
);
CREATE TABLE votes (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    score INTEGER NOT NULL
);
"""


def run_git(cwd, *args):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError("git %s failed: %s" % (" ".join(args), result.stderr.strip()))
    return result.stdout.strip()


class FakeClock:
    """Deterministic stand-in for deploy_worker.time; the real clock never waits."""

    def __init__(self):
        self.readings = 0
        self.sleeps = []

    def monotonic(self):
        self.readings += 1
        return self.readings * 1000.0

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class FakeApi:
    """Records the AstrBot HTTP helper calls made by the worker."""

    def __init__(self, running_version):
        self.running_version = running_version
        self.calls = []

    def __call__(self, base, key, path, method="GET"):
        self.calls.append((base, key, path, method))
        if method == "POST":
            return None
        return {"name": PLUGIN, "activated": True, "version": self.running_version}


class DeployWorkerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage = self.root / "stage"
        self.source = self.root / "source"
        self.plugin = self.root / "plugin"
        self.data_root = self.root / "data"
        self.stage.mkdir()
        self._build_source_history()
        run_git(self.root, "clone", str(self.source), str(self.plugin))
        run_git(self.plugin, "config", "user.email", "nas@example.test")
        run_git(self.plugin, "config", "user.name", "NAS Test")
        run_git(self.source, "bundle", "create", str(self.stage / "source.bundle"), "HEAD")

    def _build_source_history(self):
        self.source.mkdir()
        run_git(self.source, "init")
        run_git(self.source, "config", "user.email", "ci@example.test")
        run_git(self.source, "config", "user.name", "CI Test")
        (self.source / "plugin.py").write_text('VERSION = "0.13.16"\n')
        run_git(self.source, "add", "-A")
        run_git(self.source, "commit", "-m", "previous release")
        self.old_revision = run_git(self.source, "rev-parse", "HEAD")
        (self.source / "plugin.py").write_text('VERSION = "0.13.17"\n')
        (self.source / "feature.py").write_text("# release feature\n")
        run_git(self.source, "add", "-A")
        run_git(self.source, "commit", "-m", "release 0.13.17")
        self.revision = run_git(self.source, "rev-parse", "HEAD")

    @property
    def plugin_data(self):
        return self.data_root / "plugin_data" / PLUGIN

    def _checkout_deployed(self, commit):
        run_git(self.plugin, "checkout", "-B", "deployed", commit)

    def _create_database(self, statuses=()):
        self.plugin_data.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.plugin_data / "vote.db") as connection:
            connection.executescript(VOTE_DB_SCHEMA)
            for index, status in enumerate(statuses):
                connection.execute("INSERT INTO sessions (id, status) VALUES (?, ?)", ("s%d" % index, status))
        return self.plugin_data

    def _write_config(self, content='{"group_id": "999"}\n'):
        config_directory = self.data_root / "config"
        config_directory.mkdir(parents=True, exist_ok=True)
        config = config_directory / (PLUGIN + "_config.json")
        config.write_text(content)
        return config

    def _payload(self, revision=None, version=VERSION, api_key=API_KEY):
        return {
            "revision": revision or self.revision,
            "version": version,
            "base": BASE,
            "plugin_dir": str(self.plugin),
            "data_dir": str(self.data_root),
            "api_key": api_key,
        }

    def _single_backup(self, data):
        backups = sorted(data.glob("backup-ci-*"))
        self.assertEqual(len(backups), 1)
        return backups[0]

    def _invoke(self, payload, api=None, patches=(), clock=None):
        clock = clock or FakeClock()
        output = io.StringIO()
        error = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(deploy_worker, "time", clock))
            if api is not None:
                stack.enter_context(mock.patch.object(deploy_worker, "api", api))
            for patch in patches:
                stack.enter_context(patch)
            with contextlib.redirect_stdout(output):
                try:
                    deploy_worker.deploy(payload, self.stage)
                except RuntimeError as exc:
                    error = exc
                except Exception as exc:
                    self.fail("deploy raised %s: %s\n--- output ---\n%s" % (type(exc).__name__, exc, output.getvalue()))
        return output.getvalue(), error

    def test_fast_forward_deploys_and_records_backup_and_version(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database()
        self._write_config()
        clock = FakeClock()
        api = FakeApi(VERSION)

        output, error = self._invoke(self._payload(), api=api, clock=clock)

        self.assertIsNone(error, output)
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(run_git(self.plugin, "status", "--porcelain"), "")
        self.assertIn("0.13.17", (self.plugin / "plugin.py").read_text())
        backup = self._single_backup(data)
        self.assertEqual((backup / "previous-commit").read_text().strip(), self.old_revision)
        self.assertTrue((backup / "vote.db").is_file())
        self.assertTrue((backup / "plugin_config.json").is_file())
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        for name in ("vote.db", "plugin_config.json", "previous-commit"):
            self.assertEqual(stat.S_IMODE((backup / name).stat().st_mode), 0o600)
        # The worker prints fully resolved paths (on macOS /var -> /private/var).
        self.assertIn("Backup: " + str(backup.resolve()), output)
        self.assertIn("Deploy: %s -> %s (%s)" % (self.old_revision, self.revision, VERSION), output)
        self.assertIn(
            "PASS: plugin enabled, reload acknowledged, running version=%s, commit=%s" % (VERSION, self.revision), output
        )
        self.assertNotIn("FAIL:", output)
        self.assertNotIn(API_KEY, output)
        self.assertEqual([call[3] for call in api.calls], ["GET", "POST", "GET"])
        self.assertEqual(api.calls[0][0], BASE)
        self.assertEqual(api.calls[1][2], "/api/v1/plugins/" + PLUGIN + "/reload")
        self.assertEqual(clock.sleeps, [])

    def test_backup_restricts_inherited_directory_permissions_before_writing(self):
        data = self._create_database()
        config = self._write_config()
        mkdir = Path.mkdir

        def inherited_mkdir(path, *args, **kwargs):
            mkdir(path, *args, **kwargs)
            if path.name.startswith('backup-ci-'):
                path.chmod(0o777)

        # Reproduce the NAS behavior: mkdir's mode is overridden by inherited
        # directory permissions. The explicit chmod must restore privacy.
        with mock.patch.object(Path, 'mkdir', autospec=True, side_effect=inherited_mkdir):
            saved = deploy_worker.backup(data, config, self.old_revision)
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o700)
        self.assertTrue((saved / 'vote.db').is_file())
        self.assertEqual(stat.S_IMODE((saved / 'plugin_config.json').stat().st_mode), 0o600)

    def test_active_vote_session_blocks_deployment(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database(statuses=("FINISHED", "RUNNING"))
        self._write_config()
        api = FakeApi(VERSION)

        output, error = self._invoke(self._payload(), api=api)

        self.assertIsNotNone(error)
        self.assertIn("Unfinished vote sessions exist", str(error))
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), self.old_revision)
        self.assertEqual(list(data.glob("backup-ci-*")), [])
        self.assertEqual(api.calls, [])
        self.assertNotIn("Backup:", output)

    def test_dirty_worktree_blocks_deployment(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database()
        self._write_config()
        (self.plugin / "plugin.py").write_text('VERSION = "0.13.16"\n# local edit\n')
        api = FakeApi(VERSION)

        output, error = self._invoke(self._payload(), api=api)

        self.assertIsNotNone(error)
        self.assertIn("working tree is dirty", str(error))
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), self.old_revision)
        self.assertEqual(list(data.glob("backup-ci-*")), [])
        self.assertEqual(api.calls, [])

    def test_checkout_ahead_of_actions_commit_rejects_rollback(self):
        self._checkout_deployed(self.revision)
        (self.plugin / "local.py").write_text("# follow-up commit not yet in CI\n")
        run_git(self.plugin, "add", "-A")
        run_git(self.plugin, "commit", "-m", "local follow-up")
        local_head = run_git(self.plugin, "rev-parse", "HEAD")
        data = self._create_database()
        self._write_config()
        api = FakeApi(VERSION)

        output, error = self._invoke(self._payload(), api=api)

        self.assertIsNotNone(error)
        self.assertIn("merge-base", str(error))
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), local_head)
        self.assertEqual(list(data.glob("backup-ci-*")), [])
        self.assertEqual([call[3] for call in api.calls], ["GET"])
        self.assertNotIn("PASS:", output)

    def test_diverged_checkout_is_rejected(self):
        self._checkout_deployed(self.old_revision)
        (self.plugin / "local.py").write_text("# local hotfix on the old base\n")
        run_git(self.plugin, "add", "-A")
        run_git(self.plugin, "commit", "-m", "local hotfix")
        local_head = run_git(self.plugin, "rev-parse", "HEAD")
        data = self._create_database()
        self._write_config()
        api = FakeApi(VERSION)

        output, error = self._invoke(self._payload(), api=api)

        self.assertIsNotNone(error)
        self.assertIn("merge-base", str(error))
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), local_head)
        self.assertEqual(list(data.glob("backup-ci-*")), [])
        self.assertEqual([call[3] for call in api.calls], ["GET"])
        self.assertNotIn("PASS:", output)

    def test_authentication_failure_stops_before_any_update(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database()
        self._write_config()
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(BASE + "/api/v1/plugins/" + PLUGIN, 401, "Unauthorized", None, None)
        patches = [mock.patch.object(deploy_worker.urllib.request, "build_opener", return_value=opener)]

        output, error = self._invoke(self._payload(), patches=patches)

        self.assertIsNotNone(error)
        self.assertIn("HTTP 401", str(error))
        self.assertEqual(opener.open.call_count, 1)
        headers = {name.lower(): value for name, value in opener.open.call_args.args[0].headers.items()}
        self.assertEqual(headers.get("x-api-key"), API_KEY)
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), self.old_revision)
        self.assertEqual(list(data.glob("backup-ci-*")), [])
        self.assertNotIn("Backup:", output)
        self.assertNotIn("Deploy:", output)
        self.assertNotIn(API_KEY, str(error))

    def test_running_version_mismatch_after_reload_never_reports_success(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database()
        self._write_config()
        clock = FakeClock()
        api = FakeApi("0.13.16")

        output, error = self._invoke(self._payload(), api=api, clock=clock)

        self.assertIsNotNone(error)
        self.assertIn("does not match " + VERSION, str(error))
        self.assertNotIn("PASS:", output)
        self.assertEqual([call[3] for call in api.calls], ["GET", "POST", "GET"])
        self.assertEqual(clock.sleeps, [])
        # The fast-forward already happened; the mismatch must surface instead of a fake success.
        self.assertEqual(run_git(self.plugin, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(len(list(data.glob("backup-ci-*"))), 1)

    def test_backup_keeps_original_image_records_and_vote_history(self):
        self._checkout_deployed(self.old_revision)
        data = self._create_database()
        connection = sqlite3.connect(data / "vote.db")
        with connection:
            connection.execute("INSERT INTO sessions (id, status) VALUES ('s1', 'FINISHED')")
            connection.execute(
                "INSERT INTO candidates (id, session_id, source_relative_path, display_title) VALUES "
                "('c1', 's1', 'group/original-a.png', 'A-1'), ('c2', 's1', 'group/original-b.png', 'A-2')"
            )
            connection.execute(
                "INSERT INTO votes (id, session_id, candidate_id, voter_id, score) VALUES "
                "(1, 's1', 'c1', 'u1', 3), (2, 's1', 'c2', 'u2', 1)"
            )
        connection.close()
        originals = self.data_root / "projects" / "group"
        originals.mkdir(parents=True)
        image_bytes = {}
        for name in ("original-a.png", "original-b.png"):
            image_bytes[name] = b"\x89PNG " + name.encode()
            (originals / name).write_bytes(image_bytes[name])
        config = self._write_config('{"input_root": "/AstrBot/data/projects"}\n')
        live_before = (data / "vote.db").read_bytes()

        output, error = self._invoke(self._payload(), api=FakeApi(VERSION))

        self.assertIsNone(error, output)
        self.assertEqual((data / "vote.db").read_bytes(), live_before)
        for name, expected in image_bytes.items():
            self.assertEqual((originals / name).read_bytes(), expected)
        backup = self._single_backup(data)
        with sqlite3.connect(backup / "vote.db") as backup_db:
            self.assertEqual(backup_db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                backup_db.execute("SELECT id, status FROM sessions ORDER BY id").fetchall(),
                [("s1", "FINISHED")],
            )
            self.assertEqual(
                backup_db.execute("SELECT id, source_relative_path FROM candidates ORDER BY id").fetchall(),
                [("c1", "group/original-a.png"), ("c2", "group/original-b.png")],
            )
            self.assertEqual(
                backup_db.execute("SELECT id, voter_id, score FROM votes ORDER BY id").fetchall(),
                [(1, "u1", 3), (2, "u2", 1)],
            )
        self.assertEqual((backup / "plugin_config.json").read_text(), config.read_text())


if __name__ == "__main__":
    unittest.main()
