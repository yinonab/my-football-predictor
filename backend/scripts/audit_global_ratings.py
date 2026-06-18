#!/usr/bin/env python3
"""Team-level Global Rating Stack audit (Phase 1.5)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.global_ratings_audit import (
    TEAM_AUDIT_COLUMNS,
    audit_all_teams,
    format_team_audit_table,
    sort_team_rows,
    write_csv,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit internal vs external team ratings (diagnostics only).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Write CSV report (e.g. backend/reports/global_ratings_audit.csv)",
    )
    parser.add_argument(
        "--sort",
        choices=["power_delta", "form_inflation", "confidence"],
        default=None,
        help="Sort rows by elo delta, form inflation, or confidence",
    )
    parser.add_argument(
        "--only-warnings",
        action="store_true",
        help="Show only teams with at least one warning",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    pe = TeamPowerEvaluator(dm)
    rows = audit_all_teams(dm, pe)
    if args.sort:
        rows = sort_team_rows(rows, args.sort)
    if args.only_warnings:
        rows = [row for row in rows if row.warnings]
    print(format_team_audit_table(rows))
    if args.csv:
        csv_path = args.csv
        if not csv_path.is_absolute():
            csv_path = BACKEND_ROOT / csv_path
        write_csv([row.to_dict() for row in rows], csv_path)
        print(f"\nWrote {len(rows)} rows to {csv_path}")


if __name__ == "__main__":
    main()
