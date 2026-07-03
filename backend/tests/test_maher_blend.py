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


def test_portugal_dr_congo_favorite_clear() -> None:
    """Elo gap ~266 must not collapse to a 1-1 top score."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Portugal (פורטוגל)",
            "away_team": "DR Congo (קונגו)",
            "neutral_ground": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["probabilities_1x2"]["home_win"] > 62.0
    assert data["probabilities_1x2"]["away_win"] < 18.0
    top = data["top_scores"][0]["score"]
    h, a = (int(x) for x in top.split("-"))
    assert h > a
    assert data["home_xg"] > data["away_xg"] + 0.4


def test_power_based_xg_splits_by_elo() -> None:
    h, a = power_based_xg(1900.0, 1300.0, 0.0, global_avg=2.6)
    assert h > 2.0
    assert a < 0.5


# --- Stage 2: Maher fallback confidence -----------------------------------


def test_maher_confidence_default_matches_full_confidence() -> None:
    args = (1.8, 0.7, 760.0, 660.0, 0.0)
    kwargs = {"global_avg": 2.6}
    base = blend_maher_with_power(*args, **kwargs)
    explicit = blend_maher_with_power(*args, maher_confidence=1.0, **kwargs)
    assert base == explicit


def test_maher_confidence_shifts_toward_power_on_medium_gap() -> None:
    """Lower confidence lets power/Elo lead: favorite up, underdog down."""
    maher_h, maher_a = 1.3, 1.3  # symmetric fallback pair
    full_h, full_a = blend_maher_with_power(
        maher_h, maher_a, 820.0, 700.0, 0.0, global_avg=2.6, maher_confidence=1.0
    )
    low_h, low_a = blend_maher_with_power(
        maher_h, maher_a, 820.0, 700.0, 0.0, global_avg=2.6, maher_confidence=0.6
    )
    assert low_h >= full_h
    assert low_a <= full_a


def test_maher_confidence_clamped() -> None:
    args = (1.8, 0.7, 820.0, 700.0, 0.0)
    kwargs = {"global_avg": 2.6}
    assert blend_maher_with_power(
        *args, maher_confidence=5.0, **kwargs
    ) == blend_maher_with_power(*args, maher_confidence=1.0, **kwargs)
