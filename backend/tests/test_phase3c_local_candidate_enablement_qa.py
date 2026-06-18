"""Phase 3C — Local candidate enablement QA tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.activation_qa import (
    WARNING_BALANCED_MATCH_SHIFT,
    WARNING_FAVORITE_DIRECTION_REVERSED,
    WARNING_LARGE_CANDIDATE_SHIFT,
    WARNING_UNEXPECTED_FALLBACK,
    QAMatchup,
    analyze_prediction_result,
    balanced_match_shift_warning,
    classify_home_win_shift,
    collect_qa_warnings,
    favorite_direction_reversed,
    load_activation_qa_matchups,
    summarize_qa_analyses,
)
from core.external_rating_snapshots import list_production_team_names

PYTHON = sys.executable


def test_activation_qa_matchups_only_production_teams() -> None:
    production = set(list_production_team_names())
    matchups, skipped = load_activation_qa_matchups()
    assert len(matchups) >= 15
    for m in matchups:
        assert m.home in production, m.home
        assert m.away in production, m.away
    assert any(s.get("home") == "Serbia" for s in skipped)


def test_shift_classification() -> None:
    assert classify_home_win_shift(0.5) == "no_change"
    assert classify_home_win_shift(-0.9) == "no_change"
    assert classify_home_win_shift(1.5) == "small_shift"
    assert classify_home_win_shift(5.0) == "medium_shift"
    assert classify_home_win_shift(8.0) == "large_shift"
    assert classify_home_win_shift(-7.5) == "large_shift"


def test_large_shift_warning() -> None:
    warnings = collect_qa_warnings(
        baseline_probs={"home_win": 50.0, "draw": 25.0, "away_win": 25.0},
        active_probs={"home_win": 60.0, "draw": 20.0, "away_win": 20.0},
        delta_home_win=10.0,
        fallback=False,
        large_shift_pp=7.0,
    )
    assert WARNING_LARGE_CANDIDATE_SHIFT in warnings


def test_balanced_match_shift_warning() -> None:
    baseline = {"home_win": 38.0, "draw": 32.0, "away_win": 30.0}
    active = {"home_win": 46.0, "draw": 28.0, "away_win": 26.0}
    assert balanced_match_shift_warning(baseline, active, max_shift_pp=7.0) is True
    warnings = collect_qa_warnings(
        baseline_probs=baseline,
        active_probs=active,
        delta_home_win=8.0,
        fallback=False,
        large_shift_pp=7.0,
    )
    assert WARNING_BALANCED_MATCH_SHIFT in warnings


def test_favorite_direction_reversed_warning() -> None:
    baseline = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    active = {"home_win": 35.0, "draw": 25.0, "away_win": 40.0}
    assert favorite_direction_reversed(baseline, active) is True
    warnings = collect_qa_warnings(
        baseline_probs=baseline,
        active_probs=active,
        delta_home_win=-15.0,
        fallback=False,
    )
    assert WARNING_FAVORITE_DIRECTION_REVERSED in warnings


def test_unexpected_fallback_warning() -> None:
    warnings = collect_qa_warnings(
        baseline_probs={"home_win": 50.0, "draw": 25.0, "away_win": 25.0},
        active_probs={"home_win": 50.0, "draw": 25.0, "away_win": 25.0},
        delta_home_win=0.0,
        fallback=True,
    )
    assert WARNING_UNEXPECTED_FALLBACK in warnings


def test_analyze_prediction_result_shape() -> None:
    matchup = QAMatchup("test", "Test", "Brazil", "Morocco")
    prediction = {
        "baseline": {
            "probabilities_1x2": {"home_win": 46.8, "draw": 24.0, "away_win": 29.2},
            "home_xg": 1.5,
            "top_scores": ["1-0", "2-1"],
        },
        "active": {
            "probabilities_1x2": {"home_win": 45.4, "draw": 24.5, "away_win": 30.1},
            "home_xg": 1.48,
            "top_scores": ["1-0", "1-1"],
        },
        "model_diagnostics": {
            "model_version": config.ACTIVE_MODEL_VERSION,
            "fallback_to_baseline": False,
        },
    }
    row = analyze_prediction_result(matchup, prediction)
    assert row.delta_home_win == pytest.approx(-1.4, abs=0.01)
    assert row.shift_class == "small_shift"
    assert row.fallback is False


def test_summarize_recommendation_hold_on_fallback() -> None:
    from core.activation_qa import QAMatchupAnalysis

    analyses = [
        QAMatchupAnalysis(
            category="x",
            category_label="x",
            home="A",
            away="B",
            baseline_home_win=50,
            active_home_win=50,
            delta_home_win=0,
            baseline_draw=25,
            active_draw=25,
            baseline_away_win=25,
            active_away_win=25,
            baseline_xg=1.0,
            active_xg=1.0,
            baseline_top_scores="",
            active_top_scores="",
            fallback=True,
            warnings=[WARNING_UNEXPECTED_FALLBACK],
        )
    ]
    summary = summarize_qa_analyses(analyses)
    assert summary.fallback_count == 1
    assert summary.recommendation() == "hold"


def test_disabled_production_defaults_unchanged() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    assert config.MODEL_ACTIVATION_ENABLED is False
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False
    client = TestClient(app)
    r1 = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    )
    r2 = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    )
    assert r1.status_code == 200
    assert r1.json()["probabilities_1x2"] == r2.json()["probabilities_1x2"]
    md = r1.json().get("model_diagnostics") or {}
    assert md.get("activation_enabled") is False


def test_activation_qa_report_cli_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/activation_qa_report.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Activation QA summary" in proc.stdout
    assert "fallback count: 0" in proc.stdout


def test_smoke_predict_active_candidate_cli_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/smoke_predict_active_candidate.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
