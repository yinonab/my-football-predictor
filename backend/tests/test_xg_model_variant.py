"""xg_model_variant request routing — NR3 default parity + experimental candidate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from core.live_nr3_fcc_shadow_runner import NR3_FCC_SERVED_MODEL_VERSION

client = TestClient(app)

BASE_PAYLOAD = {
    "home_team": "France",
    "away_team": "Sweden",
    "neutral_ground": True,
    "include_diagnostics": True,
    "use_match_context": False,
    "odds_affect_prediction": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
}

FRANCE_HAITI = {
    **BASE_PAYLOAD,
    "home_team": "France",
    "away_team": "Haiti",
}

FRANCE_CROATIA = {
    **BASE_PAYLOAD,
    "home_team": "France",
    "away_team": "Croatia",
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
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enable_served(monkeypatch) -> None:
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: True)


def _core_prediction_fields(data: dict) -> dict:
    return {
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "probabilities_1x2": data["probabilities_1x2"],
        "primary_predicted_score": data["scoreline_decision"]["primary_predicted_score"],
        "top_scores": data["top_scores"],
    }


def test_missing_xg_model_variant_uses_nr3_parity(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    baseline = _predict(BASE_PAYLOAD)
    explicit = _predict({**BASE_PAYLOAD, "xg_model_variant": "nr3_fcc"})
    assert _core_prediction_fields(baseline) == _core_prediction_fields(explicit)
    assert baseline["model_diagnostics"]["model_variant"] == "nr3_fcc"
    assert baseline["model_diagnostics"]["active_xg_source"] == "nr3_fcc"


def test_nr3_fcc_explicit_matches_default(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    missing = _predict({k: v for k, v in BASE_PAYLOAD.items()})
    explicit = _predict({**BASE_PAYLOAD, "xg_model_variant": "nr3_fcc"})
    assert _core_prediction_fields(missing) == _core_prediction_fields(explicit)
    assert explicit["model_diagnostics"]["model_version"] == NR3_FCC_SERVED_MODEL_VERSION


def test_matchup_relative_v1_returns_full_prediction(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**BASE_PAYLOAD, "xg_model_variant": "matchup_relative_v1"})
    assert data["home_xg"] > 0
    assert data["away_xg"] > 0
    assert data["probabilities_1x2"]["home_win"] > 0
    assert data["scoreline_decision"]["primary_predicted_score"]
    assert len(data["top_scores"]) >= 1
    diag = data["model_diagnostics"]
    assert diag["active_xg_source"] == "matchup_relative_v1"
    assert diag["model_variant"] == "matchup_relative_v1"
    assert diag["model_version"] == "matchup_relative_xg_v1"


def test_no_mixed_model_outputs(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    nr3 = _predict({**BASE_PAYLOAD, "xg_model_variant": "nr3_fcc"})
    matchup = _predict({**BASE_PAYLOAD, "xg_model_variant": "matchup_relative_v1"})
    assert nr3 != matchup
    assert nr3["model_diagnostics"]["active_xg_source"] == "nr3_fcc"
    assert matchup["model_diagnostics"]["active_xg_source"] == "matchup_relative_v1"


def test_france_haiti_matchup_lowers_weak_underdog_xg(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    nr3 = _predict({**FRANCE_HAITI, "xg_model_variant": "nr3_fcc"})
    matchup = _predict({**FRANCE_HAITI, "xg_model_variant": "matchup_relative_v1"})
    assert matchup["away_xg"] < nr3["away_xg"]


def test_france_croatia_preserved_relative_to_haiti(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    nr3_haiti = _predict({**FRANCE_HAITI, "xg_model_variant": "nr3_fcc"})
    nr3_croatia = _predict({**FRANCE_CROATIA, "xg_model_variant": "nr3_fcc"})
    matchup_haiti = _predict(
        {**FRANCE_HAITI, "xg_model_variant": "matchup_relative_v1"}
    )
    matchup_croatia = _predict(
        {**FRANCE_CROATIA, "xg_model_variant": "matchup_relative_v1"}
    )
    nr3_gap = nr3_croatia["away_xg"] - nr3_haiti["away_xg"]
    matchup_gap = matchup_croatia["away_xg"] - matchup_haiti["away_xg"]
    assert matchup_gap >= nr3_gap - 0.05
    assert matchup_croatia["away_xg"] >= matchup_haiti["away_xg"]


def test_missing_ratings_degrade_safely(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    data = _predict(
        {
            **BASE_PAYLOAD,
            "home_team": "France",
            "away_team": "Haiti",
            "xg_model_variant": "matchup_relative_v1",
        }
    )
    assert data["home_xg"] > 0
    assert data["away_xg"] > 0
    assert data["probabilities_1x2"]["home_win"] > data["probabilities_1x2"]["away_win"]


def test_include_diagnostics_returns_variant_details(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**BASE_PAYLOAD, "xg_model_variant": "matchup_relative_v1"})
    diag = data["model_diagnostics"]
    assert diag["active_xg_source"] == "matchup_relative_v1"
    rel = diag.get("matchup_relative_diagnostics") or {}
    assert rel.get("feature_vector_summary")
    assert "suppression_applied" in rel
    assert "adaptive_floor_details" in rel
    assert "total_goals_guard" in rel
