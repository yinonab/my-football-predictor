#!/usr/bin/env python3
"""Validate historical and production external rating snapshots (Phase 2H/3B)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.external_rating_snapshots import (
    PRODUCTION_SNAPSHOT_KEYS,
    TOURNAMENT_SNAPSHOT_AS_OF,
    format_snapshot_validation_table,
    list_production_team_names,
    validate_external_rating_snapshot,
)
from data.tournament_data import resolve_dataset_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate external rating snapshots.")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
        help="wc2018, wc2022, euro2024, copa2024, wc2026_current (default: tournaments)",
    )
    parser.add_argument(
        "--external-rating-mode",
        default="fifa_points_snapshot",
        choices=["fifa_points_snapshot", "world_elo_snapshot", "any"],
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _resolve_validation_key(name: str) -> str:
    key = name.strip().lower()
    if key in PRODUCTION_SNAPSHOT_KEYS:
        return key
    if key in TOURNAMENT_SNAPSHOT_AS_OF:
        return key
    return resolve_dataset_key(name)


def _print_production_summary(report) -> None:
    expected = list_production_team_names()
    print("\nProduction FIFA coverage summary")
    print(f"  dataset: {report.dataset}")
    print(f"  teams expected: {report.teams}")
    print(f"  fifa_points covered: {round(report.fifa_points_coverage * report.teams)}")
    print(f"  missing: {report.missing}")
    print(f"  coverage: {report.fifa_points_coverage:.1%}")
    print(f"  threshold: {config.PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE:.0%}")
    print(f"  status: {report.status}")
    if report.unmatched_teams:
        print(f"  naming mismatches (sample): {', '.join(report.unmatched_teams[:5])}")
    if report.missing:
        block = __import__(
            "core.external_rating_snapshots",
            fromlist=["get_external_rating_snapshot"],
        ).get_external_rating_snapshot(report.dataset)
        snap_teams = set((block or {}).get("teams") or {})
        missing_names = sorted(set(expected) - snap_teams)
        if missing_names:
            print(f"  missing teams (sample): {', '.join(missing_names[:10])}")


def main() -> None:
    args = parse_args()
    default_keys = [k for k in TOURNAMENT_SNAPSHOT_AS_OF]
    datasets = args.datasets or default_keys
    reports = []
    for ds in datasets:
        key = _resolve_validation_key(ds)
        reports.append(
            validate_external_rating_snapshot(
                key,
                external_rating_mode=args.external_rating_mode,
            )
        )

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print("External rating snapshot validation\n")
        print(format_snapshot_validation_table(reports))
        prod_reports = [r for r in reports if r.dataset in PRODUCTION_SNAPSHOT_KEYS]
        for pr in prod_reports:
            _print_production_summary(pr)
        failed = [r for r in reports if r.status == "fail"]
        if failed:
            print(f"\n{len(failed)} dataset(s) failed validation.")
            sys.exit(1)


if __name__ == "__main__":
    main()
