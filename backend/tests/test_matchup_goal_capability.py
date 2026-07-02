"""Matchup goal capability diagnostics — additive shadow layer only."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from core.matchup_goal_capability import build_matchup_goal_capability
from core.scoreline_decision import ScorelineDecision, ScorelineCandidate

client = TestClient(app)

BELGIUM_SENEGAL = {
    "home_team": "Belgium",
    "away_team": "Senegal",
    "neutral_ground": True,
    "include_diagnostics": True,
    "use_match_context": False,
    "odds_affect_prediction": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
}

ENGLAND_DR_CONGO = {
    "home_team": "England",
    "away_team": "DR Congo",
    "neutral_ground": True,
    "include_diagnostics": True,
    "use_match_context": False,
    "odds_affect_prediction": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
}


@pytest.fixture(autouse=True)
def _default_flags(monkeypatch):
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: False)


@pytest.fixture
def production_model_activation(monkeypatch):
    monkeypatch.setattr(config, "MODEL_ACTIVATION_ENABLED", True)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True)


def _predict(payload: dict) -> dict:
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _enable_served(monkeypatch):
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: True)


def _mgc(data: dict) -> dict:
    diag = data.get("model_diagnostics") or {}
    mgc_payload = diag.get("matchup_goal_capability")
    assert mgc_payload is not None, "expected matchup_goal_capability"
    return mgc_payload


def test_matchup_goal_capability_only_with_diagnostics_flag(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    with_diag = _predict(BELGIUM_SENEGAL)
    without_diag = _predict({**BELGIUM_SENEGAL, "include_diagnostics": False})
    assert _mgc(with_diag)["home_team"] == "Belgium"
    assert (without_diag.get("model_diagnostics") or {}).get(
        "matchup_goal_capability"
    ) is None


def test_diagnostics_do_not_change_prediction_output(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    base_payload = {**BELGIUM_SENEGAL, "include_diagnostics": False}
    with_diag = _predict(BELGIUM_SENEGAL)
    without_diag = _predict(base_payload)
    for key in ("home_xg", "away_xg", "probabilities_1x2", "top_scores"):
        assert with_diag[key] == without_diag[key]
    sd_with = with_diag.get("scoreline_decision") or {}
    sd_without = without_diag.get("scoreline_decision") or {}
    assert sd_with.get("primary_predicted_score") == sd_without.get(
        "primary_predicted_score"
    )


def test_belgium_senegal_meaningful_underdog_and_clean_sheet_risk(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict(BELGIUM_SENEGAL)
    mgc = _mgc(data)
    assert mgc["underdog_goal_capability"] in ("MEDIUM", "HIGH")
    assert mgc["clean_sheet_risk"] in ("MEDIUM", "HIGH")
    assert mgc["probabilities"]["underdog_scores_probability"] >= 35.0
    assert "FAVORITE_CLEAN_SHEET_RISKY" in mgc["reason_codes"]


def test_england_dr_congo_meaningful_clean_sheet_risk(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict(ENGLAND_DR_CONGO)
    mgc = _mgc(data)
    assert mgc["clean_sheet_risk"] in ("LOW", "MEDIUM", "HIGH")
    assert mgc["favorite_goal_capability"] in ("LOW", "MEDIUM", "HIGH")
    assert mgc["summary"]["title"] == "יכולת הבקעה לפי מפגש"


def test_missing_inputs_degrade_safely():
    decision = ScorelineDecision(
        favorite_outcome="home",
        favorite_outcome_probability=55.0,
        second_outcome="draw",
        second_outcome_probability=25.0,
        outcome_margin=30.0,
        confidence_label="medium",
        primary_predicted_score=ScorelineCandidate(
            home_goals=2, away_goals=0, probability=12.0, outcome="home"
        ),
        primary_score_reason="test",
        top_exact_score_overall=None,
        top_exact_score_differs_from_primary=False,
    )
    payload = build_matchup_goal_capability(
        home_team="Team A",
        away_team="Team B",
        served_home_xg=1.5,
        served_away_xg=0.4,
        maher_reference_home_xg=None,
        maher_reference_away_xg=None,
        home_attack_rating=None,
        home_defense_rating=None,
        away_attack_rating=None,
        away_defense_rating=None,
        home_gf_per_game=None,
        home_ga_per_game=None,
        away_gf_per_game=None,
        away_ga_per_game=None,
        home_power=None,
        away_power=None,
        probabilities_1x2={"home_win": 60.0, "draw": 22.0, "away_win": 18.0},
        scoreline_decision=decision,
        active_model="test-model",
    )
    assert payload["home_goal_capability"] in ("LOW", "MEDIUM", "HIGH")
    assert payload["matchup_inputs"]["power_gap"] is None
    assert payload["matchup_inputs"]["home_attack_rating"] is None
    assert payload["probabilities"]["favorite_scores_2_plus_probability"] > 0.0
    assert payload["probabilities"]["btts_probability"] < payload["probabilities"]["underdog_scores_probability"]
