#!/usr/bin/env python3
"""Team-level Power component audit (Phase 1.6)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.power_component_audit import (
    TEAM_POWER_COLUMNS,
    audit_all_team_components,
    format_team_power_table,
    sort_team_power_rows,
    write_csv,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decompose composite Power into Elo/form/attack/defense components.",
    )
    parser.add_argument("--only-warnings", action="store_true")
    parser.add_argument(
        "--sort",
        choices=["power", "form_component", "defense_component", "compression_suspects"],
    )
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dm = LiveDataManager()
    pe = TeamPowerEvaluator(dm)
    rows = audit_all_team_components(dm, pe)
    if args.sort:
        rows = sort_team_power_rows(rows, args.sort)
    if args.only_warnings:
        rows = [row for row in rows if row.warnings]
    print(format_team_power_table(rows))
    if args.csv:
        path = args.csv if args.csv.is_absolute() else BACKEND_ROOT / args.csv
        write_csv([row.to_dict() for row in rows], path)
        print(f"\nWrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
