"""Tests for Phase 4D ProbabilityResult layer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api.main import app
from core.probability_coherence import ODDS_BLEND_APPLIED
from core.probability_result import build_probability_result
from fastapi.testclient import TestClient

client = TestClient(app)

PARITY_MATCHUPS = [
    ("Brazil", "Morocco"),
    ("Germany", "Haiti"),
    ("Argentina", "France"),
    ("Portugal", "DR Congo"),
]


def test_probability_result_raw_equals_final_without_odds() -> None:
    probs = {"home_win": 45.0, "draw": 28.0, "away_win": 27.0}
    result = build_probability_result(
        home_team="Brazil",
        away_team="Morocco",
        home_xg=1.5,
        away_xg=1.1,
        raw_probabilities_1x2=probs,
        final_probabilities_1x2=dict(probs),
        top_scores=[{"score": "1-0", "probability": 10.0}],
        score_coverage={"achieved_percent": 52.0},
        market_probabilities_1x2=None,
    )
    assert result.odds_blend_applied is False
    assert result.raw_probabilities_1x2 == result.final_probabilities_1x2
    assert result.probability_sum_valid is True
    assert result.coherence_warnings == []


def test_probability_result_odds_blend_detected() -> None:
    raw = {"home_win": 50.0, "draw": 28.0, "away_win": 22.0}
    final = {"home_win": 56.0, "draw": 24.0, "away_win": 20.0}
    market = {"home_win": 70.0, "draw": 20.0, "away_win": 10.0}
    result = build_probability_result(
        home_team="Germany",
        away_team="Haiti",
        home_xg=0.9,
        away_xg=2.2,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        top_scores=[{"score": "0-2", "probability": 11.0}],
        score_coverage=50.0,
        market_probabilities_1x2=market,
        odds_source="the_odds_api",
        odds_blend_weight_model=0.7,
        odds_blend_weight_market=0.3,
        odds_available=True,
        odds_affect_prediction=True,
    )
    assert result.odds_blend_applied is True
    assert ODDS_BLEND_APPLIED in result.coherence_warnings


def test_to_probability_diagnostics_dict_shape() -> None:
    probs = {"home_win": 50.0, "draw": 25.0, "away_win": 25.0}
    result = build_probability_result(
        home_team="A",
        away_team="B",
        home_xg=1.4,
        away_xg=1.3,
        raw_probabilities_1x2=probs,
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-1", "probability": 9.0}],
        score_coverage=50.0,
    )
    diag = result.to_probability_diagnostics_dict()
    assert "raw_probabilities_1x2" in diag
    assert "final_probabilities_1x2" in diag
    assert "coherence_warnings" in diag
    assert diag["probability_sum_valid"] is True


def test_predict_includes_probability_diagnostics() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    ).json()
    assert "probability_diagnostics" in data
    pd = data["probability_diagnostics"]
    assert pd["probability_sum_valid"] is True
    assert data["probabilities_1x2"] == pd["final_probabilities_1x2"]
    assert pd["raw_probabilities_1x2"] is not None
    assert "probability_coherence" in data
    assert "calibration_applied" in pd
    assert pd["calibration_applied"] is False


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_numeric_parity(home: str, away: str) -> None:
    payload = {"home_team": home, "away_team": away, "neutral_ground": True}
    first = client.post("/api/predict", json=payload).json()
    second = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert first["probabilities_1x2"][key] == second["probabilities_1x2"][key]
    assert first["home_xg"] == second["home_xg"]
    assert first["away_xg"] == second["away_xg"]
    for i, score in enumerate(first["top_scores"]):
        assert score["score"] == second["top_scores"][i]["score"]
        assert score["probability"] == second["top_scores"][i]["probability"]


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_backward_compatible_fields(home: str, away: str) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": home, "away_team": away, "neutral_ground": True},
    ).json()
    for field in (
        "probabilities_1x2",
        "home_xg",
        "away_xg",
        "top_scores",
        "score_coverage",
        "model_diagnostics",
        "global_rating_diagnostics",
        "home_power",
        "away_power",
    ):
        assert field in data
