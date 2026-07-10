"""Phase 5C — optional live/cached market_shadow_diagnostics append on /api/predict."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.market_live_cache import reset_default_cache

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

MOCK_PROVIDER_PAYLOAD = {
    "provider": "rapidapi_odds_feed",
    "event_id": "619963",
    "placing": "PREMATCH",
    "http_status": 200,
    "markets": [RAW_H2H_MARKET],
}

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


def _live_payload(**overrides) -> dict:
    payload = {
        **BASELINE_PAYLOAD,
        "include_market_shadow_diagnostics": True,
        "market_source": "live",
        "provider": "rapidapi_odds_feed",
        "provider_event_id": "619963",
    }
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


def test_predict_default_unchanged_no_diagnostics(shadow_disabled) -> None:
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" not in resp.json()
    fetch_mock.assert_not_called()


def test_predict_include_false_with_live_fields_no_provider_call(
    shadow_enabled, live_fetch_enabled
) -> None:
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json=_live_payload(include_market_shadow_diagnostics=False),
        )
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" not in resp.json()
    fetch_mock.assert_not_called()


def test_predict_env_flags_off_with_live_fields(
    shadow_disabled, live_fetch_disabled
) -> None:
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" not in resp.json()
    fetch_mock.assert_not_called()


def test_predict_shadow_on_live_off_with_live_fields(
    shadow_enabled, live_fetch_disabled
) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline
    fetch_mock.assert_not_called()


def test_predict_live_cache_miss_appends_diagnostics(
    shadow_enabled, live_fetch_enabled
) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    fetch_mock.assert_called_once_with("619963")
    data = resp.json()
    assert _core_snapshot(data) == baseline
    block = data["market_shadow_diagnostics"]
    assert block["market_source"] == "live"
    assert block["cache_status"] == "miss"
    assert block["provider_call_count"] == 1
    assert "diagnostic_only_not_used_for_prediction" in block["notes"]


def test_predict_live_cache_hit_avoids_second_provider_call(
    shadow_enabled, live_fetch_enabled
) -> None:
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        first = client.post("/api/predict", json=_live_payload())
        second = client.post("/api/predict", json=_live_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    fetch_mock.assert_called_once_with("619963")
    block = second.json()["market_shadow_diagnostics"]
    assert block["cache_status"] == "hit"
    assert block["provider_call_count"] == 0


def test_predict_live_ttl_zero_cache_disabled(
    shadow_enabled, live_fetch_enabled, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("config.MARKET_LIVE_FETCH_CACHE_TTL_SECONDS", 0, raising=False)
    monkeypatch.setattr("config.market_live_fetch_cache_ttl_seconds", lambda: 0)
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        first = client.post("/api/predict", json=_live_payload())
        second = client.post("/api/predict", json=_live_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    assert fetch_mock.call_count == 2
    assert first.json()["market_shadow_diagnostics"]["cache_status"] == "disabled"
    assert second.json()["market_shadow_diagnostics"]["cache_status"] == "disabled"


def test_predict_live_max_calls_zero_diagnostics_absent(
    shadow_enabled, live_fetch_enabled, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("config.MARKET_LIVE_FETCH_MAX_CALLS_PER_REQUEST", 0, raising=False)
    monkeypatch.setattr("config.market_live_fetch_max_calls_per_request", lambda: 0)
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline
    fetch_mock.assert_not_called()


def test_predict_live_provider_error_prediction_succeeds(
    shadow_enabled, live_fetch_enabled, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.providers.rapidapi_odds_feed_client import RapidApiOddsFeedClientError

    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        side_effect=RapidApiOddsFeedClientError("rapidapi_auth_failed"),
    ):
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert "market_shadow_diagnostics" not in data
    assert _core_snapshot(data) == baseline
    assert "rapidapi_auth_failed" not in json.dumps(data)


def test_predict_fixture_append_still_works(shadow_enabled, live_fetch_disabled) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
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
    assert data["market_shadow_diagnostics"]["source_fixture"]
    fetch_mock.assert_not_called()


def test_predict_no_api_keys_required_for_live_append(
    shadow_enabled, live_fetch_enabled, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ):
        resp = client.post("/api/predict", json=_live_payload())
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" in resp.json()
