"""Phase 4H — coherence gate, odds safety, calibration readiness, audit helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

PYTHON = sys.executable

from api.main import app
from core.probability_calibration_runtime import maybe_apply_probability_calibration
from core.probability_coherence import (
    FAVORITE_PROBABILITY_XG_MISMATCH,
    ODDS_BLEND_1X2_SCORELINE_MISMATCH,
    TOP_SCORE_DIRECTION_MISMATCH,
    build_coherence_warnings,
)
from core.probability_coherence_audit import (
    ROOT_CAUSE_COHERENT,
    ROOT_CAUSE_ODDS_BLEND,
    build_audit_row_from_predict_response,
    infer_likely_root_cause,
)
from core.probability_coherence_gate import (
    ADVISORY_NEAR_BALANCED,
    evaluate_coherence_gate,
)
from core.probability_result import build_probability_result
from fastapi.testclient import TestClient

client = TestClient(app)


def _build_result(
    *,
    raw: dict[str, float],
    final: dict[str, float] | None = None,
    home_xg: float = 1.8,
    away_xg: float = 1.2,
    top_scores: list | None = None,
    odds_available: bool = False,
    odds_affect_prediction: bool = False,
    market: dict[str, float] | None = None,
) -> object:
    final_probs = final if final is not None else raw
    return build_probability_result(
        home_team="Qatar",
        away_team="Canada",
        home_xg=home_xg,
        away_xg=away_xg,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final_probs,
        top_scores=top_scores or [{"score": "2-1", "probability": 11.0}],
        score_coverage=52.0,
        market_probabilities_1x2=market,
        odds_available=odds_available,
        odds_affect_prediction=odds_affect_prediction,
    )


def test_qatar_canada_style_odds_blend_mismatch_triggers_gate_failure() -> None:
    raw = {"home_win": 42.0, "draw": 26.0, "away_win": 32.0}
    final = {"home_win": 23.0, "draw": 25.4, "away_win": 51.7}
    market = {"home_win": 20.0, "draw": 25.0, "away_win": 55.0}
    result = build_probability_result(
        home_team="Qatar",
        away_team="Canada",
        home_xg=1.8,
        away_xg=1.2,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        top_scores=[
            {"score": "2-1", "probability": 10.0},
            {"score": "1-1", "probability": 9.0},
            {"score": "2-0", "probability": 8.0},
        ],
        score_coverage=52.0,
        market_probabilities_1x2=market,
        odds_available=True,
        odds_affect_prediction=True,
    )
    gate = evaluate_coherence_gate(result)
    assert gate.passed is False
    assert FAVORITE_PROBABILITY_XG_MISMATCH in gate.blocking_reasons
    assert TOP_SCORE_DIRECTION_MISMATCH in gate.blocking_reasons
    assert ODDS_BLEND_1X2_SCORELINE_MISMATCH in gate.blocking_reasons


def test_multiple_mismatch_cases_detected_by_audit_helper() -> None:
    payload = {
        "home_team": "Qatar",
        "away_team": "Canada",
        "home_xg": 1.8,
        "away_xg": 1.2,
        "top_scores": [{"score": "2-1", "probability": 10.0}],
        "score_coverage": {"achieved_percent": 52.0},
        "probabilities_1x2": {"home_win": 23.0, "draw": 25.4, "away_win": 51.7},
        "probability_diagnostics": {
            "raw_probabilities_1x2": {"home_win": 42.0, "draw": 26.0, "away_win": 32.0},
            "final_probabilities_1x2": {"home_win": 23.0, "draw": 25.4, "away_win": 51.7},
            "odds_available": True,
            "odds_affect_prediction": True,
            "odds_blend_applied": True,
            "market_probabilities_1x2": {"home_win": 20.0, "draw": 25.0, "away_win": 55.0},
            "probability_sum_valid": True,
            "probability_sum": 100.1,
            "coherence_warnings": [
                FAVORITE_PROBABILITY_XG_MISMATCH,
                TOP_SCORE_DIRECTION_MISMATCH,
                ODDS_BLEND_1X2_SCORELINE_MISMATCH,
            ],
        },
    }
    row = build_audit_row_from_predict_response(payload, scenario="test")
    assert row.gate_passed is False
    assert row.likely_root_cause == ROOT_CAUSE_ODDS_BLEND


def test_coherent_prediction_passes_gate() -> None:
    probs = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    result = _build_result(
        raw=probs,
        home_xg=2.0,
        away_xg=1.0,
        top_scores=[{"score": "2-1", "probability": 12.0}],
    )
    gate = evaluate_coherence_gate(result)
    assert gate.passed is True
    assert gate.blocking_reasons == []


def test_near_balanced_prediction_not_over_blocked() -> None:
    probs = {"home_win": 38.0, "draw": 33.0, "away_win": 29.0}
    result = _build_result(
        raw=probs,
        home_xg=1.45,
        away_xg=1.40,
        top_scores=[{"score": "1-1", "probability": 11.0}],
    )
    gate = evaluate_coherence_gate(result)
    assert gate.passed is True
    assert ADVISORY_NEAR_BALANCED in gate.advisory_reasons


def test_invalid_probability_sum_fails_gate() -> None:
    probs = {"home_win": 50.0, "draw": 30.0, "away_win": 10.0}
    result = _build_result(raw=probs, final=probs)
    gate = evaluate_coherence_gate(result)
    assert gate.passed is False


def test_top_scores_direction_mismatch_detected_conservatively() -> None:
    warnings = build_coherence_warnings(
        raw_probabilities_1x2={"home_win": 60.0, "draw": 22.0, "away_win": 18.0},
        final_probabilities_1x2={"home_win": 60.0, "draw": 22.0, "away_win": 18.0},
        home_xg=0.9,
        away_xg=2.1,
        top_scores=[{"score": "0-2", "probability": 12.0}],
        odds_blend_applied=False,
    )
    assert TOP_SCORE_DIRECTION_MISMATCH in warnings


def test_odds_affect_prediction_false_keeps_model_probs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.ODDS_AFFECT_PREDICTION", False)
    market = {"home_win": 20.0, "draw": 25.0, "away_win": 55.0}
    with patch("api.main._odds_client.fetch_match_odds", return_value=market):
        data = client.post(
            "/api/predict",
            json={"home_team": "Qatar", "away_team": "Canada", "neutral_ground": True},
        ).json()
    pd = data["probability_diagnostics"]
    assert pd["odds_available"] is True
    assert pd["odds_affect_prediction"] is False
    assert pd["odds_blend_applied"] is False
    assert data["probabilities_1x2"] == pd["raw_probabilities_1x2"]
    assert data["probabilities_1x2"] == pd["final_probabilities_1x2"]


def test_odds_affect_prediction_false_still_shows_market_in_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("config.ODDS_AFFECT_PREDICTION", False)
    market = {"home_win": 30.0, "draw": 30.0, "away_win": 40.0}
    with patch("api.main._odds_client.fetch_match_odds", return_value=market):
        data = client.post(
            "/api/predict",
            json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
        ).json()
    pd = data["probability_diagnostics"]
    assert pd["market_probabilities_1x2"] == market


def test_odds_affect_prediction_true_preserves_blend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.ODDS_AFFECT_PREDICTION", True)
    market = {"home_win": 20.0, "draw": 25.0, "away_win": 55.0}
    with patch("api.main._odds_client.fetch_match_odds", return_value=market):
        data = client.post(
            "/api/predict",
            json={"home_team": "Qatar", "away_team": "Canada", "neutral_ground": True},
        ).json()
    pd = data["probability_diagnostics"]
    assert pd["odds_affect_prediction"] is True
    assert pd["odds_blend_applied"] is True
    assert data["probabilities_1x2"] != pd["raw_probabilities_1x2"]
    assert "probability_coherence" in data
    if not data["probability_coherence"]["passed"]:
        assert data["probability_coherence"]["blocking_reasons"]


def test_probability_diagnostics_odds_flags_present() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    pd = data["probability_diagnostics"]
    for key in ("odds_available", "odds_affect_prediction", "odds_blend_applied"):
        assert key in pd


def test_api_home_draw_away_semantics() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    ).json()
    assert data["home_team"] == "Brazil"
    assert data["away_team"] == "Morocco"
    probs = data["probabilities_1x2"]
    assert set(probs.keys()) == {"home_win", "draw", "away_win"}
    assert data["probability_diagnostics"]["final_probabilities_1x2"]["home_win"] == probs["home_win"]


def test_flutter_mapping_documented_in_score_format() -> None:
    score_format = BACKEND_ROOT.parent / "mobile" / "lib" / "utils" / "score_format.dart"
    text = score_format.read_text(encoding="utf-8")
    assert "teamAName" in text
    assert "homeGoals" in text
    assert "awayGoals" in text


def test_probability_calibration_defaults_false() -> None:
    import config

    assert config.PROBABILITY_CALIBRATION_ENABLED is False


def test_calibration_disabled_predict_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.PROBABILITY_CALIBRATION_ENABLED", False)
    payload = {"home_team": "Argentina", "away_team": "France", "neutral_ground": True}
    first = client.post("/api/predict", json=payload).json()
    second = client.post("/api/predict", json=payload).json()
    assert first["probabilities_1x2"] == second["probabilities_1x2"]


def test_calibration_enabled_applies_temperature_and_valid_sum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("config.PROBABILITY_CALIBRATION_ENABLED", True)
    monkeypatch.setattr("config.PROBABILITY_CALIBRATION_TEMPERATURE", 1.35)
    data = client.post(
        "/api/predict",
        json={"home_team": "Portugal", "away_team": "DR Congo", "neutral_ground": True},
    ).json()
    total = (
        data["probabilities_1x2"]["home_win"]
        + data["probabilities_1x2"]["draw"]
        + data["probabilities_1x2"]["away_win"]
    )
    assert 99.5 <= total <= 100.2


def test_calibration_skipped_when_coherence_gate_fails() -> None:
    from core.probability_coherence_gate import CoherenceGateResult

    probs = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    gate = CoherenceGateResult(
        passed=False,
        blocking_reasons=["FAVORITE_PROBABILITY_XG_MISMATCH"],
    )
    with patch("config.PROBABILITY_CALIBRATION_ENABLED", True):
        out, applied = maybe_apply_probability_calibration(probs, coherence_gate=gate)
    assert applied is False
    assert out == probs


def test_infer_root_cause_coherent_when_gate_passes() -> None:
    from core.probability_coherence_gate import CoherenceGateResult

    gate = CoherenceGateResult(passed=True, advisory_reasons=["NEAR_BALANCED_MATCH"])
    assert (
        infer_likely_root_cause(
            odds_blend_applied=False,
            coherence_warnings=[],
            gate=gate,
        )
        == "near_balanced_advisory"
    )


def test_explanations_mention_odds_when_blend_applied() -> None:
    from core.explanations import ExplanationContext, explain_outcome_1x2

    text = explain_outcome_1x2(
        "away",
        51.7,
        home_power=100,
        away_power=120,
        home_xg=1.8,
        away_xg=1.2,
        home_team="Qatar",
        away_team="Canada",
        explanation_context=ExplanationContext(odds_blend_applied=True),
    )
    assert "שוק הימורים" in text


def test_audit_script_smoke() -> None:
    out_md = BACKEND_ROOT / "reports" / "_test_coherence_audit_smoke.md"
    out_csv = BACKEND_ROOT / "reports" / "_test_coherence_audit_smoke.csv"
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/audit_probability_coherence.py",
            "--skip-live",
            "--markdown",
            str(out_md),
            "--csv",
            str(out_csv),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_md.exists()
    out_md.unlink(missing_ok=True)
    out_csv.unlink(missing_ok=True)
