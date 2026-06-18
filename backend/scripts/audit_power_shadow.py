#!/usr/bin/env python3
"""Shadow Power calibration audit CLI (Phase 2A)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.opponent_maher import build_opponent_index
from core.power_shadow_calibration import (
    audit_all_shadow,
    audit_sample_shadow,
    format_shadow_table,
    write_csv,
)
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare shadow Power candidate variants vs current production formula.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sample", action="store_true", help="Curated pairs (default)")
    mode.add_argument("--all", action="store_true", help="All 48x47 team pairs")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument(
        "--include-xg",
        action="store_true",
        help="Include shadow xG/1X2 pipeline (slower)",
    )
    parser.add_argument(
        "--sort",
        choices=["improvement"],
        default=None,
        help="Sort rows by compression improvement vs best variant",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    opp_idx = None
    if args.include_xg:
        opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    if args.all:
        print("Evaluating all team pairs...")
        rows = audit_all_shadow(
            data_manager=dm,
            include_xg=args.include_xg,
            opponent_index=opp_idx,
        )
    else:
        rows = audit_sample_shadow(
            data_manager=dm,
            include_xg=args.include_xg,
            opponent_index=opp_idx,
        )
    if args.sort == "improvement":
        rows = sorted(rows, key=lambda r: r.improvement, reverse=True)
    print(format_shadow_table(rows))
    if args.csv:
        path = args.csv if args.csv.is_absolute() else BACKEND_ROOT / args.csv
        write_csv([row.to_dict() for row in rows], path)
        print(f"\nWrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
