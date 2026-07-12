"""Phase 6B — auto event resolver on /api/predict market influence path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_event_map import make_event_map_key
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


def _core_snapshot(data: dict) -> dict:
    scoreline = data.get("scoreline_decision") or {}
    primary = scoreline.get("primary_predicted_score") or {}
    return {
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "probabilities_1x2": data["probabilities_1x2"],
        "top_scores": data["top_scores"],
        "primary_predicted_score": primary,
    }


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
    monkeypatch.setattr(config, "MARKET_AUTO_EVENT_RESOLVER_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_auto_event_resolver_enabled", lambda: False)


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


def test_auto_resolver_flag_default_false(influence_off) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["market_auto_event_resolver_enabled"] is False


def test_resolver_flag_off_no_event_list_call(influence_off) -> None:
    with patch("core.market_event_resolver.fetch_resolver_discovery_events") as list_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    list_mock.assert_not_called()


def test_influence_flags_off_no_event_list_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_AUTO_EVENT_RESOLVER_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_auto_event_resolver_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_INFLUENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_influence_enabled", lambda: False)
    with patch("core.market_event_resolver.fetch_resolver_discovery_events") as list_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    list_mock.assert_not_called()


def test_request_provider_event_id_skips_resolver(auto_resolver_on) -> None:
    with patch("core.market_event_resolver.fetch_resolver_discovery_events") as list_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    list_mock.assert_not_called()
    assert resp.json()["market_influence"]["provider_event_id"] == "619963"


def test_event_map_match_skips_resolver(auto_resolver_on, monkeypatch: pytest.MonkeyPatch) -> None:
    event_map = {make_event_map_key("Canada (קנדה)", "Argentina (ארגנטינה)"): "619963"}
    monkeypatch.setattr(config, "load_market_provider_event_map", lambda: event_map)
    with patch("core.market_event_resolver.fetch_resolver_discovery_events") as list_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    list_mock.assert_not_called()
    assert resp.json()["market_influence"]["provider_event_id"] == "619963"


def test_resolver_on_exact_match_applies_influence(auto_resolver_on) -> None:
    events = [_event(619963, "Norway", "England")]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ) as list_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        resp = client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 200
    list_mock.assert_called_once()
    fetch_mock.assert_called_once()
    influence = resp.json()["market_influence"]
    assert influence["market_influence_applied"] is True
    assert influence["provider_event_id"] == "619963"


def test_resolver_cache_hit_no_second_event_list_call(auto_resolver_on) -> None:
    events = [_event(619963, "Norway", "England")]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ) as list_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
        client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
    assert list_mock.call_count == 1


def test_resolver_reversed_match_safe(auto_resolver_on) -> None:
    events = [_event(700001, "Argentina", "Canada")]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    fetch_mock.assert_called_once()
    assert resp.json()["market_influence"]["provider_event_id"] == "700001"


def test_resolver_no_match_prediction_unchanged(auto_resolver_on) -> None:
    events = [_event(1, "France", "Germany")]
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_event_resolver.fetch_resolver_discovery_events", return_value=events):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()
    assert _core_snapshot(resp.json()) == baseline


def test_resolver_ambiguous_match_prediction_unchanged(auto_resolver_on) -> None:
    events = [
        _event(1, "Canada", "Argentina"),
        _event(2, "Canada", "Argentina"),
    ]
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_event_resolver.fetch_resolver_discovery_events", return_value=events):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()
    assert _core_snapshot(resp.json()) == baseline


def test_resolver_provider_error_prediction_unchanged_no_key_leak(auto_resolver_on) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        side_effect=RapidApiOddsFeedClientError("rapidapi_auth_failed:super-secret-key"),
    ):
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()
    assert _core_snapshot(resp.json()) == baseline
    assert "super-secret-key" not in json.dumps(resp.json())


def test_resolver_budget_exceeded_prediction_unchanged(auto_resolver_on, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_EVENT_RESOLVER_MAX_CALLS_PER_REQUEST", 0, raising=False)
    monkeypatch.setattr(config, "market_event_resolver_max_calls_per_request", lambda: 0)
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_event_resolver.fetch_resolver_discovery_events") as list_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    list_mock.assert_not_called()
    assert "market_influence" not in resp.json()
    assert _core_snapshot(resp.json()) == baseline


def test_no_api_keys_required_for_resolver_path(auto_resolver_on, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    events = [_event(619963, "Norway", "England")]
    with patch("core.market_event_resolver.fetch_resolver_discovery_events", return_value=events), patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post("/api/predict", json=NORWAY_ENGLAND_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json()["market_influence"]["market_influence_applied"] is True
