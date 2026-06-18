#!/usr/bin/env python3
"""Aggregate staging release readiness report (Phase 3E)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.activation_shift_explainer import load_large_shift_reviews
from core.release_readiness import (
    RELEASE_READY_FOR_STAGING,
    determine_release_status,
    format_release_readiness_markdown,
    production_defaults_disabled,
    run_activation_rollback_smoke,
    run_local_activation_enabled_smoke,
)
from scripts.check_activation_readiness import (
    determine_readiness,
    _check_defaults,
    _check_gate_documented,
    _check_phase2j_winner,
    _check_production_coverage,
    _check_sample_dry_run,
)
from scripts.local_enablement_checklist import (
    determine_local_enablement_recommendation,
    _run_qa_summary,
)

DEFAULT_REPORT = Path("reports/release_readiness_report.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Staging release readiness report.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _large_shifts_reviewed(large_pairs: list[tuple[str, str]]) -> bool:
    if not large_pairs:
        return True
    doc = load_large_shift_reviews()
    reviews = doc.get("reviews") or {}
    for home, away in large_pairs:
        entry = reviews.get(f"{home}|{away}")
        if not entry or entry.get("status") != "accepted":
            return False
    return True


def build_release_report() -> dict:
    defaults_ok, default_issues = production_defaults_disabled()
    readiness_defaults_ok, _ = _check_defaults()
    winner_ok, _ = _check_phase2j_winner()
    coverage_ok, coverage_msgs, _ = _check_production_coverage()
    gate_ok, _, gate_status = _check_gate_documented()
    sample_ok, sample_fallbacks, _ = _check_sample_dry_run()
    qa_summary, large_pairs = _run_qa_summary()
    readiness_status = determine_readiness(
        defaults_ok=readiness_defaults_ok,
        winner_ok=winner_ok,
        coverage_ok=coverage_ok,
        coverage_warnings=[m for m in coverage_msgs if "approximate" in m],
        gate_ok=gate_ok,
        sample_ok=sample_ok,
    )
    local_rec = determine_local_enablement_recommendation(
        defaults_ok=defaults_ok,
        qa_summary=qa_summary,
        large_pairs=large_pairs,
        large_shifts_reviewed=_large_shifts_reviewed(large_pairs),
        large_shifts_all_expected=True,
        readiness_status=readiness_status,
    )
    enabled_smoke = run_local_activation_enabled_smoke()
    rollback_smoke = run_activation_rollback_smoke()
    release_status = determine_release_status(
        defaults_ok=defaults_ok,
        readiness_status=readiness_status,
        local_enablement_recommendation=local_rec,
        qa_fallback_count=qa_summary.fallback_count,
        qa_large_shift_count=qa_summary.large_shift_count,
        large_shifts_reviewed=_large_shifts_reviewed(large_pairs),
        enabled_smoke_passed=enabled_smoke.passed,
        rollback_smoke_passed=rollback_smoke.passed,
    )

    return {
        "release_status": release_status,
        "defaults_ok": defaults_ok,
        "default_issues": default_issues,
        "readiness_status": readiness_status,
        "activation_gate_status": gate_status,
        "local_enablement_recommendation": local_rec,
        "qa_fallback_count": qa_summary.fallback_count,
        "qa_large_shift_count": qa_summary.large_shift_count,
        "qa_balanced_shift_count": qa_summary.balanced_shift_count,
        "qa_direction_reversal_count": qa_summary.direction_reversal_count,
        "large_shifts_reviewed": _large_shifts_reviewed(large_pairs),
        "large_shift_pairs": [f"{h} vs {a}" for h, a in large_pairs],
        "enabled_smoke_passed": enabled_smoke.passed,
        "rollback_smoke_passed": rollback_smoke.passed,
        "enabled_smoke": enabled_smoke.to_dict(),
        "rollback_smoke": rollback_smoke.to_dict(),
        "production_defaults": {
            "MODEL_ACTIVATION_ENABLED": config.MODEL_ACTIVATION_ENABLED,
            "POWER_CANDIDATE_AFFECTS_PREDICTION": config.POWER_CANDIDATE_AFFECTS_PREDICTION,
        },
        "sample_fallbacks": sample_fallbacks,
    }


def main() -> int:
    args = parse_args()
    report = build_release_report()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"release_status: {report['release_status']}")
        print(format_release_readiness_markdown(report))

    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(format_release_readiness_markdown(report), encoding="utf-8")
    print(f"\nWrote {args.markdown}")

    if report["release_status"] != RELEASE_READY_FOR_STAGING:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
