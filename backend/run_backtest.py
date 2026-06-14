"""Run WC 2022 backtest and print a human-readable report."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.backtest import BacktestRunner  # noqa: E402


def main() -> None:
    report = BacktestRunner().run_wc2022()

    print("=" * 60)
    print(f"  BACKTEST: {report.tournament}")
    print("=" * 60)
    print(f"  Matches evaluated:     {report.match_count}")
    print()
    print("  --- 1X2 (outcome) ---")
    print(f"  Model accuracy:        {report.outcome_accuracy}%")
    print(f"  Baseline (Elo fav):    {report.baseline_outcome_accuracy}%")
    print(f"  Mean Brier score:      {report.mean_brier}  (lower is better)")
    print()
    print("  --- Exact score ---")
    print(f"  Exact score hit rate:  {report.exact_score_accuracy}%")
    print(f"  Top-3 score hit rate:  {report.top3_score_hit_rate}%")
    print(f"  Mean log-loss:         {report.mean_log_loss}  (lower is better)")
    print(f"  Baseline 1-0/0-1:      {report.baseline_exact_accuracy}%")
    print()
    print("  --- Biggest upsets (model wrong, favorite strong) ---")
    for item in report.upsets:
        print(
            f"    {item.home} vs {item.away}: "
            f"actual {item.actual_score}, "
            f"predicted {item.predicted_top_score} ({item.predicted_outcome})"
        )
    print()
    print("  --- Worst exact-score surprises ---")
    for item in report.worst_predictions:
        print(
            f"    {item.home} vs {item.away}: "
            f"actual {item.actual_score}, "
            f"top pick {item.predicted_top_score}, "
            f"log-loss {item.log_loss_score:.2f}"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
