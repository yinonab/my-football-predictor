#!/usr/bin/env python3
"""Multi-tournament full-pipeline shadow backtest (Phase 2B/2C)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.power_effective_elo import format_full_backtest_table, run_all_full_pipeline_backtests
from core.power_multitournament_backtest import (
    format_multitournament_table,
    run_all_multitournament_backtests,
    run_dataset_backtests,
    serious_backtest_candidates,
    write_multitournament_csv,
)
from core.power_shadow_calibration import format_backtest_table, run_all_shadow_backtests
from data.tournament_data import dataset_documentation, list_dataset_keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shadow Power backtest — engine-level or full pipeline."
    )
    parser.add_argument(
        "--full-pipeline",
        action="store_true",
        help="Full Maher/xG/blowout/Dixon-Coles path with effective Elo variants",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        metavar="NAME",
        help=(
            "Dataset: wc2018, wc2022, euro2024, copa2024, qualifiers2026, all "
            "(repeatable; default wc2022 for legacy mode, all for --compare-top-candidates)"
        ),
    )
    parser.add_argument(
        "--compare-top-candidates",
        action="store_true",
        help="Run serious candidate set only (excludes defense flip by default)",
    )
    parser.add_argument(
        "--include-defense-flip",
        action="store_true",
        help="Include defense-flip effective Elo variants (optional, risky)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Write results CSV (e.g. reports/power_shadow_multitournament_backtest.csv)",
    )
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="Show dataset key mapping and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list_datasets:
        print("Dataset mapping:")
        for key, desc in dataset_documentation().items():
            print(f"  {key}: {desc}")
        return

    if args.full_pipeline and (args.compare_top_candidates or args.datasets):
        datasets = args.datasets or ["all"]
        rows = []
        for ds in datasets:
            rows.extend(
                run_dataset_backtests(
                    ds,
                    include_defense_flip=args.include_defense_flip,
                )
            )
        print("Shadow Power backtest — multi-tournament full pipeline\n")
        print(format_multitournament_table(rows))
        if args.csv:
            write_multitournament_csv(rows, args.csv)
            print(f"\nWrote {args.csv}")
        print(
            "\nNote: Full pipeline includes Maher opponent-aware xG, power blend, "
            "underdog floor, blowout, and Dixon-Coles."
        )
        print(
            "WARNING: Backtest uses static snapshots — not walk-forward. "
            "Run scripts/audit_backtest_leakage.py before trusting metrics."
        )
        if not args.include_defense_flip:
            n = len(serious_backtest_candidates(include_defense_flip=False))
            print(f"Serious candidates only ({n} combos). Use --include-defense-flip to add defense variants.")
        return

    if args.full_pipeline:
        print("Shadow Power backtest — WC 2022 (full pipeline + effective Elo)\n")
        rows = run_all_full_pipeline_backtests()
        print(format_full_backtest_table(rows))
        print(
            "\nNote: Full pipeline includes Maher opponent-aware xG, power blend, "
            "underdog floor, blowout, and Dixon-Coles."
        )
        print("Use --dataset all --compare-top-candidates for Phase 2C multi-tournament gate.")
        return

    print("Shadow Power backtest — WC 2022 (engine-level, candidate Power only)\n")
    rows = run_all_shadow_backtests()
    print(format_backtest_table(rows))
    print(
        "\nNote: Engine-level only (no Maher/xG blend). "
        "Use --full-pipeline for Phase 2B comparison."
    )


if __name__ == "__main__":
    main()
