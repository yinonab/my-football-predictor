"""Tests for blowout scoreline adjustment."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.blowout import apply_blowout_adjustment
from core.math_engine import AdvancedDixonColesEngine


def test_blowout_inactive_on_close_match() -> None:
    adj = apply_blowout_adjustment(1.4, 1.2, 850.0, 820.0, 0.0)
    assert not adj.active
    assert adj.max_goals == 6


def test_blowout_inflates_favorite_xg() -> None:
    adj = apply_blowout_adjustment(2.25, 0.35, 998.0, 582.0, 0.0)
    assert adj.active
    assert adj.home_xg > 2.8
    assert adj.away_xg >= 0.85
    assert adj.max_goals >= 7


def test_blowout_underdog_can_score_in_top_scores() -> None:
    adj = apply_blowout_adjustment(2.25, 0.35, 998.0, 582.0, 0.0)
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6, alpha=adj.alpha)
    result = engine.generate_match_prediction(
        998.0,
        582.0,
        0.0,
        max_goals=adj.max_goals,
        top_n=3,
        home_xg_override=adj.home_xg,
        away_xg_override=adj.away_xg,
        include_all_scores=True,
    )
    top_scores = [s["score"] for s in result["top_scores"]]
    assert any(int(s.split("-")[1]) >= 1 for s in top_scores)


def test_spain_cape_verde_can_reach_high_scores() -> None:
    adj = apply_blowout_adjustment(2.25, 0.35, 998.0, 582.0, 0.0)
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6, alpha=adj.alpha)
    result = engine.generate_match_prediction(
        998.0,
        582.0,
        0.0,
        max_goals=adj.max_goals,
        top_n=10,
        home_xg_override=adj.home_xg,
        away_xg_override=adj.away_xg,
        include_all_scores=True,
    )
    all_scores = result["all_scores"]
    high = sum(
        p for score, p in all_scores.items() if int(score.split("-")[0]) >= 4
    )
    assert high > 15.0
    assert result["probabilities_1x2"]["home_win"] > 75.0


def test_germany_heavy_favorite() -> None:
    adj = apply_blowout_adjustment(1.99, 0.61, 920.0, 540.0, 0.0)
    assert adj.active
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6, alpha=adj.alpha)
    result = engine.generate_match_prediction(
        920.0,
        540.0,
        0.0,
        max_goals=adj.max_goals,
        top_n=5,
        home_xg_override=adj.home_xg,
        away_xg_override=adj.away_xg,
        include_all_scores=True,
    )
    top_scores = [s["score"] for s in result["top_scores"]]
    assert any(int(s.split("-")[0]) >= 3 for s in top_scores)
