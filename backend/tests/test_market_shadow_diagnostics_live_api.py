"""Phase 5A — live provider fetch on debug diagnostics endpoint only."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.market_live_cache import reset_default_cache
from api.main import app

client = TestClient(app)

RAW_H2H_MARKET = {
    "id": 50679030,
    "market_name": "1X2",
    "period": "FULL_TIME",
    "placing": "PREMATCH",
    "bet_type": "BACK",
    "value": None,
    "market_books": [
        {
            "book": "BET365",
            "outcome_0": 4.09,
            "outcome_1": 3.7,
            "outcome_2": 1.85,
            "is_open": True,
        }
    ],
}

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVAL_CASES = json.loads((FIXTURES / "market_shadow_eval_cases.json").read_text(encoding="utf-8"))
NORWAY_ENGLAND_CASE = next(
    c for c in EVAL_CASES["cases"] if c["name"] == "norway_england_green"
)

BASE_MATRIX = NORWAY_ENGLAND_CASE["model_score_matrix"]
BASE_TOP = NORWAY_ENGLAND_CASE["model_top_scores"]


def _base_payload(**overrides) -> dict:
    payload = {
        "include_market_shadow_diagnostics": True,
        "home_team": "Norway",
        "away_team": "England",
        "model_primary_score": "1-1",
        "model_top_scores": BASE_TOP,
        "model_score_matrix": BASE_MATRIX,
    }
    payload.update(overrides)
    return payload


def _live_payload(**overrides) -> dict:
    payload = _base_payload(
        market_source="live",
        provider="rapidapi_odds_feed",
        provider_event_id="619963",
    )
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _clear_live_cache() -> None:
    reset_default_cache()
    yield
    reset_default_cache()


@pytest.fixture
def shadow_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", True, raising=False)
    monkeypatch.setattr("config.market_shadow_diagnostics_enabled", lambda: True)


@pytest.fixture
def shadow_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_SHADOW_DIAGNOSTICS_ENABLED", False, raising=False)
    monkeypatch.setattr("config.market_shadow_diagnostics_enabled", lambda: False)


@pytest.fixture
def live_fetch_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_LIVE_PROVIDER_FETCH_ENABLED", True, raising=False)
    monkeypatch.setattr("config.market_live_provider_fetch_enabled", lambda: True)


@pytest.fixture
def live_fetch_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.MARKET_LIVE_PROVIDER_FETCH_ENABLED", False, raising=False)
    monkeypatch.setattr("config.market_live_provider_fetch_enabled", lambda: False)


def test_health_live_fetch_flag_default_false(shadow_disabled) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["market_live_provider_fetch_enabled"] is False


def test_debug_live_request_with_shadow_disabled_returns_403(shadow_disabled) -> None:
    resp = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "market_shadow_diagnostics_disabled"


def test_debug_live_request_with_live_flag_off_does_not_call_provider(
    shadow_enabled, live_fetch_disabled
) -> None:
    with patch("core.providers.rapidapi_odds_feed_client.fetch_event_markets") as fetch_mock:
        resp = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "market_live_provider_fetch_disabled"
    fetch_mock.assert_not_called()


def test_debug_live_missing_key_returns_safe_error(
    shadow_enabled, live_fetch_enabled, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with patch(
        "core.providers.rapidapi_odds_feed_client.rapidapi_key",
        return_value="",
    ):
        resp = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "rapidapi_key_not_configured"
    body = json.dumps(resp.json())
    assert "RAPIDAPI_KEY" not in body


def test_debug_live_mocked_response_returns_diagnostics_block(
    shadow_enabled, live_fetch_enabled
) -> None:
    mock_payload = {
        "provider": "rapidapi_odds_feed",
        "event_id": "619963",
        "placing": "PREMATCH",
        "http_status": 200,
        "markets": [RAW_H2H_MARKET],
    }
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=mock_payload,
    ) as fetch_mock:
        resp = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    assert resp.status_code == 200
    fetch_mock.assert_called_once_with("619963")
    block = resp.json()["market_shadow_diagnostics"]
    assert block["market_source"] == "live"
    assert block["provider"] == "rapidapi_odds_feed"
    assert block["provider_event_id"] == "619963"
    assert block["source_fixture"] is None
    assert block["cache_status"] == "miss"
    assert block["provider_call_count"] == 1
    assert "diagnostic_only_not_used_for_prediction" in block["notes"]
    assert "live_provider_fetch_used_for_diagnostics_only" in block["notes"]
    assert block["quality_band"] in ("GREEN", "YELLOW", "RED")


def test_debug_live_invalid_provider_rejected(shadow_enabled, live_fetch_enabled) -> None:
    resp = client.post(
        "/api/debug/market-shadow-diagnostics",
        json=_live_payload(provider="the_odds_api"),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unsupported_provider"


def test_debug_live_provider_event_id_required(shadow_enabled, live_fetch_enabled) -> None:
    resp = client.post(
        "/api/debug/market-shadow-diagnostics",
        json=_live_payload(provider_event_id=""),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "provider_event_id_required"


def test_debug_exactly_one_source_rule(shadow_enabled, live_fetch_enabled) -> None:
    resp = client.post(
        "/api/debug/market-shadow-diagnostics",
        json=_live_payload(market_fixture="rapidapi_odds_feed_norway_england.json"),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "exactly_one_market_source_required"


def test_predict_default_unchanged_no_live_fetch(
    shadow_enabled, live_fetch_enabled
) -> None:
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "Canada (קנדה)",
                "away_team": "Argentina (ארגנטינה)",
                "neutral_ground": True,
                "use_match_context": False,
                "top_n": 3,
                "include_market_shadow_diagnostics": True,
                "market_source": "live",
                "provider": "rapidapi_odds_feed",
                "provider_event_id": "619963",
            },
        )
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" not in resp.json()
    fetch_mock.assert_not_called()


def test_debug_live_cache_hit_avoids_second_provider_call(
    shadow_enabled, live_fetch_enabled
) -> None:
    mock_payload = {
        "provider": "rapidapi_odds_feed",
        "event_id": "619963",
        "placing": "PREMATCH",
        "http_status": 200,
        "markets": [RAW_H2H_MARKET],
    }
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=mock_payload,
    ) as fetch_mock:
        first = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
        second = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    fetch_mock.assert_called_once_with("619963")
    second_block = second.json()["market_shadow_diagnostics"]
    assert second_block["cache_status"] == "hit"
    assert second_block["provider_call_count"] == 0


def test_debug_live_cache_metadata_on_miss(shadow_enabled, live_fetch_enabled) -> None:
    mock_payload = {
        "provider": "rapidapi_odds_feed",
        "event_id": "619963",
        "placing": "PREMATCH",
        "http_status": 200,
        "markets": [RAW_H2H_MARKET],
    }
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=mock_payload,
    ):
        resp = client.post("/api/debug/market-shadow-diagnostics", json=_live_payload())
    block = resp.json()["market_shadow_diagnostics"]
    assert block["cache_status"] == "miss"
    assert block["provider_call_count"] == 1
    assert block["provider"] == "rapidapi_odds_feed"
    assert "diagnostic_only_not_used_for_prediction" in block["notes"]
