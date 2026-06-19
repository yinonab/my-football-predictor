"""Tests for Phase 4I probability pipeline and calibration runtime."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api.main import app
from core.probability_calibration_runtime import apply_probability_calibration
from core.probability_coherence_gate import CoherenceGateResult
from core.probability_pipeline import finalize_probability_pipeline
from fastapi.testclient import TestClient

client = TestClient(app)


def test_pipeline_odds_off_final_equals_raw() -> None:
    raw = {"home_win": 45.0, "draw": 28.0, "away_win": 27.0}
    with patch("config.ODDS_AFFECT_PREDICTION", False):
        pipeline = finalize_probability_pipeline(
            home_team="Brazil",
            away_team="Morocco",
            home_xg=1.5,
            away_xg=1.1,
            raw_probabilities_1x2=raw,
            top_scores=[{"score": "1-0", "probability": 10.0}],
            score_coverage=52.0,
            market_odds={"home_win": 30.0, "draw": 30.0, "away_win": 40.0},
            odds_available=True,
        )
    assert pipeline.final_probabilities_1x2 == raw
    assert pipeline.probability_result.odds_blend_applied is False


def test_pipeline_odds_on_preserves_blend() -> None:
    raw = {"home_win": 42.0, "draw": 26.0, "away_win": 32.0}
    market = {"home_win": 20.0, "draw": 25.0, "away_win": 55.0}
    with patch("config.ODDS_AFFECT_PREDICTION", True):
        pipeline = finalize_probability_pipeline(
            home_team="Qatar",
            away_team="Canada",
            home_xg=1.8,
            away_xg=1.2,
            raw_probabilities_1x2=raw,
            top_scores=[{"score": "2-1", "probability": 10.0}],
            score_coverage=52.0,
            market_odds=market,
        )
    assert pipeline.final_probabilities_1x2 != raw
    assert pipeline.probability_result.odds_blend_applied is True


def test_calibration_disabled_identical_output() -> None:
    payload = {"home_team": "Argentina", "away_team": "France", "neutral_ground": True}
    with patch("config.PROBABILITY_CALIBRATION_ENABLED", False):
        first = client.post("/api/predict", json=payload).json()
        second = client.post("/api/predict", json=payload).json()
    assert first["probabilities_1x2"] == second["probabilities_1x2"]
    pd = first["probability_diagnostics"]
    assert pd["calibration_applied"] is False
    assert pd["calibration_enabled"] is False


def test_calibration_enabled_preserves_sum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.PROBABILITY_CALIBRATION_ENABLED", True)
    data = client.post(
        "/api/predict",
        json={"home_team": "Portugal", "away_team": "DR Congo", "neutral_ground": True},
    ).json()
    total = sum(data["probabilities_1x2"].values())
    assert 99.5 <= total <= 100.2
    pd = data["probability_diagnostics"]
    assert pd["calibration_enabled"] is True


def test_calibration_blocked_when_gate_fails() -> None:
    gate = CoherenceGateResult(passed=False, blocking_reasons=["TOP_SCORE_DIRECTION_MISMATCH"])
    with patch("config.PROBABILITY_CALIBRATION_ENABLED", True):
        probs, applied, reason = apply_probability_calibration(
            {"home_win": 55.0, "draw": 25.0, "away_win": 20.0},
            coherence_gate=gate,
        )
    assert applied is False
    assert reason is not None
    assert "coherence_gate_failed" in reason


def test_predict_includes_probability_coherence() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    ).json()
    assert "probability_coherence" in data
    pc = data["probability_coherence"]
    assert "passed" in pc
    assert "blocking_reasons" in pc
    assert data["probabilities_1x2"] == data["probability_diagnostics"]["final_probabilities_1x2"]


def test_explanations_align_with_final_probs_default_mode() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    probs = data["probabilities_1x2"]
    best_key = max(probs, key=probs.get)
    summary = data["match_summary"]
    if best_key == "home_win":
        assert "ניצחון" in summary
    assert data["probability_diagnostics"]["odds_blend_applied"] is False
