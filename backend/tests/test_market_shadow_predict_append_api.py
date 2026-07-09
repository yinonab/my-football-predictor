"""Phase 4B — optional market_shadow_diagnostics append on /api/predict."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVAL_CASES = json.loads((FIXTURES / "market_shadow_eval_cases.json").read_text(encoding="utf-8"))
NORWAY_ENGLAND_CASE = next(
    c for c in EVAL_CASES["cases"] if c["name"] == "norway_england_green"
)

BASELINE_PAYLOAD = {
    "home_team": "Canada (קנדה)",
    "away_team": "Argentina (ארגנטינה)",
    "neutral_ground": True,
    "use_match_context": False,
    "top_n": 3,
}


def _core_snapshot(data: dict) -> dict:
    scoreline = data.get("scoreline_decision") or {}
    return {
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "probabilities_1x2": data["probabilities_1x2"],
        "top_scores": data["top_scores"],
        "primary_predicted_score": scoreline.get("primary_predicted_score"),
        "primary_score_reason": scoreline.get("primary_score_reason"),
    }


@pytest.fixture
def shadow_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", True, raising=False)
    monkeypatch.setattr("config.market_shadow_diagnostics_enabled", lambda: True)


@pytest.fixture
def shadow_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", False, raising=False)
    monkeypatch.setattr("config.market_shadow_diagnostics_enabled", lambda: False)


def test_predict_default_response_unchanged(shadow_disabled) -> None:
    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    baseline = _core_snapshot(data)
    assert baseline["home_xg"] > 0
    assert baseline["top_scores"]


def test_predict_env_off_request_on_no_block(shadow_disabled) -> None:
    baseline_resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert baseline_resp.status_code == 200
    baseline = _core_snapshot(baseline_resp.json())

    resp = client.post(
        "/api/predict",
        json={
            **BASELINE_PAYLOAD,
            "include_market_shadow_diagnostics": True,
            "market_shadow_fixture": NORWAY_ENGLAND_CASE["fixture"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline


def test_predict_env_on_request_off_no_block(shadow_enabled) -> None:
    baseline_resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert baseline_resp.status_code == 200
    baseline = _core_snapshot(baseline_resp.json())

    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline


def test_predict_env_on_request_on_with_fixture_appends_block(shadow_enabled) -> None:
    baseline_resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert baseline_resp.status_code == 200
    baseline = _core_snapshot(baseline_resp.json())

    resp = client.post(
        "/api/predict",
        json={
            **BASELINE_PAYLOAD,
            "include_market_shadow_diagnostics": True,
            "market_shadow_fixture": NORWAY_ENGLAND_CASE["fixture"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert _core_snapshot(data) == baseline
    block = data["market_shadow_diagnostics"]
    assert block["quality_band"] == "GREEN"
    assert block["source_fixture"] == "rapidapi_odds_feed_norway_england.json"
    assert "diagnostic_only_not_used_for_prediction" in block["notes"]


def test_predict_env_on_request_on_without_snapshot_no_block(shadow_enabled) -> None:
    baseline_resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    baseline = _core_snapshot(baseline_resp.json())

    resp = client.post(
        "/api/predict",
        json={**BASELINE_PAYLOAD, "include_market_shadow_diagnostics": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline


def test_predict_no_live_provider_calls_for_shadow(shadow_enabled) -> None:
    import core.market_shadow_api as msa

    with patch(
        "core.market_shadow_api.build_market_shadow_diagnostics",
        wraps=msa.build_market_shadow_diagnostics,
    ) as shadow_build:
        with patch("requests.get", side_effect=AssertionError("requests.get must not run")):
            with patch("httpx.get", side_effect=AssertionError("httpx.get must not run")):
                resp = client.post(
                    "/api/predict",
                    json={
                        **BASELINE_PAYLOAD,
                        "include_market_shadow_diagnostics": True,
                        "market_shadow_fixture": NORWAY_ENGLAND_CASE["fixture"],
                    },
                )
    assert resp.status_code == 200
    assert resp.json()["market_shadow_diagnostics"]["source_fixture"]
    shadow_build.assert_called_once()


def test_predict_no_api_keys_required(shadow_enabled, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    resp = client.post(
        "/api/predict",
        json={
            **BASELINE_PAYLOAD,
            "include_market_shadow_diagnostics": True,
            "market_shadow_fixture": NORWAY_ENGLAND_CASE["fixture"],
        },
    )
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" in resp.json()


@pytest.mark.parametrize(
    "bad_fixture",
    ["../secrets.json", "oddspapi_wc_odds_sample.json"],
)
def test_predict_invalid_fixture_does_not_fail_prediction(
    shadow_enabled, bad_fixture: str
) -> None:
    baseline = _core_snapshot(
        client.post("/api/predict", json=BASELINE_PAYLOAD).json()
    )
    resp = client.post(
        "/api/predict",
        json={
            **BASELINE_PAYLOAD,
            "include_market_shadow_diagnostics": True,
            "market_shadow_fixture": bad_fixture,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline


def test_predict_response_schema_default_omits_null_diagnostics(shadow_disabled) -> None:
    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" not in resp.json()
