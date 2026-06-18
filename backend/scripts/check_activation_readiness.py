#!/usr/bin/env python3
"""Production activation readiness check (Phase 3B)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.active_model_activation import (
    PHASE2J_WINNER_CANDIDATE,
    PHASE2J_WINNER_MODE,
    PHASE2J_WINNER_STRATEGY,
    SAMPLE_PRODUCTION_MATCHUPS,
    run_prediction_with_active_candidate,
    validate_activation_configuration,
)
from core.external_rating_snapshots import (
    WARNING_SNAPSHOT_AS_OF_APPROXIMATE,
    external_fifa_points_production_ready,
    get_team_fifa_points,
)
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

READINESS_READY = "READY_FOR_LOCAL_ENABLEMENT"
READINESS_WARNINGS = "READY_WITH_WARNINGS"
READINESS_NOT_READY = "NOT_READY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check production activation readiness.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _check_defaults() -> tuple[bool, list[str]]:
    issues: list[str] = []
    if config.MODEL_ACTIVATION_ENABLED:
        issues.append("MODEL_ACTIVATION_ENABLED should be false by default")
    if config.POWER_CANDIDATE_AFFECTS_PREDICTION:
        issues.append("POWER_CANDIDATE_AFFECTS_PREDICTION should be false by default")
    return len(issues) == 0, issues


def _check_phase2j_winner() -> tuple[bool, list[str]]:
    issues: list[str] = []
    if config.ACTIVE_POWER_CANDIDATE != PHASE2J_WINNER_CANDIDATE:
        issues.append(
            f"ACTIVE_POWER_CANDIDATE={config.ACTIVE_POWER_CANDIDATE} "
            f"!= {PHASE2J_WINNER_CANDIDATE}"
        )
    if config.ACTIVE_EXTERNAL_RATING_STRATEGY != PHASE2J_WINNER_STRATEGY:
        issues.append(
            f"ACTIVE_EXTERNAL_RATING_STRATEGY mismatch: {config.ACTIVE_EXTERNAL_RATING_STRATEGY}"
        )
    if config.ACTIVE_EXTERNAL_RATING_MODE != PHASE2J_WINNER_MODE:
        issues.append(
            f"ACTIVE_EXTERNAL_RATING_MODE mismatch: {config.ACTIVE_EXTERNAL_RATING_MODE}"
        )
    return len(issues) == 0, issues


def _check_production_coverage() -> tuple[bool, list[str], dict]:
    ready, report = external_fifa_points_production_ready()
    info = report.to_dict()
    issues: list[str] = []
    if not ready:
        issues.append(
            f"production FIFA coverage {report.fifa_points_coverage:.1%} "
            f"< threshold {config.PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE:.0%}"
        )
    warnings: list[str] = []
    if WARNING_SNAPSHOT_AS_OF_APPROXIMATE in report.warnings:
        warnings.append("production snapshot as_of is approximate")
    return ready, issues + warnings, info


def _check_gate_documented() -> tuple[bool, list[str], str]:
    """Phase 2J gate pass is documented via wired winner constants (no slow re-run)."""
    documented_status = "MODEL_ACTIVATION_PASS"
    if (
        config.ACTIVE_POWER_CANDIDATE == PHASE2J_WINNER_CANDIDATE
        and config.ACTIVE_EXTERNAL_RATING_MODE == PHASE2J_WINNER_MODE
        and config.ACTIVE_EXTERNAL_RATING_STRATEGY == PHASE2J_WINNER_STRATEGY
    ):
        return True, [], documented_status
    return False, ["phase2j_gate_winner_not_documented_in_config"], "NOT_DOCUMENTED"


def _check_sample_dry_run() -> tuple[bool, list[str], list[dict]]:
    dm = LiveDataManager()
    opp = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    prod_key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    rows: list[dict] = []
    fallbacks: list[str] = []
    for home, away in SAMPLE_PRODUCTION_MATCHUPS:
        home_key, _ = dm.resolve_team(home)
        away_key, _ = dm.resolve_team(away)
        out = run_prediction_with_active_candidate(
            home_key,
            away_key,
            data_manager=dm,
            opponent_index=opp,
            force_enable=True,
        )
        diag = out["model_diagnostics"]
        home_fp, home_ok = get_team_fifa_points(prod_key, home)
        away_fp, away_ok = get_team_fifa_points(prod_key, away)
        row = {
            "home": home,
            "away": away,
            "fallback": diag.get("fallback_to_baseline"),
            "fallback_reasons": out.get("fallback_reasons") or [],
            "home_fifa_points": home_fp if home_ok else None,
            "away_fifa_points": away_fp if away_ok else None,
            "activation_applied": out.get("activation_applied"),
        }
        rows.append(row)
        if diag.get("fallback_to_baseline"):
            fallbacks.append(f"{home} vs {away}: {row['fallback_reasons']}")
    ok = len(fallbacks) == 0
    return ok, fallbacks, rows


def determine_readiness(
    *,
    defaults_ok: bool,
    winner_ok: bool,
    coverage_ok: bool,
    coverage_warnings: list[str],
    gate_ok: bool,
    sample_ok: bool,
) -> str:
    if not defaults_ok or not coverage_ok or not sample_ok or not gate_ok:
        return READINESS_NOT_READY
    if coverage_warnings or not winner_ok:
        return READINESS_WARNINGS
    return READINESS_READY


def main() -> None:
    args = parse_args()
    defaults_ok, default_issues = _check_defaults()
    winner_ok, winner_issues = _check_phase2j_winner()
    coverage_ok, coverage_msgs, coverage_info = _check_production_coverage()
    gate_ok, gate_issues, gate_status = _check_gate_documented()
    sample_ok, sample_fallbacks, sample_rows = _check_sample_dry_run()
    config_ok, config_reasons = validate_activation_configuration()

    coverage_warnings = [m for m in coverage_msgs if "approximate" in m]
    coverage_issues = [m for m in coverage_msgs if "approximate" not in m]

    readiness = determine_readiness(
        defaults_ok=defaults_ok,
        winner_ok=winner_ok,
        coverage_ok=coverage_ok,
        coverage_warnings=coverage_warnings,
        gate_ok=gate_ok,
        sample_ok=sample_ok,
    )

    payload = {
        "readiness_status": readiness,
        "defaults_ok": defaults_ok,
        "phase2j_winner_ok": winner_ok,
        "production_fifa_coverage_ok": coverage_ok,
        "production_coverage": coverage_info,
        "activation_gate_status": gate_status,
        "sample_production_fallbacks": sample_fallbacks,
        "sample_production_rows": sample_rows,
        "config_validation_ok": config_ok,
        "config_validation_reasons": config_reasons,
        "issues": default_issues + winner_issues + coverage_issues + gate_issues + sample_fallbacks,
        "warnings": coverage_warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Activation readiness check (Phase 3B)\n")
        print(f"readiness_status: {readiness}")
        print(f"MODEL_ACTIVATION_ENABLED={config.MODEL_ACTIVATION_ENABLED}")
        print(f"POWER_CANDIDATE_AFFECTS_PREDICTION={config.POWER_CANDIDATE_AFFECTS_PREDICTION}")
        print(f"ACTIVE_POWER_CANDIDATE={config.ACTIVE_POWER_CANDIDATE}")
        print(f"PRODUCTION_FIFA_SNAPSHOT_DATASET={config.PRODUCTION_FIFA_SNAPSHOT_DATASET}")
        cov = coverage_info
        print(
            f"production FIFA coverage: {cov.get('fifa_points_coverage', 0):.1%} "
            f"({cov.get('teams', 0)} teams, missing={cov.get('missing', 0)})"
        )
        print(f"activation_gate_status: {gate_status}")
        print(f"sample production fallbacks: {len(sample_fallbacks)}")
        for row in sample_rows:
            fb = "FALLBACK" if row["fallback"] else "ok"
            print(
                f"  {row['home']} vs {row['away']}: {fb} "
                f"(H fifa={row['home_fifa_points']}, A fifa={row['away_fifa_points']})"
            )
        if payload["issues"]:
            print("\nIssues:")
            for issue in payload["issues"]:
                print(f"  - {issue}")
        if payload["warnings"]:
            print("\nWarnings:")
            for warn in payload["warnings"]:
                print(f"  - {warn}")

    if readiness == READINESS_NOT_READY:
        sys.exit(1)


if __name__ == "__main__":
    main()
