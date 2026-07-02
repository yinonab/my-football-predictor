"""xg_model_variant request routing — NR3 default parity + experimental candidate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from core.live_nr3_fcc_shadow_runner import NR3_FCC_SERVED_MODEL_VERSION
from core.matchup_relative_xg_v1 import (
    FUSION_IGNORE_REASON,
    build_matchup_shift_reason_codes,
)

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

BRAZIL_JAPAN = {
    **BASE_PAYLOAD,
    "home_team": "Brazil",
    "away_team": "Japan",
}

SWITZERLAND_ALGERIA = {
    **BASE_PAYLOAD,
    "home_team": "Switzerland",
    "away_team": "Algeria",
}

PORTUGAL_CROATIA = {
    **BASE_PAYLOAD,
    "home_team": "Portugal",
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
    assert "reason_codes" in rel


def test_matchup_failure_falls_back_to_nr3(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    nr3 = _predict({**BASE_PAYLOAD, "xg_model_variant": "nr3_fcc"})

    def _boom(**_kwargs):
        raise RuntimeError("matchup_relative_v1_test_failure")

    with patch(
        "core.matchup_relative_xg_v1.run_matchup_relative_v1_prediction",
        side_effect=_boom,
    ):
        fallback = _predict(
            {**BASE_PAYLOAD, "xg_model_variant": "matchup_relative_v1"}
        )

    assert _core_prediction_fields(fallback) == _core_prediction_fields(nr3)
    diag = fallback["model_diagnostics"]
    assert diag.get("model_variant_fallback") is True
    assert diag.get("requested_xg_model_variant") == "matchup_relative_v1"
    assert diag.get("active_xg_source") == "nr3_fcc"
    assert diag.get("model_variant") == "nr3_fcc"
    assert diag.get("fallback_reason")


def test_matchup_fusion_ignored_with_diagnostics(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    off = _predict(
        {
            **FRANCE_HAITI,
            "xg_model_variant": "matchup_relative_v1",
            "fusion_blowout_enabled": False,
        }
    )
    on = _predict(
        {
            **FRANCE_HAITI,
            "xg_model_variant": "matchup_relative_v1",
            "fusion_blowout_enabled": True,
        }
    )
    rel = on["model_diagnostics"]["matchup_relative_diagnostics"]
    assert rel["fusion_blowout_enabled"] is True
    assert rel["fusion_applied"] is False
    assert rel["fusion_ignored_for_model_variant"] is True
    assert rel["fusion_ignore_reason"] == FUSION_IGNORE_REASON
    assert rel["pre_fusion_xg"]
    assert rel["post_fusion_xg"]
    assert on["home_xg"] == off["home_xg"]
    assert on["away_xg"] == off["away_xg"]


def test_nr3_fusion_still_applies_when_enabled(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    off = _predict({**FRANCE_HAITI, "xg_model_variant": "nr3_fcc", "fusion_blowout_enabled": False})
    on = _predict({**FRANCE_HAITI, "xg_model_variant": "nr3_fcc", "fusion_blowout_enabled": True})
    assert on["home_xg"] != off["home_xg"] or on["away_xg"] != off["away_xg"]


def test_brazil_japan_large_delta_reason_codes(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**BRAZIL_JAPAN, "xg_model_variant": "matchup_relative_v1"})
    rel = data["model_diagnostics"]["matchup_relative_diagnostics"]
    codes = rel.get("reason_codes") or []
    assert "model_variant_experimental" in codes
    assert "MATCHUP_RELATIVE_LARGE_DELTA_FROM_NR3" in codes
    assert "large_delta_from_nr3" in codes


def test_build_matchup_shift_reason_codes_detects_favorite_flip():
    codes = build_matchup_shift_reason_codes(
        mr_home_xg=0.9,
        mr_away_xg=1.2,
        mr_probs={"home_win": 26.0, "draw": 33.0, "away_win": 41.0},
        feature_vector_summary={
            "attack_vs_defense_edges": {
                "favorite": 0.2,
                "underdog": 0.5,
            }
        },
        nr3_home_xg=1.3,
        nr3_away_xg=0.8,
        nr3_probs={"home_win": 46.0, "draw": 31.0, "away_win": 23.0},
    )
    assert "favorite_attack_edge_low" in codes
    assert "underdog_attack_edge_high" in codes
    assert "MATCHUP_RELATIVE_LARGE_DELTA_FROM_NR3" in codes


def _top_1x2_bucket(probs: dict) -> str:
    return max(("home_win", "draw", "away_win"), key=lambda k: float(probs[k]))


def _primary_outcome(primary: dict) -> str:
    h = int(primary["home_goals"])
    a = int(primary["away_goals"])
    if h > a:
        return "home_win"
    if a > h:
        return "away_win"
    return "draw"


def test_switzerland_algeria_primary_matches_top_1x2_bucket(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**SWITZERLAND_ALGERIA, "xg_model_variant": "matchup_relative_v1"})
    probs = data["probabilities_1x2"]
    primary = data["scoreline_decision"]["primary_predicted_score"]
    bucket = _top_1x2_bucket(probs)
    assert _primary_outcome(primary) == bucket
    if bucket != "draw":
        assert primary["home_goals"] != primary["away_goals"]


def test_portugal_croatia_clean_sheet_guard(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**PORTUGAL_CROATIA, "xg_model_variant": "matchup_relative_v1"})
    diag = data["model_diagnostics"]
    primary = data["scoreline_decision"]["primary_predicted_score"]
    is_clean_sheet = (
        int(primary["home_goals"]) > int(primary["away_goals"])
        and int(primary["away_goals"]) == 0
    ) or (
        int(primary["away_goals"]) > int(primary["home_goals"])
        and int(primary["home_goals"]) == 0
    )
    if is_clean_sheet:
        assert (
            diag.get("clean_sheet_primary_adjusted")
            or diag.get("clean_sheet_primary_warning")
        )
    assert diag.get("matchup_relative_xg_breakdown")
    assert diag.get("nr3_reference")


def test_nr3_diagnostics_still_returned(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    data = _predict({**BASE_PAYLOAD, "xg_model_variant": "nr3_fcc"})
    diag = data["model_diagnostics"]
    assert diag["model_variant"] == "nr3_fcc"
    assert diag.get("nr3_xg_decomposition")


def test_matchup_breakdown_diagnostics_returned(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict({**BASE_PAYLOAD, "xg_model_variant": "matchup_relative_v1"})
    diag = data["model_diagnostics"]
    breakdown = diag.get("matchup_relative_xg_breakdown") or {}
    assert breakdown.get("final_home_xg") == data["home_xg"]
    assert breakdown.get("final_away_xg") == data["away_xg"]
    assert "reason_codes" in breakdown
