"""Tests for Maher + power xG blend."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.maher import blend_maher_with_power, power_based_xg
from core.math_engine import AdvancedDixonColesEngine


def test_large_gap_increases_favorite_xg() -> None:
    maher_h, maher_a = 1.8, 0.7
    blended_h, blended_a = blend_maher_with_power(
        maher_h,
        maher_a,
        998.0,
        582.0,
        0.0,
        global_avg=2.6,
    )
    assert blended_h > maher_h
    assert blended_a < maher_a
    assert blended_h / max(blended_a, 0.1) > maher_h / maher_a


def test_spain_cape_verde_favors_clearer_scoreline() -> None:
    maher_h, maher_a = 1.8, 0.7
    home_xg, away_xg = blend_maher_with_power(
        maher_h, maher_a, 998.0, 582.0, 0.0, global_avg=2.6
    )
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6)
    result = engine.generate_match_prediction(
        998.0,
        582.0,
        0.0,
        top_n=3,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    assert result["probabilities_1x2"]["home_win"] > 70.0
    top = result["top_scores"][0]["score"]
    h, a = (int(x) for x in top.split("-"))
    assert h > a
    assert h >= 2


def test_power_based_xg_splits_by_elo() -> None:
    h, a = power_based_xg(1900.0, 1300.0, 0.0, global_avg=2.6)
    assert h > 2.0
    assert a < 0.5
