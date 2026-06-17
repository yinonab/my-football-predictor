"""Calibration grid-search tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.calibrate import ModelParams, evaluate_params, grid_search


def test_calibrated_params_beat_old_defaults_on_top3() -> None:
    old = evaluate_params(
        ModelParams(rho=-0.07, alpha=0.12, avg_goals=2.6, home_advantage=55.0)
    )
    new = evaluate_params(
        ModelParams(rho=-0.15, alpha=0.0, avg_goals=2.6, home_advantage=0.0)
    )
    assert new.report.top3_score_hit_rate >= old.report.top3_score_hit_rate


def test_small_grid_returns_sorted_results() -> None:
    tiny_grid = {
        "rho": [-0.15, -0.07],
        "alpha": [0.0, 0.12],
        "avg_goals": [2.6, 3.0],
        "home_advantage": [0.0, 55.0],
    }
    top = grid_search(grid=tiny_grid, top_n=3)
    assert len(top) == 3
    assert top[0].score <= top[1].score <= top[2].score
