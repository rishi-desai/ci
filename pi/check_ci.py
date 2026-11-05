"""Fail closed unless the newest push run of the workflow on BRANCH tested this exact commit.

Usage: check_ci.py <sha> <branch> < runs.json   (GET .../actions/workflows/<file>/runs?head_sha=<sha>)

Ported from aurora's deploy/pi/check-ci.py. A pull_request run, a success for an older SHA, a
run on another branch, and an old success superseded by a failed rerun cannot approve a deploy.
Exit 3 means pending/failed/missing (not an error: the running version stays); any other
non-zero exit is an operational error that should reach the updater's OnFailure alert.
Stdlib only, Python 3.11+ (Debian 12's /usr/bin/python3).
"""

from __future__ import annotations

import json
import sys


def approved(payload: dict, sha: str, branch: str) -> bool:
    """True only if the latest matching push run for sha on branch completed successfully."""
    runs = [run for run in payload["workflow_runs"]
            if run.get("head_sha") == sha and run.get("head_branch") == branch
            and run.get("event") == "push"]
    if not runs:
        return False
    latest = max(runs, key=lambda run: (run["created_at"], run["id"]))
    return latest.get("status") == "completed" and latest.get("conclusion") == "success"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: check_ci.py <sha> <branch> < runs.json")
    if not approved(json.load(sys.stdin), sys.argv[1], sys.argv[2]):
        print(f"CI has not passed for {sys.argv[1][:7]} on {sys.argv[2]}; leaving the running version unchanged")
        sys.exit(3)
