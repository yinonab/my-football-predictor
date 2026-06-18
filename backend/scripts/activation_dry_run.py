#!/usr/bin/env python3
"""Activation dry-run — baseline vs active candidate (Phase 3A/3B)."""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.active_model_activation import (
    DRY_RUN_MATCHUPS,
    SAMPLE_PRODUCTION_MATCHUPS,
    run_prediction_with_active_candidate,
)
from core.external_rating_snapshots import get_team_fifa_points, list_production_team_names
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baseline vs active candidate dry-run.")
    parser.add_argument(
        "--enable-candidate",
        action="store_true",
        help="Simulate activation (does not change config files)",
    )
    parser.add_argument(
        "--sample-production",
        action="store_true",
        help="Run standard 8-match WC 2026 production sample",
    )
    parser.add_argument(
        "--all-production-pairs",
        action="store_true",
        help="Run all unique pairs from 48 production teams (slow)",
    )
    parser.add_argument(
        "--only-fallbacks",
        action="store_true",
        help="Print only rows that fall back to baseline",
    )
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args()


def _select_matchups(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.all_production_pairs:
        teams = list_production_team_names()
        return list(itertools.combinations(teams, 2))
    if args.sample_production:
        return list(SAMPLE_PRODUCTION_MATCHUPS)
    return list(DRY_RUN_MATCHUPS)


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    matchups = _select_matchups(args)
    prod_key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET

    header = (
        "home | away | baseline_H | active_H | delta_H | fallback | fallback_reasons | "
        "home_fifa_points | away_fifa_points | model_version"
    )
    print("Activation dry-run\n")
    print(header)
    print("-" * len(header))

    rows: list[dict[str, str | float | bool | None]] = []
    fallback_count = 0
    for home, away in matchups:
        home_key, _ = dm.resolve_team(home)
        away_key, _ = dm.resolve_team(away)
        out = run_prediction_with_active_candidate(
            home_key,
            away_key,
            data_manager=dm,
            opponent_index=opp_idx,
            force_enable=args.enable_candidate,
        )
        base = out["baseline"]["probabilities_1x2"]
        active = out["active"]["probabilities_1x2"]
        delta_h = round(active["home_win"] - base["home_win"], 2)
        diag = out["model_diagnostics"]
        fallback = bool(diag.get("fallback_to_baseline"))
        if fallback:
            fallback_count += 1
        reasons = ",".join(out.get("fallback_reasons") or []) or "-"
        home_fp, home_ok = get_team_fifa_points(prod_key, home)
        away_fp, away_ok = get_team_fifa_points(prod_key, away)
        home_fp_disp = f"{home_fp:.0f}" if home_ok and home_fp is not None else "-"
        away_fp_disp = f"{away_fp:.0f}" if away_ok and away_fp is not None else "-"
        row = {
            "home": home,
            "away": away,
            "baseline_H": base["home_win"],
            "active_H": active["home_win"],
            "delta_H": delta_h,
            "fallback": fallback,
            "fallback_reasons": reasons,
            "home_fifa_points": home_fp if home_ok else None,
            "away_fifa_points": away_fp if away_ok else None,
            "model_version": diag["model_version"],
        }
        rows.append(row)
        if args.only_fallbacks and not fallback:
            continue
        line = (
            f"{home} | {away} | {base['home_win']:5.1f} | {active['home_win']:5.1f} | "
            f"{delta_h:+5.1f} | {fallback} | {reasons} | {home_fp_disp} | {away_fp_disp} | "
            f"{diag['model_version']}"
        )
        print(line)

    if args.csv and rows:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {args.csv}")

    mode = "enabled (simulated)" if args.enable_candidate else "disabled (default)"
    print(f"\nActivation mode: {mode}")
    print(f"matchups: {len(matchups)} | fallbacks: {fallback_count}")
    print(f"MODEL_ACTIVATION_ENABLED={config.MODEL_ACTIVATION_ENABLED}")
    print(f"POWER_CANDIDATE_AFFECTS_PREDICTION={config.POWER_CANDIDATE_AFFECTS_PREDICTION}")
    print(f"PRODUCTION_FIFA_SNAPSHOT_DATASET={config.PRODUCTION_FIFA_SNAPSHOT_DATASET}")


if __name__ == "__main__":
    main()
