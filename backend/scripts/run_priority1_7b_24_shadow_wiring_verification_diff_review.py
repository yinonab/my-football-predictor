#!/usr/bin/env python3
"""Priority 1.7B.24 — Shadow wiring verification and diff review."""

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

from core.shadow_wiring_verification_diff_review import (  # noqa: E402
    ALLOWED_CHANGED_FILES,
    run_shadow_wiring_verification_diff_review,
    write_p1724_markdown,
)

DEFAULT_JSON = ROOT / "reports" / "priority1_7b_24_shadow_wiring_verification_diff_review.json"
DEFAULT_MD = REPO / "docs" / "PRIORITY1_7B_24_SHADOW_WIRING_VERIFICATION_DIFF_REVIEW.md"


def _git_capture() -> tuple[str, str, str]:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    name_status = subprocess.run(
        ["git", "diff", "--name-status"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    stat = subprocess.run(
        ["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    return status, name_status, stat


def main() -> int:
    parser = argparse.ArgumentParser(description="P1.7B.24 shadow wiring verification")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--write-report", type=Path, default=DEFAULT_MD)
    parser.add_argument("--skip-pytest", action="store_true")
    args = parser.parse_args()

    git_before = _git_capture()
    print("Running P1.7B.24 shadow wiring verification (verification-only)...", flush=True)

    git_after = _git_capture()
    test_result: dict[str, Any] = {"skipped": True}
    if not args.skip_pytest:
        suites = [
            "tests/test_shadow_wiring_verification_diff_review.py",
            "tests/test_disabled_shadow_wiring_runtime.py",
            "tests/test_disabled_shadow_wiring_design.py",
            "tests/test_controlled_activation_plan_draft.py",
            "tests/test_final_activation_readiness_audit.py",
            "tests/test_activation_readiness_gate_context_audit.py",
            "tests/test_scoreline_ranking_topk_robustness_audit.py",
            "tests/test_wc2022_top5_robustness_blocker_decomposition.py",
            "tests/test_favorite_confidence_curve_prototype.py",
            "tests/test_favorite_confidence_curve_audit.py",
            "tests/test_favorite_spread_too_small_decomposition.py",
            "tests/test_validation_metrology_redesign.py",
            "tests/test_strength_based_xg_generator.py",
            "tests/test_backtest_metrics.py",
            "tests/test_probability_quality.py",
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
            "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
        }
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr)

    report = run_shadow_wiring_verification_diff_review(
        git_status_before=git_before[0],
        git_diff_name_status_before=git_before[1],
        git_diff_stat_before=git_before[2],
        git_status_after=git_after[0],
        git_diff_name_status_after=git_after[1],
        git_diff_stat_after=git_after[2],
    )
    report["tests_run"] = test_result

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    args.write_report.write_text(write_p1724_markdown(report), encoding="utf-8")

    print(f"Verification status: {report['verification_status']}")
    print(f"Commit readiness: {report['commit_readiness']['decision']}")
    print(f"API leak: {report['api_schema_leak_detected']}")

    print(f"Allowed files only: {len(ALLOWED_CHANGED_FILES)} paths documented")
    if not args.skip_pytest and test_result.get("exit_code", 0) != 0:
        return test_result["exit_code"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
