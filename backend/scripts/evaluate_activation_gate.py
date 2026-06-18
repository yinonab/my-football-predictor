#!/usr/bin/env python3
"""Evaluate activation gate for shadow Power candidates (Phase 2C/2D/2J)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.model_activation_gate import (
    activation_candidate_status,
    activation_diagnostic_fields,
    build_walk_forward_activation_rows,
    evaluate_activation_gate,
    format_activation_gate_report,
)
from core.regression_diagnostic_matchups import (
    collect_balanced_match_warnings,
    run_all_regression_diagnostics,
)
from core.temporal_backtest import attach_walk_forward_baseline_deltas, write_walk_forward_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Activation gate evaluation.")
    parser.add_argument(
        "--include-defense-flip",
        action="store_true",
        help="Include defense-flip variants (static / all-shadow modes)",
    )
    parser.add_argument(
        "--run-walk-forward",
        action="store_true",
        help="Run walk-forward backtests before gating (slow)",
    )
    parser.add_argument(
        "--external-rating-mode",
        default="none",
        choices=[
            "none",
            "world_elo_snapshot",
            "fifa_points_snapshot",
            "current_static_world_elo",
        ],
        help="External anchor mode for walk-forward runs",
    )
    parser.add_argument(
        "--prior-mode",
        default="tournament_prior_file",
        choices=["default_internal", "tournament_prior_file", "rolling_from_prior_dataset"],
    )
    parser.add_argument(
        "--candidate-set",
        default="serious",
        choices=["serious", "all-shadow", "fifa-points"],
        help="Walk-forward candidate set when --run-walk-forward",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
        help="Tournament dataset keys (default: all tournament keys + combined when all)",
    )
    parser.add_argument("--csv", type=Path, default=None, help="Write walk-forward rows CSV")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    walk_forward_rows = None
    if args.run_walk_forward:
        walk_forward_rows = build_walk_forward_activation_rows(
            datasets=args.datasets,
            external_rating_mode=args.external_rating_mode,
            prior_mode=args.prior_mode,
            candidate_set=args.candidate_set,
            include_defense_flip=args.include_defense_flip,
        )
        if args.csv:
            enriched = attach_walk_forward_baseline_deltas(walk_forward_rows)
            write_walk_forward_csv(enriched, args.csv)

    balanced_warnings: list[str] = []
    try:
        regression = run_all_regression_diagnostics(
            external_rating_mode=args.external_rating_mode
            if args.external_rating_mode == "fifa_points_snapshot"
            else "none",
            power_variant=(
                "effective_external_current_formula"
                if args.external_rating_mode == "fifa_points_snapshot"
                else None
            ),
            elo_strategy=(
                "fifa_points_confidence_weighted"
                if args.external_rating_mode == "fifa_points_snapshot"
                else None
            ),
        )
        balanced_warnings = collect_balanced_match_warnings(regression)
    except Exception:
        pass

    result = evaluate_activation_gate(
        run_backtests=False,
        walk_forward_rows=walk_forward_rows,
        run_walk_forward=False,
        include_defense_flip=args.include_defense_flip,
        balanced_warnings=balanced_warnings,
        external_rating_mode=args.external_rating_mode,
        prior_mode=args.prior_mode,
        candidate_set=args.candidate_set,
        walk_forward_datasets=args.datasets,
    )

    diag_fields = activation_diagnostic_fields(result)
    if args.json:
        payload = result.to_dict()
        payload.update(diag_fields)
        if args.external_rating_mode == "fifa_points_snapshot":
            from core.model_activation_gate import _per_dataset_fifa_coverage

            payload["fifa_points_coverage_by_dataset"] = _per_dataset_fifa_coverage()
        print(json.dumps(payload, indent=2))
    else:
        print(format_activation_gate_report(result))
        if args.external_rating_mode == "fifa_points_snapshot":
            from core.model_activation_gate import _per_dataset_fifa_coverage

            cov = _per_dataset_fifa_coverage()
            print("")
            print("FIFA points coverage by dataset:")
            for ds, c in sorted(cov.items()):
                print(f"  {ds}: {c:.2f}")
        print("")
        print(f"activation_candidate_status: {diag_fields['activation_candidate_status']}")
        if args.csv:
            print(f"Walk-forward CSV: {args.csv}")


if __name__ == "__main__":
    main()
