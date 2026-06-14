"""Run parameter calibration on WC 2022 backtest."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.calibrate import current_defaults_report, grid_search  # noqa: E402


def _print_result(rank: int, item) -> None:
    p = item.params
    r = item.report
    print(
        f"  #{rank}  score={item.score:.4f}  |  "
        f"rho={p.rho:.2f}  alpha={p.alpha:.2f}  "
        f"goals={p.avg_goals:.1f}  home_adv={p.home_advantage:.0f}"
    )
    print(
        f"       1X2={r.outcome_accuracy}%  exact={r.exact_score_accuracy}%  "
        f"top3={r.top3_score_hit_rate}%  brier={r.mean_brier}  log={r.mean_log_loss}"
    )


def main() -> None:
    print("=" * 60)
    print("  CALIBRATION — World Cup 2022 grid search")
    print("=" * 60)

    baseline = current_defaults_report()
    print("\n  Current defaults:")
    _print_result(0, baseline)

    print("\n  Searching grid (this may take ~30s)...")
    top = grid_search(top_n=5)

    print("\n  Top 5 parameter sets:")
    for idx, item in enumerate(top, start=1):
        _print_result(idx, item)

    best = top[0]
    print("\n  RECOMMENDED config.py values:")
    print(f"    DEFAULT_RHO = {best.params.rho}")
    print(f"    OVERDISPERSION_ALPHA = {best.params.alpha}")
    print(f"    GLOBAL_XG_AVG = {best.params.avg_goals}")
    print(f"    DEFAULT_HOME_ADV = {best.params.home_advantage}")
    print("=" * 60)


if __name__ == "__main__":
    main()
