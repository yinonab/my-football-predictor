#!/usr/bin/env python3
"""Effective Elo anchor audit CLI (Phase 2B)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.opponent_maher import build_opponent_index
from core.power_effective_elo import (
    audit_all_effective_elo,
    audit_sample_effective_elo,
    format_effective_elo_table,
    write_csv,
)
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit internal vs world Elo and shadow full-pipeline variants.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sample", action="store_true", help="Curated pairs (default)")
    mode.add_argument("--all", action="store_true", help="All team pairs (slow)")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--include-top-scores", action="store_true")
    parser.add_argument(
        "--sort",
        choices=["divergence"],
        default=None,
        help="Sort by internal/world Elo divergence",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    if args.all:
        print("Evaluating all pairs with full-pipeline shadow (slow)...")
        rows = audit_all_effective_elo(data_manager=dm, opponent_index=opp_idx)
    else:
        rows = audit_sample_effective_elo(
            data_manager=dm,
            opponent_index=opp_idx,
            include_top_scores=args.include_top_scores,
        )
    if args.sort == "divergence":
        rows = sorted(rows, key=lambda r: r.elo_divergence, reverse=True)
    print(format_effective_elo_table(rows))
    if args.csv:
        path = args.csv if args.csv.is_absolute() else BACKEND_ROOT / args.csv
        write_csv([row.to_dict() for row in rows], path)
        print(f"\nWrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
