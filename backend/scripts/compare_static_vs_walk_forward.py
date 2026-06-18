#!/usr/bin/env python3
"""Compare static vs walk-forward backtest metrics (Phase 2D/2E)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.power_multitournament_backtest import run_multitournament_backtest
from core.temporal_backtest import run_walk_forward_backtest
from core.temporal_match_data import serious_walk_forward_candidates
from data.tournament_data import DATASET_REGISTRY, list_dataset_keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Static vs walk-forward comparison.")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
    )
    parser.add_argument(
        "--compare-candidates",
        action="store_true",
        help="Include top walk-forward shadow candidates",
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
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = args.datasets or ["wc2022"]

    header = (
        f"{'dataset':16} | {'mode':>14} | {'candidate':>28} | {'1x2':>5} | "
        f"{'log_loss':>8} | {'brier':>6} | {'leak':>4} | {'dq':>8} | notes"
    )
    lines = [header, "-" * len(header)]

    wf_candidates = [("baseline", "internal_only")]
    if args.compare_candidates:
        wf_candidates = serious_walk_forward_candidates(include_defense_flip=False)

    seen: set[str] = set()
    for ds in datasets:
        key = ds.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        keys = list_dataset_keys() if key == "all" else [key]

        for dk in keys:
            reg = DATASET_REGISTRY.get(dk)
            if not reg:
                continue
            static = run_multitournament_backtest(
                dk,
                "current",
                "internal_only",
                matches=reg.matches,
                elo_map=reg.elo_map,
                dataset_label=reg.label,
            )
            lines.append(
                f"{static.dataset:16} | {'static':>14} | {'current':>28} | "
                f"{static.outcome_accuracy:5.1f} | {static.mean_log_loss:8.4f} | "
                f"{static.mean_brier:6.4f} | {'high':>4} | {'snapshot':>8} | "
                f"pre-tournament FIFA"
            )
            for cand, elo in wf_candidates:
                wf = run_walk_forward_backtest(
                    dk,
                    candidate=cand,
                    elo_strategy=elo,
                    world_elo_mode=args.world_elo_mode,
                    prior_mode=args.prior_mode,
                )
                label = cand if cand != "baseline" else "baseline"
                lines.append(
                    f"{wf.dataset:16} | {'walk_forward':>14} | {label:>28} | "
                    f"{wf.outcome_accuracy:5.1f} | {wf.mean_log_loss:8.4f} | "
                    f"{wf.mean_brier:6.4f} | {wf.leakage_label:>4} | "
                    f"{wf.data_quality:>8} | prior={wf.prior_mode}"
                )

    print("Static vs walk-forward comparison\n")
    print("\n".join(lines))
    print(
        "\nPurpose: quantify leakage impact and compare shadow candidates under "
        "walk-forward temporal mode."
    )


if __name__ == "__main__":
    main()
