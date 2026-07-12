"""Phase 2 — shared market resolution context and predict wiring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_event_resolver_cache import reset_default_resolver_cache
from core.market_live_cache import reset_default_cache
from core.market_live_fetch import LiveFetchResult
from core.market_resolution import (
    MarketResolutionContext,
    build_market_resolution_context,
    odds_feed_snapshot_to_market_fetch,
)
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.odds_ensemble import OddsLookupResult
from core.odds_provider import UnifiedOddsClient

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GREEN_AUDIT = json.loads(
    (FIXTURES / "rapidapi_odds_feed_norway_england.json").read_text(encoding="utf-8")
)


def _event(
    event_id: int,
    home: str,
    away: str,
    *,
    status: str = "SCHEDULED",
    start_at: str | None = None,
) -> dict:
    payload = {
        "id": event_id,
        "status": status,
        "team_home": {"name": home},
        "team_away": {"name": away},
    }
    if start_at is not None:
        payload["start_at"] = start_at
    return payload


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
def all_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_INFLUENCE_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_influence_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_SHADOW_DIAGNOSTICS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_shadow_diagnostics_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_LIVE_PROVIDER_FETCH_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_live_provider_fetch_enabled", lambda: True)
    monkeypatch.setattr(config, "MARKET_AUTO_EVENT_RESOLVER_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "market_auto_event_resolver_enabled", lambda: True)
    monkeypatch.setattr(config, "load_market_provider_event_map", lambda: {})


def test_odds_feed_snapshot_to_market_fetch_shape() -> None:
    snapshot = parse_rapidapi_odds_feed_audit(GREEN_AUDIT)
    consensus, _ = build_snapshot_pipeline(snapshot)
    fetch = odds_feed_snapshot_to_market_fetch(snapshot, consensus)
    assert fetch is not None
    assert fetch.sport_key == "rapidapi_odds_feed"
    assert fetch.consensus_1x2_percent is not None
    assert set(fetch.consensus_1x2_percent) == {"home_win", "draw", "away_win"}
    assert fetch.bookmakers
    assert fetch.bookmakers[0].source_key == "rapidapi_odds_feed"


def test_build_market_resolution_context_explicit_id(all_gates) -> None:
    with patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        ctx = build_market_resolution_context(
            home_team="Norway",
            away_team="England",
            provider_event_id="619963",
        )
    assert ctx.provider_event_id == "619963"
    assert ctx.resolved_via == "explicit"
    assert ctx.snapshot is not None
    assert ctx.odds_market_fetch is not None
    fetch_mock.assert_called_once()


def test_predict_france_spain_scheduled_resolver_applies_influence(all_gates) -> None:
    events = [_event(700100, "France", "Spain", start_at="2026-07-14 19:00:00")]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as resolution_fetch_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
    ) as influence_fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "France",
                "away_team": "Spain",
                "venue_mode": "neutral",
                "neutral_ground": True,
                "rho": -0.15,
                "avg_goals": 2.6,
                "use_live_stats": False,
                "use_match_context": False,
                "odds_affect_prediction": False,
                "include_diagnostics": True,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    resolution_fetch_mock.assert_called_once()
    influence_fetch_mock.assert_not_called()
    assert data["market_influence"]["market_influence_applied"] is True
    status = data["market_influence_status"]
    assert status["applied"] is True
    assert status["reason"] == "applied"
    assert status["provider_event_id"] == "700100"


def test_predict_france_spain_market_diagnostics_use_odds_feed_after_scheduled_resolve(
    all_gates,
) -> None:
    events = [_event(700100, "France", "Spain", start_at="2026-07-14 19:00:00")]
    legacy = OddsLookupResult(
        status="quota_exceeded",
        odds_key_configured=True,
        notes=["quota exceeded"],
    )
    oddspapi = MagicMock()
    oddspapi.is_available = True
    oddspapi.lookup_match_market.return_value = legacy
    the_odds = MagicMock()
    the_odds.is_available = True
    the_odds.lookup_match_market.return_value = legacy
    real_client = UnifiedOddsClient(oddspapi=oddspapi, the_odds_api=the_odds)

    with patch("api.main._odds_client", real_client), patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "France",
                "away_team": "Spain",
                "venue_mode": "neutral",
                "neutral_ground": True,
                "rho": -0.15,
                "avg_goals": 2.6,
                "use_live_stats": False,
                "use_match_context": False,
                "odds_affect_prediction": False,
                "include_diagnostics": True,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    market = resp.json()["market_diagnostics"]
    assert market["status"] == "ok"
    assert market["primary_source"] == "rapidapi_odds_feed"
    assert market["available"] is True


def test_build_market_resolution_context_single_fetch_per_predict(all_gates) -> None:
    events = [_event(619963, "Norway", "England")]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as resolution_fetch_mock, patch(
        "core.market_influence.fetch_live_market_audit_report",
    ) as influence_fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "Norway",
                "away_team": "England",
                "neutral_ground": True,
                "use_match_context": False,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    resolution_fetch_mock.assert_called_once()
    influence_fetch_mock.assert_not_called()
    data = resp.json()
    assert data["market_influence"]["market_influence_applied"] is True


def test_predict_outside_window_status(all_gates) -> None:
    events = [
        {
            "id": 619963,
            "status": "SCHEDULED",
            "start_at": "2027-01-15 19:00:00",
            "team_home": {"name": "Norway"},
            "team_away": {"name": "England"},
        }
    ]
    with patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
    ) as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "Norway",
                "away_team": "England",
                "neutral_ground": True,
                "use_match_context": False,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    status = resp.json()["market_influence_status"]
    assert status["reason"] == "resolver_outside_window"
    fetch_mock.assert_not_called()


def test_unified_odds_client_odds_feed_fallback() -> None:
    snapshot = parse_rapidapi_odds_feed_audit(GREEN_AUDIT)
    consensus, _ = build_snapshot_pipeline(snapshot)
    odds_fetch = odds_feed_snapshot_to_market_fetch(snapshot, consensus)
    ctx = MarketResolutionContext(
        provider_event_id="619963",
        odds_market_fetch=odds_fetch,
    )
    legacy = OddsLookupResult(
        status="quota_exceeded",
        odds_key_configured=True,
        notes=["The Odds API quota exceeded"],
    )
    oddspapi = MagicMock()
    oddspapi.is_available = True
    oddspapi.lookup_match_market.return_value = legacy
    the_odds = MagicMock()
    the_odds.is_available = True
    the_odds.lookup_match_market.return_value = legacy
    client = UnifiedOddsClient(oddspapi=oddspapi, the_odds_api=the_odds)
    result = client.lookup_match_market("Norway", "England", resolution_context=ctx)
    assert result.status == "ok"
    assert result.fetch is not None
    assert result.fetch.sport_key == "rapidapi_odds_feed"


def test_predict_market_diagnostics_uses_odds_feed_when_legacy_quota(all_gates) -> None:
    events = [_event(619963, "Norway", "England")]
    legacy = OddsLookupResult(
        status="quota_exceeded",
        odds_key_configured=True,
        notes=["quota exceeded"],
    )
    oddspapi = MagicMock()
    oddspapi.is_available = True
    oddspapi.lookup_match_market.return_value = legacy
    the_odds = MagicMock()
    the_odds.is_available = True
    the_odds.lookup_match_market.return_value = legacy
    real_client = UnifiedOddsClient(oddspapi=oddspapi, the_odds_api=the_odds)

    with patch("api.main._odds_client", real_client), patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=events,
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "Norway",
                "away_team": "England",
                "neutral_ground": True,
                "use_match_context": False,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    market = body["market_diagnostics"]
    assert market["status"] == "ok"
    assert market["available"] is True
    assert market["primary_source"] == "rapidapi_odds_feed"
    assert market["consensus_1x2_percent"] is not None
    assert "top-secret" not in json.dumps(body).lower()


def test_predict_legacy_quota_without_odds_feed_still_fails(all_gates) -> None:
    legacy = OddsLookupResult(
        status="quota_exceeded",
        odds_key_configured=True,
        notes=["quota exceeded"],
    )
    oddspapi = MagicMock()
    oddspapi.is_available = True
    oddspapi.lookup_match_market.return_value = legacy
    the_odds = MagicMock()
    the_odds.is_available = True
    the_odds.lookup_match_market.return_value = legacy
    real_client = UnifiedOddsClient(oddspapi=oddspapi, the_odds_api=the_odds)

    with patch("api.main._odds_client", real_client), patch(
        "core.market_event_resolver.fetch_resolver_discovery_events",
        return_value=[],
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
    ) as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                "home_team": "Canada (קנדה)",
                "away_team": "Argentina (ארגנטינה)",
                "neutral_ground": True,
                "use_match_context": False,
                "top_n": 3,
            },
        )
    assert resp.status_code == 200
    market = resp.json()["market_diagnostics"]
    assert market["status"] == "quota_exceeded"
    fetch_mock.assert_not_called()
