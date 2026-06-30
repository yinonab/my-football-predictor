#!/usr/bin/env python3
"""Priority 1.7B.25 — Commit scope and release safety review (review-only)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.commit_scope_release_safety_review import (  # noqa: E402
    ALLOWED_CHANGED_FILES,
    run_commit_scope_release_safety_review,
    write_p1725_markdown,
)

DEFAULT_JSON = ROOT / "reports" / "priority1_7b_25_commit_scope_release_safety_review.json"
DEFAULT_MD = REPO / "docs" / "PRIORITY1_7B_25_COMMIT_SCOPE_RELEASE_SAFETY_REVIEW.md"


def _git_readonly(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="P1.7B.25 commit scope review")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--write-report", type=Path, default=DEFAULT_MD)
    parser.add_argument("--skip-pytest", action="store_true")
    args = parser.parse_args()

    git_before = (
        _git_readonly("status", "--short"),
        _git_readonly("diff", "--name-status"),
        _git_readonly("diff", "--stat"),
    )
    print("Running P1.7B.25 commit scope review (review-only)...", flush=True)

    test_result: dict = {"skipped": True}
    if not args.skip_pytest:
        suites = [
            "tests/test_commit_scope_release_safety_review.py",
            "tests/test_shadow_wiring_verification_diff_review.py",
            "tests/test_disabled_shadow_wiring_runtime.py",
            "tests/test_disabled_shadow_wiring_design.py",
            "tests/test_controlled_activation_plan_draft.py",
            "tests/test_final_activation_readiness_audit.py",
            "tests/test_activation_readiness_gate_context_audit.py",
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *suites, "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        test_result = {
            "skipped": False,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "suites": suites,
            "stdout_tail": proc.stdout[-1500:] if proc.stdout else "",
        }
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr)

    git_after = (
        _git_readonly("status", "--short"),
        _git_readonly("diff", "--name-status"),
        _git_readonly("diff", "--stat"),
    )

    report = run_commit_scope_release_safety_review(
        git_status=git_before[0],
        git_diff_name_status=git_before[1],
        git_diff_stat=git_before[2],
        git_status_after=git_after[0],
        git_diff_name_status_after=git_after[1],
        git_diff_stat_after=git_after[2],
    )
    report["tests_run"] = test_result

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    args.write_report.write_text(write_p1725_markdown(report), encoding="utf-8")

    print(f"Review status: {report['review_status']}")
    print(f"Commit readiness: {report['commit_readiness_decision']}")
    print(f"Commit recommended now: {report['commit_recommended_now']}")

    if not args.skip_pytest and test_result.get("exit_code", 0) != 0:
        return test_result["exit_code"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
