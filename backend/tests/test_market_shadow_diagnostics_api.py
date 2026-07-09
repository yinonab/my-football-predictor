"""Phase 4A — shadow-only market diagnostics debug API tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVAL_CASES = json.loads((FIXTURES / "market_shadow_eval_cases.json").read_text(encoding="utf-8"))

NORWAY_ENGLAND_CASE = next(
    c for c in EVAL_CASES["cases"] if c["name"] == "norway_england_green"
)
STRONG_FAVORITE_CASE = next(
    c for c in EVAL_CASES["cases"] if c["name"] == "strong_favorite_under_btts_no"
)

NORWAY_ENGLAND_PAYLOAD = {
    "include_market_shadow_diagnostics": True,
    "home_team": NORWAY_ENGLAND_CASE["home_team"],
    "away_team": NORWAY_ENGLAND_CASE["away_team"],
    "model_primary_score": NORWAY_ENGLAND_CASE["model_primary_score"],
    "model_top_scores": NORWAY_ENGLAND_CASE["model_top_scores"],
    "model_score_matrix": NORWAY_ENGLAND_CASE["model_score_matrix"],
    "market_fixture": NORWAY_ENGLAND_CASE["fixture"],
}


@pytest.fixture
def shadow_diagnostics_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_MARKET_SHADOW_DIAGNOSTICS", "true")
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "config.market_shadow_diagnostics_enabled",
        lambda: True,
    )


@pytest.fixture
def shadow_diagnostics_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_MARKET_SHADOW_DIAGNOSTICS", "false")
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", False, raising=False)
    monkeypatch.setattr(
        "config.market_shadow_diagnostics_enabled",
        lambda: False,
    )


def test_env_disabled_returns_403(shadow_diagnostics_disabled) -> None:
    resp = client.post("/api/debug/market-shadow-diagnostics", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "market_shadow_diagnostics_disabled"


def test_env_enabled_request_flag_false_returns_400(shadow_diagnostics_enabled) -> None:
    payload = {**NORWAY_ENGLAND_PAYLOAD, "include_market_shadow_diagnostics": False}
    resp = client.post("/api/debug/market-shadow-diagnostics", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "diagnostics_not_requested"


def test_env_enabled_valid_fixture_returns_diagnostics(shadow_diagnostics_enabled) -> None:
    resp = client.post("/api/debug/market-shadow-diagnostics", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    block = data["market_shadow_diagnostics"]
    assert block["quality_band"] == "GREEN"
    assert block["market_favorite"] == "England"
    assert block["requested_shadow_weight_pct"] in (50, 60)
    assert block["shadow_top_scores"]
    assert "diagnostic_only_not_used_for_prediction" in block["notes"]
    assert block["source_fixture"] == "rapidapi_odds_feed_norway_england.json"
    assert block["model_primary_score_unchanged"] == "1-1"


def test_inline_market_works(shadow_diagnostics_enabled) -> None:
    case = STRONG_FAVORITE_CASE
    payload = {
        "include_market_shadow_diagnostics": True,
        "home_team": case["home_team"],
        "away_team": case["away_team"],
        "model_primary_score": case["model_primary_score"],
        "model_top_scores": case["model_top_scores"],
        "model_score_matrix": case["model_score_matrix"],
        "inline_market": case["inline_market"],
    }
    resp = client.post("/api/debug/market-shadow-diagnostics", json=payload)
    assert resp.status_code == 200
    block = resp.json()["market_shadow_diagnostics"]
    assert block["quality_band"] == "GREEN"
    assert block["source_fixture"] is None


def test_no_live_api_calls(shadow_diagnostics_enabled) -> None:
    lookup_mock = MagicMock(side_effect=AssertionError("live odds lookup must not run"))
    with patch("api.main._odds_client.lookup_match_market", lookup_mock):
        with patch("core.odds_ensemble.OddsClient.lookup_match_market", lookup_mock):
            resp = client.post("/api/debug/market-shadow-diagnostics", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 200
    lookup_mock.assert_not_called()


def test_no_api_keys_required(shadow_diagnostics_enabled, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    resp = client.post("/api/debug/market-shadow-diagnostics", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 200


def test_model_inputs_not_mutated(shadow_diagnostics_enabled) -> None:
    matrix = copy.deepcopy(NORWAY_ENGLAND_CASE["model_score_matrix"])
    top_scores = copy.deepcopy(NORWAY_ENGLAND_CASE["model_top_scores"])
    primary = NORWAY_ENGLAND_CASE["model_primary_score"]
    payload = {
        "include_market_shadow_diagnostics": True,
        "home_team": NORWAY_ENGLAND_CASE["home_team"],
        "away_team": NORWAY_ENGLAND_CASE["away_team"],
        "model_primary_score": primary,
        "model_top_scores": top_scores,
        "model_score_matrix": matrix,
        "market_fixture": NORWAY_ENGLAND_CASE["fixture"],
    }
    resp = client.post("/api/debug/market-shadow-diagnostics", json=payload)
    assert resp.status_code == 200
    assert matrix == NORWAY_ENGLAND_CASE["model_score_matrix"]
    assert top_scores == NORWAY_ENGLAND_CASE["model_top_scores"]
    assert primary == NORWAY_ENGLAND_CASE["model_primary_score"]


def test_effective_movement_display_safe_small_gap(shadow_diagnostics_enabled) -> None:
    case = STRONG_FAVORITE_CASE
    payload = {
        "include_market_shadow_diagnostics": True,
        "home_team": case["home_team"],
        "away_team": case["away_team"],
        "model_primary_score": case["model_primary_score"],
        "model_top_scores": case["model_top_scores"],
        "model_score_matrix": case["model_score_matrix"],
        "inline_market": case["inline_market"],
    }
    resp = client.post("/api/debug/market-shadow-diagnostics", json=payload)
    assert resp.status_code == 200
    fav = resp.json()["market_shadow_diagnostics"]["effective_movement"]["favorite_side"]
    assert fav is not None
    assert fav["display"] == "n/a-small-gap"
    assert fav["status"] == "small_gap"


def test_fixture_path_traversal_rejected(shadow_diagnostics_enabled) -> None:
    payload = {
        **NORWAY_ENGLAND_PAYLOAD,
        "market_fixture": "../secrets.json",
        "inline_market": None,
    }
    resp = client.post("/api/debug/market-shadow-diagnostics", json=payload)
    assert resp.status_code == 400


def test_health_exposes_shadow_flag(shadow_diagnostics_enabled) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["market_shadow_diagnostics_enabled"] is True


def test_predict_default_unchanged_no_shadow_block(shadow_diagnostics_enabled) -> None:
    resp = client.post(
        "/api/predict",
        json={
            "home_team": "Canada (קנדה)",
            "away_team": "Argentina (ארגנטינה)",
            "neutral_ground": True,
            "top_n": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert data["home_xg"] > 0
    assert data["away_xg"] > 0
    assert data["top_scores"]
    assert "scoreline_decision" in data
