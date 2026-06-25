"""Fusion blowout signal and xG uplift."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.fusion_blowout import apply_fusion_blowout, compute_fusion_blowout_signal


def test_fusion_signal_active_on_wide_blended_margin() -> None:
    probs = {"home_win": 72.0, "draw": 18.0, "away_win": 10.0}
    market = {"home_win": 88.0, "draw": 8.0, "away_win": 4.0}
    signal = compute_fusion_blowout_signal(
        probs,
        market,
        power_gap=217.0,
        weather_xg_delta=0.0,
    )
    assert signal.active
    assert signal.favorite_outcome == "home_win"
    assert "BLENDED_MARGIN_WIDE" in signal.triggers
    assert "MARKET_CONFIRMS_FAVORITE" in signal.triggers


def test_fusion_blowout_inflates_favorite_xg() -> None:
    probs = {"home_win": 72.0, "draw": 18.0, "away_win": 10.0}
    signal = compute_fusion_blowout_signal(
        probs,
        None,
        power_gap=200.0,
    )
    adj = apply_fusion_blowout(0.7, 2.1, signal)
    assert adj.active
    assert adj.home_xg > 0.7
    assert adj.max_goals >= 7


def test_weather_suppresses_fusion_blowout() -> None:
    probs = {"home_win": 72.0, "draw": 18.0, "away_win": 10.0}
    signal = compute_fusion_blowout_signal(
        probs,
        None,
        power_gap=200.0,
        weather_xg_delta=-0.15,
    )
    assert "WEATHER_REDUCES_GOAL_VOLUME" in signal.suppressed_by
    assert signal.weather_factor < 1.0
