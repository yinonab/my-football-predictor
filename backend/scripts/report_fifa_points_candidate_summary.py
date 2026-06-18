#!/usr/bin/env python3
"""Aggregate FIFA-points walk-forward candidate summary (Phase 2J)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.model_activation_gate import _per_dataset_fifa_coverage
from core.temporal_backtest import (
    WalkForwardBacktestRow,
    attach_walk_forward_baseline_deltas,
    run_walk_forward_backtest,
)
from core.temporal_match_data import fifa_points_walk_forward_candidates
from data.tournament_data import DATASET_REGISTRY, list_dataset_keys, resolve_dataset_key

FOCUS_STRATEGIES = (
    "fifa_points_confidence_weighted",
    "fifa_points_snapshot_static",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FIFA-points candidate aggregate report.")
    parser.add_argument("--csv", type=Path, default=None, help="Read existing CSV instead of running")
    parser.add_argument(
        "--prior-mode",
        default="tournament_prior_file",
        choices=["default_internal", "tournament_prior_file", "rolling_from_prior_dataset"],
    )
    return parser.parse_args()


def _run_rows(prior_mode: str) -> list[WalkForwardBacktestRow]:
    rows: list[WalkForwardBacktestRow] = []
    targets = list_dataset_keys() + ["all"]
    for target in targets:
        for cand, elo in fifa_points_walk_forward_candidates():
            rows.append(
                run_walk_forward_backtest(
                    target,
                    candidate=cand,
                    elo_strategy=elo,
                    external_rating_mode="fifa_points_snapshot",
                    prior_mode=prior_mode,  # type: ignore[arg-type]
                )
            )
    return attach_walk_forward_baseline_deltas(rows)


def _load_csv(path: Path) -> list[WalkForwardBacktestRow]:
    import csv

    rows: list[WalkForwardBacktestRow] = []
    with path.open(encoding="utf-8") as fh:
        for item in csv.DictReader(fh):
            rows.append(
                WalkForwardBacktestRow(
                    dataset=item["dataset"],
                    matches=int(item["matches"]),
                    candidate=item["candidate"],
                    elo_strategy=item["elo_strategy"],
                    world_elo_mode=item.get("world_elo_mode", "none"),
                    leakage_label=item.get("leakage_label", "low"),
                    outcome_accuracy=float(item["outcome_accuracy"]),
                    exact_score_accuracy=float(item.get("exact_score_accuracy", 0)),
                    top3_score_hit_rate=float(item.get("top3_score_hit_rate", 0)),
                    mean_log_loss=float(item["mean_log_loss"]),
                    mean_brier=float(item["mean_brier"]),
                    prior_mode=item.get("prior_mode", "tournament_prior_file"),
                    external_rating_mode=item.get("external_rating_mode", "fifa_points_snapshot"),
                    external_rating_type=item.get("external_rating_type", "fifa_points"),
                    external_coverage=float(item.get("external_coverage", 0)),
                    fifa_points_coverage=float(item.get("fifa_points_coverage", 0)),
                    delta_log_loss_vs_baseline=float(item["delta_log_loss_vs_baseline"])
                    if item.get("delta_log_loss_vs_baseline") not in (None, "")
                    else None,
                    delta_brier_vs_baseline=float(item["delta_brier_vs_baseline"])
                    if item.get("delta_brier_vs_baseline") not in (None, "")
                    else None,
                    delta_1x2_acc_pp_vs_baseline=float(item["delta_1x2_acc_pp_vs_baseline"])
                    if item.get("delta_1x2_acc_pp_vs_baseline") not in (None, "")
                    else None,
                    notes=item.get("notes", ""),
                )
            )
    return rows


def _baseline(rows: list[WalkForwardBacktestRow], dataset: str) -> WalkForwardBacktestRow | None:
    for r in rows:
        if r.dataset == dataset and r.candidate in ("baseline", "current"):
            return r
    return None


def _weighted(rows: list[WalkForwardBacktestRow], field: str) -> float:
    total = sum(r.matches for r in rows)
    if total == 0:
        return 0.0
    return sum(getattr(r, field) * r.matches for r in rows) / total


def format_summary(rows: list[WalkForwardBacktestRow]) -> str:
    per_ds = [r for r in rows if r.dataset.lower() != "all combined"]
    combined = [r for r in rows if r.dataset.lower() == "all combined"]
    focus_rows = [
        r
        for r in rows
        if r.candidate.startswith("effective_external")
        and r.elo_strategy in FOCUS_STRATEGIES
    ]

    lines = ["FIFA points walk-forward aggregate summary", "=" * 60, ""]
    lines.append("FIFA coverage by dataset:")
    for ds, cov in sorted(_per_dataset_fifa_coverage().items()):
        flag = " (partial — Poland missing)" if ds.lower().startswith("euro") and cov < 1.0 else ""
        lines.append(f"  {ds}: {cov:.2%}{flag}")
    lines.append("")

    header = (
        f"{'dataset':16} | {'candidate':32} | {'strategy':28} | "
        f"{'fifa':>4} | {'1x2':>5} | {'log':>7} | {'brier':>6} | {'d_log':>7}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for r in sorted(focus_rows, key=lambda x: (x.dataset, x.candidate, x.elo_strategy)):
        dlog = r.delta_log_loss_vs_baseline
        dlog_s = f"{dlog:+.4f}" if dlog is not None else "-"
        lines.append(
            f"{r.dataset:16} | {r.candidate:32} | {r.elo_strategy:28} | "
            f"{r.fifa_points_coverage:4.2f} | {r.outcome_accuracy:5.1f} | "
            f"{r.mean_log_loss:7.4f} | {r.mean_brier:6.4f} | {dlog_s:>7}"
        )

    lines.append("")
    lines.append("Per-dataset wins vs baseline (focus strategies):")
    datasets = sorted({r.dataset for r in per_ds})
    for ds in datasets:
        base = _baseline(rows, ds)
        if not base:
            continue
        wins: list[str] = []
        losses: list[str] = []
        for strat in FOCUS_STRATEGIES:
            for variant in (
                "effective_external_current_formula",
                "effective_external_adjusted_form",
            ):
                cand = next(
                    (
                        r
                        for r in per_ds
                        if r.dataset == ds
                        and r.candidate == variant
                        and r.elo_strategy == strat
                    ),
                    None,
                )
                if not cand:
                    continue
                label = f"{variant.split('_')[-2]}_{strat.split('_')[-1]}"
                if cand.mean_log_loss < base.mean_log_loss - 1e-6:
                    wins.append(label)
                elif cand.mean_log_loss > base.mean_log_loss + 1e-6:
                    losses.append(label)
        lines.append(f"  {ds}: wins={wins or ['-']} losses={losses or ['-']}")

    grouped: dict[tuple[str, str], list[WalkForwardBacktestRow]] = {}
    for r in focus_rows:
        if r.dataset.lower() == "all combined":
            continue
        grouped.setdefault((r.candidate, r.elo_strategy), []).append(r)

    lines.append("")
    lines.append("Combined tournament metrics (match-weighted):")
    for (cand, strat), grp in sorted(grouped.items()):
        lines.append(
            f"  {cand} + {strat}: log_loss={_weighted(grp, 'mean_log_loss'):.4f} "
            f"brier={_weighted(grp, 'mean_brier'):.4f} "
            f"1x2={_weighted(grp, 'outcome_accuracy'):.1f}%"
        )

    if combined:
        lines.append("")
        lines.append("All combined rows:")
        for r in focus_rows:
            if r.dataset.lower() == "all combined":
                lines.append(
                    f"  {r.candidate} + {r.elo_strategy}: log={r.mean_log_loss:.4f} "
                    f"brier={r.mean_brier:.4f} 1x2={r.outcome_accuracy:.1f}%"
                )

    best_log = min(focus_rows, key=lambda r: r.mean_log_loss, default=None)
    best_brier = min(focus_rows, key=lambda r: r.mean_brier, default=None)
    best_1x2 = max(focus_rows, key=lambda r: r.outcome_accuracy, default=None)

    lines.append("")
    lines.append("Best focus candidates:")
    if best_log:
        lines.append(
            f"  log_loss: {best_log.candidate} + {best_log.elo_strategy} "
            f"({best_log.dataset} row; combined see weighted above)"
        )
    if best_brier:
        lines.append(
            f"  brier: {best_brier.candidate} + {best_brier.elo_strategy} ({best_brier.dataset})"
        )
    if best_1x2:
        lines.append(
            f"  1x2: {best_1x2.candidate} + {best_1x2.elo_strategy} ({best_1x2.dataset})"
        )

    lines.append("")
    lines.append("Consistency notes:")
    wc2022_improved = any(
        r.dataset.startswith("WC 2022")
        and r.delta_log_loss_vs_baseline is not None
        and r.delta_log_loss_vs_baseline < -0.005
        for r in focus_rows
    )
    others_regress = any(
        not r.dataset.startswith("WC 2022")
        and r.dataset.lower() != "all combined"
        and r.delta_log_loss_vs_baseline is not None
        and r.delta_log_loss_vs_baseline > 0.005
        for r in focus_rows
        if r.elo_strategy == "fifa_points_confidence_weighted"
    )
    lines.append(
        f"  WC2022 improvement present: {wc2022_improved}; "
        f"other datasets regress (conf_weighted): {others_regress}"
    )
    lines.append(
        "  Euro 2024 partial FIFA coverage (96%) may add noise; not blocking if >= 90%."
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    if args.csv and args.csv.exists():
        rows = _load_csv(args.csv)
    else:
        rows = _run_rows(args.prior_mode)
    print(format_summary(rows))


if __name__ == "__main__":
    main()
