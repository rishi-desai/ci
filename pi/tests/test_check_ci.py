"""check_ci.approved: only the newest push run on the branch for the exact SHA can approve."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_ci import approved  # noqa: E402

SHA = "a" * 40


def run(run_id: int, created: str, conclusion: str | None = "success", status: str = "completed",
        sha: str = SHA, branch: str = "main", event: str = "push") -> dict:
    """One workflow run as GitHub's API returns it (only the fields check_ci reads)."""
    return {"id": run_id, "created_at": created, "status": status, "conclusion": conclusion,
            "head_sha": sha, "head_branch": branch, "event": event}


class ApprovedTest(unittest.TestCase):
    def check(self, *runs: dict) -> bool:
        return approved({"workflow_runs": list(runs)}, SHA, "main")

    def test_success_on_exact_sha_approves(self) -> None:
        self.assertTrue(self.check(run(1, "2026-11-05T01:00:00Z")))

    def test_no_runs_rejects(self) -> None:
        self.assertFalse(self.check())

    def test_in_progress_rejects(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z", conclusion=None, status="in_progress")))

    def test_failure_rejects(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z", conclusion="failure")))

    def test_failed_rerun_supersedes_older_success(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z"),
                                    run(2, "2026-11-05T02:00:00Z", conclusion="failure")))

    def test_pull_request_run_cannot_approve(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z", event="pull_request")))

    def test_other_branch_cannot_approve(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z", branch="feature")))

    def test_success_for_other_sha_cannot_approve(self) -> None:
        self.assertFalse(self.check(run(1, "2026-11-05T01:00:00Z", sha="b" * 40)))


if __name__ == "__main__":
    unittest.main()
