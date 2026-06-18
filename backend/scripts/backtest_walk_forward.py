#!/usr/bin/env python3
"""Walk-forward full-pipeline shadow backtest (Phase 2D/2E/2I)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.external_rating_mode import resolve_external_rating_mode
from core.temporal_backtest import (
    attach_walk_forward_baseline_deltas,
    format_walk_forward_table,
    run_walk_forward_backtest,
    write_walk_forward_csv,
)
from core.temporal_match_data import (
    all_shadow_walk_forward_candidates,
    fifa_points_walk_forward_candidates,
    serious_walk_forward_candidates,
)
from data.tournament_data import list_dataset_keys, resolve_dataset_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward temporal backtest.")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
        help="wc2018, wc2022, euro2024, copa2024, qualifiers2026, all",
    )
    parser.add_argument(
        "--candidate",
        default=None,
        help="baseline, effective_elo_current_formula, ... (ignored with --compare-top-candidates)",
    )
    parser.add_argument(
        "--elo-strategy",
        default="internal_only",
        help="Used only with single --candidate mode",
    )
    parser.add_argument(
        "--compare-top-candidates",
        action="store_true",
        help="Run serious candidate set (defense flip excluded by default)",
    )
    parser.add_argument(
        "--candidate-set",
        default="serious",
        choices=["serious", "all-shadow", "fifa-points"],
        help="Candidate set when --compare-top-candidates",
    )
    parser.add_argument(
        "--include-defense-flip",
        action="store_true",
        help="Include defense-flip variants (optional, risky)",
    )
    parser.add_argument(
        "--prior-mode",
        default="default_internal",
        choices=["default_internal", "tournament_prior_file", "rolling_from_prior_dataset"],
    )
    parser.add_argument(
        "--world-elo-mode",
        default="none",
        choices=["none", "current_static", "snapshot_file", "proxy_from_internal"],
        help="Legacy; use --external-rating-mode when possible",
    )
    parser.add_argument(
        "--external-rating-mode",
        default=None,
        choices=[
            "none",
            "world_elo_snapshot",
            "fifa_points_snapshot",
            "current_static_world_elo",
        ],
        help="External anchor mode for walk-forward evaluation",
    )
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args()


def _candidate_list(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.compare_top_candidates:
        ext_mode = resolve_external_rating_mode(
            external_rating_mode=args.external_rating_mode,
            world_elo_mode=args.world_elo_mode,
        )
        if args.candidate_set == "fifa-points" or ext_mode == "fifa_points_snapshot":
            return fifa_points_walk_forward_candidates()
        if args.candidate_set == "all-shadow":
            return all_shadow_walk_forward_candidates(
                include_defense_flip=args.include_defense_flip
            )
        return serious_walk_forward_candidates(
            include_defense_flip=args.include_defense_flip
        )
    return [(args.candidate or "baseline", args.elo_strategy)]


def _run_for_datasets(
    datasets: list[str],
    candidates: list[tuple[str, str]],
    *,
    prior_mode: str,
    world_elo_mode: str,
    external_rating_mode: str | None,
) -> list:
    rows = []
    for ds in datasets:
        key = resolve_dataset_key(ds)
        targets = list_dataset_keys() + ["all"] if key == "all" else [ds]
        for target in targets:
            for cand, elo in candidates:
                rows.append(
                    run_walk_forward_backtest(
                        target,
                        candidate=cand,
                        elo_strategy=elo,
                        world_elo_mode=world_elo_mode,  # type: ignore[arg-type]
                        external_rating_mode=external_rating_mode,
                        prior_mode=prior_mode,
                    )
                )
    return rows


def main() -> None:
    args = parse_args()
    datasets = args.datasets or ["wc2022"]
    candidates = _candidate_list(args)
    ext_mode = resolve_external_rating_mode(
        external_rating_mode=args.external_rating_mode,
        world_elo_mode=args.world_elo_mode,
    )
    rows = _run_for_datasets(
        datasets,
        candidates,
        prior_mode=args.prior_mode,
        world_elo_mode=args.world_elo_mode,
        external_rating_mode=args.external_rating_mode,
    )
    rows = attach_walk_forward_baseline_deltas(rows)

    print("Walk-forward full-pipeline backtest\n")
    print(format_walk_forward_table(rows))
    if args.csv:
        write_walk_forward_csv(rows, args.csv)
        print(f"\nWrote {args.csv}")

    from core.external_rating_snapshots import validate_external_rating_snapshot

    if ext_mode in ("world_elo_snapshot", "fifa_points_snapshot"):
        mode_label = ext_mode
        print(f"\nExternal snapshot coverage ({mode_label}):")
        seen: set[str] = set()
        for ds in datasets:
            key = resolve_dataset_key(ds)
            if key in seen or key == "all":
                continue
            seen.add(key)
            report = validate_external_rating_snapshot(key, external_rating_mode=mode_label)
            print(
                f"  {report.dataset}: world_elo={report.world_elo_coverage:.2f} "
                f"fifa_points={report.fifa_points_coverage:.2f} "
                f"any={report.any_external_rating_coverage:.2f} "
                f"leakage={report.leakage} warnings={report.warnings or ['-']}"
            )
        if ext_mode == "world_elo_snapshot":
            print(
                "\nNote: world_elo_snapshot uses external_rating_snapshots.json world_elo only — "
                "never current global_ratings.json. Missing world_elo falls back to internal."
            )
        else:
            print(
                "\nNote: fifa_points_snapshot uses normalized FIFA ranking points — "
                "not World Elo. Missing fifa_points falls back to internal."
            )
    else:
        print(
            "\nNote: Snapshots use only matches strictly before each target. "
            "world_elo_mode=none recommended for baseline activation. "
            "Use --external-rating-mode fifa_points_snapshot for FIFA-points external evaluation."
        )


if __name__ == "__main__":
    main()
