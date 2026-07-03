"""Fusion blowout signal and xG uplift."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.blowout import apply_blowout_adjustment
from core.fusion_blowout import (
    FusionBlowoutSignal,
    apply_fusion_blowout,
    compute_fusion_blowout_signal,
)


def _make_signal(
    blowout_t: float,
    *,
    favorite_side: str = "home",
) -> FusionBlowoutSignal:
    favorite_outcome = "home_win" if favorite_side == "home" else "away_win"
    return FusionBlowoutSignal(
        blowout_t=blowout_t,
        favorite_side=favorite_side,
        favorite_outcome=favorite_outcome,
        favorite_probability=75.0,
        underdog_probability=10.0,
        margin_pp=65.0,
        weather_factor=1.0,
    )


def _expected_dog_xg(dog_xg: float, t: float) -> float:
    dog_floor = 0.45 + 0.35 * t
    return round(max(dog_floor, dog_xg * (1.0 - 0.12 * t)), 2)


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


def test_fusion_favorite_uplift_capped_on_extreme_mismatch() -> None:
    signal = _make_signal(0.87)
    pre_home, pre_away = 2.37, 0.80
    adj = apply_fusion_blowout(pre_home, pre_away, signal)

    assert adj.active
    assert adj.fusion_favorite_uplift_capped is True
    assert adj.fusion_favorite_uplift_cap == config.FUSION_MAX_FAVORITE_UPLIFT
    assert adj.home_xg <= pre_home + config.FUSION_MAX_FAVORITE_UPLIFT + 1e-9
    assert adj.original_uncapped_favorite_xg is not None
    assert adj.capped_favorite_xg is not None
    assert adj.original_uncapped_favorite_xg > adj.capped_favorite_xg
    assert adj.away_xg == _expected_dog_xg(pre_away, 0.87)


def test_fusion_favorite_uplift_unchanged_when_below_cap() -> None:
    signal = _make_signal(0.13)
    pre_home, pre_away = 1.62, 0.98
    adj = apply_fusion_blowout(pre_home, pre_away, signal)

    assert adj.active
    assert adj.fusion_favorite_uplift_capped is False
    fav_target = 2.75 + 0.13 * 2.05
    expected_home = round(pre_home + 0.13 * max(0.0, fav_target - pre_home), 2)
    assert adj.home_xg == expected_home
    assert adj.away_xg == _expected_dog_xg(pre_away, 0.13)


def test_fusion_cap_does_not_change_underdog_formula() -> None:
    signal = _make_signal(0.77)
    pre_home, pre_away = 2.00, 0.80
    adj = apply_fusion_blowout(pre_home, pre_away, signal)
    assert adj.away_xg == _expected_dog_xg(pre_away, 0.77)


def test_fusion_cap_applies_when_favorite_is_away() -> None:
    signal = _make_signal(0.84, favorite_side="away")
    pre_home, pre_away = 0.80, 2.22
    adj = apply_fusion_blowout(pre_home, pre_away, signal)

    assert adj.fusion_favorite_uplift_capped is True
    assert adj.away_xg <= pre_away + config.FUSION_MAX_FAVORITE_UPLIFT + 1e-9
    assert adj.home_xg == _expected_dog_xg(pre_home, 0.84)


def test_standard_blowout_path_unchanged() -> None:
    adj = apply_blowout_adjustment(
        2.37,
        0.80,
        home_power=900.0,
        away_power=500.0,
        advantage=0.0,
        home_elo=2100.0,
        away_elo=1500.0,
    )
    assert adj.fusion_favorite_uplift_capped is False
    assert adj.fusion_favorite_uplift_cap is None
