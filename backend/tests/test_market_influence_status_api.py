"""Phase 1 — market_influence_status observability on /api/predict."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_influence import map_resolver_match_reason
from core.market_live_cache import reset_default_cache
from core.market_event_resolver_cache import reset_default_resolver_cache
from core.market_live_fetch import LiveFetchResult
from core.providers.rapidapi_odds_feed_client import RapidApiOddsFeedClientError

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GREEN_AUDIT = json.loads(
    (FIXTURES / "rapidapi_odds_feed_norway_england.json").read_text(encoding="utf-8")
)

BASELINE_PAYLOAD = {
    "home_team": "Canada (קנדה)",
    "away_team": "Argentina (ארגנטינה)",
    "neutral_ground": True,
    "use_match_context": False,
    "top_n": 3,
}

NORWAY_ENGLAND_PAYLOAD = {
    "home_team": "Norway",
    "away_team": "England",
    "neutral_ground": True,
    "use_match_context": False,
    "top_n": 3,
}


def _event(event_id: int, home: str, away: str) -> dict:
    return {
        "id": event_id,
        "status": "SCHEDULED",
        "team_home": {"name": home},
        "team_away": {"name": away},
    }


def _live_fetch_result(audit: dict) -> LiveFetchResult:
    return LiveFetchResult(
        audit_report=audit,
        cache_status="miss",
        provider_call_count=1,
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    reset_default_cache()
    reset_default_resolver_cache()
    yield
    reset_default_cache()
    reset_default_resolver_cache()


@pytest.fixture
def influence_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_INFLUENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_influence_enabled", lambda: False)


@pytest.fixture
def all_influence_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_INFLUENCE_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_influence_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_SHADOW_DIAGNOSTICS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_shadow_diagnostics_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_LIVE_PROVIDER_FETCH_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_live_provider_fetch_enabled", lambda: True)


@pytest.fixture
def auto_resolver_on(monkeypatch: pytest.MonkeyPatch, all_influence_gates: None) -> None:
    monkeypatch.setattr(config, "MARKET_AUTO_EVENT_RESOLVER_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_auto_event_resolver_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_PROVIDER_EVENT_MAP_JSON", "{}", raising=False)
    monkeypatch.setattr(config, "load_market_provider_event_map", lambda: {})


def test_map_resolver_match_reason() -> None:
    assert map_resolver_match_reason("no_match") == "resolver_no_match"
    assert map_resolver_match_reason("ambiguous_forward") == "resolver_ambiguous"
    assert map_resolver_match_reason("outside_window") == "resolver_outside_window"
    assert map_resolver_match_reason("provider_error") == "provider_event_id_missing"


def test_influence_off_omits_status_block(influence_off) -> None:
    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence_status" not in data
    assert "market_influence" not in data


def test_provider_disabled_status(all_influence_gates, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_SHADOW_DIAGNOSTICS_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_shadow_diagnostics_enabled", lambda: False)
    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    status = resp.json()["market_influence_status"]
    assert status["attempted"] is False
    assert status["applied"] is False
    assert status["reason"] == "provider_disabled"
    assert "market_influence" not in resp.json()


def test_explicit_event_id_applied_status(all_influence_gates) -> None:
    with patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    data = resp.json()
    influence = data["market_influence"]
    status = data["market_influence_status"]
    assert influence["market_influence_applied"] is True
    assert influence["provider_event_id"] == "619963"
    assert influence["quality_band"] == "GREEN"
    assert status["attempted"] is True
    assert status["applied"] is True
    assert status["reason"] == "applied"
    assert status["provider"] == "rapidapi_odds_feed"
    assert status["provider_event_id"] == "619963"
    assert status["resolver_window_hours"] == config.market_event_resolver_lookahead_hours()


def test_resolver_no_match_app_style_status(auto_resolver_on) -> None:
    events = [_event(1, "France", "Germany")]
    with patch("core.market_event_resolver.fetch_events_in_match_window", return_value=events):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence" not in data
    status = data["market_influence_status"]
    assert status["attempted"] is True
    assert status["applied"] is False
    assert status["reason"] == "resolver_no_match"
    assert status["provider"] == "rapidapi_odds_feed"
    assert status["provider_event_id"] is None


def test_resolver_ambiguous_status(auto_resolver_on) -> None:
    events = [
        _event(1, "Canada", "Argentina"),
        _event(2, "Canada", "Argentina"),
    ]
    with patch("core.market_event_resolver.fetch_events_in_match_window", return_value=events):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    status = resp.json()["market_influence_status"]
    assert status["reason"] == "resolver_ambiguous"


def test_live_fetch_failed_status(all_influence_gates) -> None:
    from core.market_live_fetch import MarketLiveFetchError

    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        side_effect=MarketLiveFetchError("rapidapi_rate_limited"),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    status = resp.json()["market_influence_status"]
    assert status["reason"] == "live_fetch_failed"
    assert status["provider_event_id"] == "619963"
    assert "rapidapi_rate_limited" not in json.dumps(resp.json())


def test_no_secrets_or_raw_payload_in_status(auto_resolver_on) -> None:
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        side_effect=RapidApiOddsFeedClientError("rapidapi_auth_failed:top-secret-key"),
    ):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    body = json.dumps(resp.json())
    assert "top-secret-key" not in body
    assert "rapidapi_auth_failed" not in body
    status = resp.json()["market_influence_status"]
    assert status["reason"] == "provider_event_id_missing"


def test_resolver_outside_window_status(auto_resolver_on) -> None:
    events = [
        {
            "id": 619963,
            "status": "FINISHED",
            "start_at": "2026-07-11 10:00:00",
            "team_home": {"name": "Norway"},
            "team_away": {"name": "England"},
        }
    ]
    with patch("core.market_event_resolver.fetch_events_in_match_window", return_value=events):
        resp = client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
    status = resp.json()["market_influence_status"]
    assert status["reason"] == "resolver_outside_window"
    assert status["provider_event_id"] is None


def test_resolver_success_app_style_status(auto_resolver_on) -> None:
    events = [_event(619963, "Norway", "England")]
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
    data = resp.json()
    assert data["market_influence"]["market_influence_applied"] is True
    assert data["market_influence_status"]["applied"] is True
    assert data["market_influence_status"]["reason"] == "applied"
