#!/usr/bin/env python3
"""Controlled local/staging enablement checklist (Phase 3D)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.activation_qa import (
    WARNING_LARGE_CANDIDATE_SHIFT,
    analyze_prediction_result,
    load_activation_qa_matchups,
    summarize_qa_analyses,
)
from core.activation_shift_explainer import (
    EXPLANATION_EXPECTED_CORRECTION,
    all_large_shifts_reviewed,
    load_large_shift_reviews,
)
from core.active_model_activation import run_prediction_with_active_candidate
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager
from scripts.check_activation_readiness import (
    READINESS_NOT_READY,
    READINESS_READY,
    READINESS_WARNINGS,
    determine_readiness,
    _check_defaults,
    _check_gate_documented,
    _check_phase2j_winner,
    _check_production_coverage,
    _check_sample_dry_run,
)

HOLD = "HOLD"
PROCEED_TO_LOCAL_ENABLEMENT = "PROCEED_TO_LOCAL_ENABLEMENT"
PROCEED_TO_STAGING_WITH_APPROVAL = "PROCEED_TO_STAGING_WITH_APPROVAL"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local enablement checklist.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _run_qa_summary() -> tuple[object, list[tuple[str, str]]]:
    matchups, skipped = load_activation_qa_matchups()
    dm = LiveDataManager()
    opp = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    analyses = []
    large_pairs: list[tuple[str, str]] = []
    for matchup in matchups:
        home_key, _ = dm.resolve_team(matchup.home)
        away_key, _ = dm.resolve_team(matchup.away)
        out = run_prediction_with_active_candidate(
            home_key,
            away_key,
            data_manager=dm,
            opponent_index=opp,
            force_enable=True,
        )
        row = analyze_prediction_result(matchup, out)
        analyses.append(row)
        if (
            row.shift_class == "large_shift"
            or WARNING_LARGE_CANDIDATE_SHIFT in row.warnings
        ):
            large_pairs.append((matchup.home, matchup.away))
    return summarize_qa_analyses(analyses, skipped=skipped), large_pairs


def determine_local_enablement_recommendation(
    *,
    defaults_ok: bool,
    qa_summary: object,
    large_pairs: list[tuple[str, str]],
    large_shifts_reviewed: bool,
    large_shifts_all_expected: bool,
    readiness_status: str,
) -> str:
    if not defaults_ok:
        return HOLD
    if qa_summary.fallback_count > 0:
        return HOLD
    if qa_summary.balanced_shift_count > 0 or qa_summary.direction_reversal_count > 0:
        return HOLD
    if readiness_status == READINESS_NOT_READY:
        return HOLD
    if large_pairs and not large_shifts_reviewed:
        return HOLD
    if large_pairs and not large_shifts_all_expected:
        return PROCEED_TO_STAGING_WITH_APPROVAL
    if readiness_status in (READINESS_READY, READINESS_WARNINGS):
        return PROCEED_TO_LOCAL_ENABLEMENT
    return HOLD


def main() -> int:
    args = parse_args()
    defaults_ok, default_issues = _check_defaults()
    winner_ok, winner_issues = _check_phase2j_winner()
    coverage_ok, coverage_msgs, coverage_info = _check_production_coverage()
    gate_ok, gate_issues, gate_status = _check_gate_documented()
    sample_ok, sample_fallbacks, _ = _check_sample_dry_run()
    qa_summary, large_pairs = _run_qa_summary()
    reviews_doc = load_large_shift_reviews()
    reviewed_ok, missing_reviews = all_large_shifts_reviewed(large_pairs)
    large_all_expected = True
    for home, away in large_pairs:
        entry = (reviews_doc.get("reviews") or {}).get(f"{home}|{away}")
        if not entry or entry.get("explainability") != EXPLANATION_EXPECTED_CORRECTION:
            large_all_expected = False
            break

    readiness = determine_readiness(
        defaults_ok=defaults_ok,
        winner_ok=winner_ok,
        coverage_ok=coverage_ok,
        coverage_warnings=[m for m in coverage_msgs if "approximate" in m],
        gate_ok=gate_ok,
        sample_ok=sample_ok,
    )
    recommendation = determine_local_enablement_recommendation(
        defaults_ok=defaults_ok,
        qa_summary=qa_summary,
        large_pairs=large_pairs,
        large_shifts_reviewed=reviewed_ok,
        large_shifts_all_expected=large_all_expected,
        readiness_status=readiness,
    )

    payload = {
        "local_enablement_recommendation": recommendation,
        "readiness_status": readiness,
        "defaults_ok": defaults_ok,
        "qa_fallback_count": qa_summary.fallback_count,
        "qa_balanced_shift_count": qa_summary.balanced_shift_count,
        "qa_direction_reversal_count": qa_summary.direction_reversal_count,
        "qa_large_shift_count": qa_summary.large_shift_count,
        "large_shift_pairs": [f"{h} vs {a}" for h, a in large_pairs],
        "large_shifts_reviewed": reviewed_ok,
        "missing_shift_reviews": missing_reviews,
        "production_fifa_coverage_ok": coverage_ok,
        "issues": default_issues + winner_issues + gate_issues + sample_fallbacks,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Local enablement checklist (Phase 3D)\n")
        print(f"local_enablement_recommendation: {recommendation}")
        print(f"readiness_status: {readiness}")
        print(f"MODEL_ACTIVATION_ENABLED={config.MODEL_ACTIVATION_ENABLED}")
        print(f"POWER_CANDIDATE_AFFECTS_PREDICTION={config.POWER_CANDIDATE_AFFECTS_PREDICTION}")
        print("\nChecks:")
        print(f"  tests: run `python -m pytest tests/ -q`")
        print(f"  QA fallbacks: {qa_summary.fallback_count} (need 0)")
        print(f"  QA balanced shifts: {qa_summary.balanced_shift_count} (need 0)")
        print(f"  QA direction reversals: {qa_summary.direction_reversal_count} (need 0)")
        print(f"  large shifts reviewed: {reviewed_ok} ({len(large_pairs)} found)")
        if missing_reviews:
            print(f"  missing reviews: {', '.join(missing_reviews)}")
        print(f"  production FIFA coverage: {coverage_info.get('fifa_points_coverage', 0):.0%}")
        print("\nRollback (immediate):")
        print("  MODEL_ACTIVATION_ENABLED=false")
        print("  POWER_CANDIDATE_AFFECTS_PREDICTION=false")
        print("\nLocal/staging enable only (not production defaults):")
        print("  MODEL_ACTIVATION_ENABLED=true")
        print("  POWER_CANDIDATE_AFFECTS_PREDICTION=true")
        print("  Production requires explicit approval.")

    if recommendation == HOLD:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
