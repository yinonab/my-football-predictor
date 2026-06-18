#!/usr/bin/env python3
"""Matchup-level divergence audit (Phase 1.5)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.global_ratings_audit import (
    MATCHUP_AUDIT_COLUMNS,
    audit_all_matchups,
    audit_sample_matchups,
    format_matchup_audit_table,
    write_csv,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit matchup divergence vs current neutral predictions.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--sample",
        action="store_true",
        help="Evaluate curated sample pairs (default)",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all 48x47 neutral team pairs (slow)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Write CSV report (e.g. backend/reports/matchup_divergence_audit.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    pe = TeamPowerEvaluator(dm)
    if args.all:
        print("Evaluating all team pairs (this may take several minutes)...")
        rows = audit_all_matchups(data_manager=dm, power_eval=pe)
    else:
        rows = audit_sample_matchups(data_manager=dm, power_eval=pe)
    print(format_matchup_audit_table(rows))
    if args.csv:
        csv_path = args.csv
        if not csv_path.is_absolute():
            csv_path = BACKEND_ROOT / csv_path
        write_csv([row.to_dict() for row in rows], csv_path)
        print(f"\nWrote {len(rows)} rows to {csv_path}")


if __name__ == "__main__":
    main()
