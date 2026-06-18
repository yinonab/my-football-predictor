#!/usr/bin/env python3
"""Qualitative regression suite for known diagnostic matchups (Phase 2C/2J)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.regression_diagnostic_matchups import (
    format_regression_table,
    run_all_regression_diagnostics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostic matchup regression suite.")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--external-rating-mode",
        default="none",
        choices=["none", "fifa_points_snapshot"],
    )
    parser.add_argument("--candidate", default=None, help="Power variant override")
    parser.add_argument("--strategy", default=None, help="Elo / FIFA strategy override")
    parser.add_argument(
        "--fifa-dataset",
        default="wc2022",
        help="Snapshot dataset for FIFA normalization in diagnostic mode",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = run_all_regression_diagnostics(
        external_rating_mode=args.external_rating_mode,
        power_variant=args.candidate,
        elo_strategy=args.strategy,
        fifa_dataset_key=args.fifa_dataset,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        mode = args.external_rating_mode
        cand = args.candidate or "default"
        strat = args.strategy or "default"
        print(f"Diagnostic matchup regression (mode={mode}, candidate={cand}, strategy={strat})\n")
        print(format_regression_table(results))
        passed = sum(1 for r in results if r.improves_known_issue)
        warned = sum(1 for r in results if r.warnings)
        print(f"\n{passed}/{len(results)} matchups improved or met expectation")
        if warned:
            print(f"{warned} matchup(s) with balanced-shift warnings")


if __name__ == "__main__":
    main()
