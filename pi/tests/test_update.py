"""ci-gated-update end to end against real git, with fake gh/sudo/systemctl on PATH.

Each test builds a bare "origin", a checkout of it (the app on the Pi), and a config. The fake
gh prints whatever runs JSON the test wrote; fake sudo/systemctl record their arguments. Needs
flock (util-linux), so it runs on Linux CI and skips on a stock Mac.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

UPDATER = Path(__file__).resolve().parents[1] / "ci-gated-update"

FAKES = {
    # Ignores its arguments except for logging them, and prints the test's runs payload.
    "gh": 'echo "$*" >> "$FAKE_LOG"; cat "$FAKE_RUNS"',
    # `sudo -n -l ...` (permission probe) succeeds; `sudo -n cmd...` runs cmd.
    "sudo": '[ "$1" = -n ] && shift; [ "$1" = -l ] && exit 0; exec "$@"',
    "systemctl": 'echo "systemctl $*" >> "$FAKE_LOG"',
}


def git(cwd: Path, *args: str) -> str:
    """Run git in cwd and return stripped stdout."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("flock"), "flock not installed (Linux CI runs these)")
class UpdaterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.origin = self.tmp / "origin.git"
        self.app = self.tmp / "app"
        self.log = self.tmp / "calls.log"
        self.runs = self.tmp / "runs.json"
        self.log.touch()
        self.set_runs([])

        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in FAKES.items():
            path = bin_dir / name
            path.write_text(f"#!/usr/bin/env bash\n{body}\n")
            path.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_LOG": str(self.log), "FAKE_RUNS": str(self.runs),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update({k: self.env[k] for k in self.env if k.startswith("GIT_")})

        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = self.tmp / "seed"
        git(self.tmp, "clone", "-q", str(self.origin), str(seed))
        # build.sh logs which commit it built; health.sh fails while a file named `unhealthy` exists.
        (seed / ".gitignore").write_text("data/\n")
        (seed / "build.sh").write_text('#!/usr/bin/env bash\ngit rev-parse HEAD >> data/builds.log\n')
        (seed / "health.sh").write_text("#!/usr/bin/env bash\ntest ! -e unhealthy\n")
        for script in ("build.sh", "health.sh"):
            (seed / script).chmod(0o755)
        git(seed, "add", ".")
        git(seed, "commit", "-qm", "initial")
        git(seed, "push", "-q", "origin", "main")
        self.seed = seed
        git(self.tmp, "clone", "-q", str(self.origin), str(self.app))

        self.conf = self.tmp / "app.conf"
        self.conf.write_text(textwrap.dedent(f"""\
            APP_NAME=app
            APP_DIR={self.app}
            BUILD_CMD=./build.sh
            RESTART_UNIT=app
            HEALTH_CMD=./health.sh
            HEALTH_TRIES=1
            HEALTH_DELAY=0
            """))
        self.conf.chmod(0o644)

    def set_runs(self, runs: list[dict]) -> None:
        self.runs.write_text(json.dumps({"workflow_runs": runs}))

    def passing_run(self, sha: str) -> dict:
        return {"id": 1, "created_at": "2026-11-05T01:00:00Z", "status": "completed",
                "conclusion": "success", "head_sha": sha, "head_branch": "main", "event": "push"}

    def push_commit(self, filename: str = "feature.txt") -> str:
        """Commit a new file upstream and return the new origin/main SHA."""
        (self.seed / filename).write_text(filename)
        git(self.seed, "add", filename)
        git(self.seed, "commit", "-qm", f"add {filename}")
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def update(self) -> subprocess.CompletedProcess:
        return subprocess.run([str(UPDATER), str(self.conf)], env=self.env, capture_output=True, text=True)

    def head(self) -> str:
        return git(self.app, "rev-parse", "HEAD")

    def builds(self) -> list[str]:
        path = self.app / "data" / "builds.log"
        return path.read_text().split() if path.exists() else []

    def test_no_new_commit_is_a_quiet_noop(self) -> None:
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.builds(), [])

    def test_pending_ci_leaves_the_running_version(self) -> None:
        old = self.head()
        new = self.push_commit()
        self.set_runs([{**self.passing_run(new), "status": "in_progress", "conclusion": None}])
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), old)
        self.assertIn("CI has not passed", result.stdout)

    def test_success_for_another_sha_does_not_deploy(self) -> None:
        old = self.head()
        self.push_commit()
        self.set_runs([self.passing_run(old)])
        self.assertEqual(self.update().returncode, 0)
        self.assertEqual(self.head(), old)

    def test_passing_ci_deploys_builds_and_restarts(self) -> None:
        new = self.push_commit()
        self.set_runs([self.passing_run(new)])
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), new)
        self.assertEqual(self.builds(), [new])
        calls = self.log.read_text()
        self.assertIn("systemctl restart app", calls)
        self.assertIn(f"actions/workflows/ci.yml/runs?head_sha={new}&event=push", calls)

    def test_unhealthy_commit_rolls_back_and_is_never_retried(self) -> None:
        old = self.head()
        bad = self.push_commit("unhealthy")
        self.set_runs([self.passing_run(bad)])
        result = self.update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.head(), old)
        self.assertEqual(self.builds(), [bad, old])
        self.assertEqual((self.app / "data" / ".update-failed").read_text().strip(), bad)

        retry = self.update()
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(self.builds(), [bad, old])

    def test_dirty_checkout_is_skipped(self) -> None:
        old = self.head()
        new = self.push_commit()
        self.set_runs([self.passing_run(new)])
        (self.app / "build.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        result = self.update()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.head(), old)
        self.assertIn("uncommitted edits", result.stdout)

    def test_group_writable_config_is_refused(self) -> None:
        self.conf.chmod(self.conf.stat().st_mode | stat.S_IWGRP)
        result = self.update()
        self.assertEqual(result.returncode, 1)
        self.assertIn("writable", result.stdout)


if __name__ == "__main__":
    unittest.main()
