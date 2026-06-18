#!/usr/bin/env python3
"""Matchup-level Power decomposition audit (Phase 1.6)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.h2h_adjustment import H2HStore
from core.power_component_audit import (
    audit_sample_matchup_power,
    format_matchup_power_table,
    write_csv,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Identify which Power components compress Elo/world gaps.",
    )
    parser.add_argument("--sample", action="store_true", help="Curated sample pairs")
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    pe = TeamPowerEvaluator(dm)
    h2h = H2HStore()
    rows = audit_sample_matchup_power(
        data_manager=dm,
        power_eval=pe,
        h2h_lookup=h2h.get,
    )
    print(format_matchup_power_table(rows))
    if args.csv:
        path = args.csv if args.csv.is_absolute() else BACKEND_ROOT / args.csv
        write_csv([row.to_dict() for row in rows], path)
        print(f"\nWrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
