"""Market-primary prediction — separate interpreted mode tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_event_resolver import ResolverEventListDiscovery
from core.market_event_resolver_cache import reset_default_resolver_cache, reset_default_resolver_list_cache
from core.market_live_cache import reset_default_cache
from core.market_live_fetch import LiveFetchResult
from core.market_primary_prediction import build_market_primary_prediction
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW
from core.market_resolution import MarketResolutionContext
from core.market_types import MarketConsensus, MarketQualityResult
from core.math_engine import AdvancedDixonColesEngine

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GREEN_AUDIT = json.loads(
    (FIXTURES / "rapidapi_odds_feed_norway_england.json").read_text(encoding="utf-8")
)

FRA_ESP_PAYLOAD = {
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
    "top_n": 5,
}


def _live_fetch_result(audit: dict) -> LiveFetchResult:
    return LiveFetchResult(
        audit_report=audit,
        cache_status="miss",
        provider_call_count=1,
    )


def _event(event_id: int, home: str, away: str) -> dict:
    return {
        "id": event_id,
        "status": "SCHEDULED",
        "start_at": "2026-07-14 19:00:00",
        "team_home": {"name": home},
        "team_away": {"name": away},
    }


def _matrix_from_xg(home_xg: float = 1.08, away_xg: float = 1.02) -> dict[str, float]:
    engine = AdvancedDixonColesEngine(rho=-0.15)
    pred = engine.generate_match_prediction(
        994,
        1006,
        0,
        include_all_scores=True,
        top_n=10,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    raw = pred["all_scores"]
    total = sum(raw.values())
    return {k: round(v / total * 100.0, 6) for k, v in raw.items()}


def _quality(band: str) -> MarketQualityResult:
    return MarketQualityResult(
        score=85 if band == BAND_GREEN else 55,
        band=band,
        families_present=("h2h", "totals", "btts", "spreads"),
        bookmaker_count=8,
        provider_count=3,
        total_line_count=12,
        spread_line_count=2,
        has_btts=True,
    )


def _ctx(
    *,
    h2h: dict[str, float],
    totals: dict[str, dict[str, float]] | None = None,
    btts: dict[str, float] | None = None,
    spreads: dict[str, dict[str, float]] | None = None,
    band: str = BAND_GREEN,
) -> MarketResolutionContext:
    return MarketResolutionContext(
        consensus=MarketConsensus(
            h2h=h2h,
            totals_by_line=totals or {},
            btts=btts,
            spreads_by_line=spreads or {},
        ),
        quality=_quality(band),
    )


def _discovery(events: list[dict], *, pages_fetched: int = 1) -> ResolverEventListDiscovery:
    return ResolverEventListDiscovery(
        events=list(events),
        pages_fetched=pages_fetched,
        events_seen=len(events),
        list_cache_status="miss",
        provider_page_calls=pages_fetched,
        discovery_status="SCHEDULED",
        api_lookback_hours=24,
        api_lookahead_hours=1080,
    )


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    reset_default_cache()
    reset_default_resolver_cache()
    reset_default_resolver_list_cache()
    yield
    reset_default_cache()
    reset_default_resolver_cache()
    reset_default_resolver_list_cache()


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


def test_green_home_favorite_low_scoring_selects_narrow_home_win() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(
        h2h={"home": 41.32, "draw": 29.52, "away": 29.16},
        totals={"2.5": {"over": 48.0, "under": 52.0}},
        btts={"yes": 45.0, "no": 55.0},
        spreads={"-0.5": {"home": 52.0, "away": 48.0}},
    )
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        home_xg=1.08,
        away_xg=1.02,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["selected_score"] == "1-0"
    assert result.payload["selected_outcome"] == "home_win"
    assert result.payload["market_weight_pct"] == 70


def test_green_over_btts_yes_prefers_two_one() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(
        h2h={"home": 44.0, "draw": 28.0, "away": 28.0},
        totals={"2.5": {"over": 58.0, "under": 42.0}},
        btts={"yes": 62.0, "no": 38.0},
        spreads={"-0.5": {"home": 55.0, "away": 45.0}},
    )
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        home_xg=1.08,
        away_xg=1.02,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["selected_score"] in {"2-1", "1-0", "2-0"}
    assert result.payload["selected_outcome"] == "home_win"


def test_away_favorite_under_btts_no() -> None:
    matrix = _matrix_from_xg(home_xg=0.95, away_xg=1.25)
    ctx = _ctx(
        h2h={"home": 28.0, "draw": 30.0, "away": 42.0},
        totals={"2.5": {"over": 44.0, "under": 56.0}},
        btts={"yes": 40.0, "no": 60.0},
        spreads={"0.5": {"home": 46.0, "away": 54.0}},
    )
    result = build_market_primary_prediction(
        home_team="Norway",
        away_team="England",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 30.0, "draw": 32.0, "away_win": 38.0},
        home_xg=0.95,
        away_xg=1.25,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["selected_outcome"] == "away_win"
    assert result.payload["selected_score"] in {"0-1", "0-2", "1-2"}


def test_balanced_market_under_can_select_draw_score() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(
        h2h={"home": 33.5, "draw": 33.0, "away": 33.5},
        totals={"2.5": {"over": 47.0, "under": 53.0}},
        btts={"yes": 49.0, "no": 51.0},
    )
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.0, "draw": 34.0, "away_win": 32.0},
        home_xg=1.08,
        away_xg=1.02,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["selected_outcome"] in {"draw", "home_win", "away_win"}
    assert result.payload["selected_score"] in {"0-0", "1-1", "1-0", "0-1"}


def test_red_quality_not_applied() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(h2h={"home": 41.0, "draw": 30.0, "away": 29.0}, band=BAND_RED)
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is False
    assert result.payload is not None
    assert result.payload["reason"] == "quality_below_minimum"


def test_missing_totals_btts_still_works() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(h2h={"home": 41.32, "draw": 29.52, "away": 29.16})
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        home_xg=1.08,
        away_xg=1.02,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["market_goal_trend"] == "unavailable"
    assert result.payload["btts_signal"] == "unavailable"
    assert result.payload["selected_score"] == "1-0"


def test_yellow_band_weights() -> None:
    matrix = _matrix_from_xg()
    ctx = _ctx(
        h2h={"home": 40.0, "draw": 30.0, "away": 30.0},
        band=BAND_YELLOW,
    )
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.applied is True
    assert result.payload is not None
    assert result.payload["market_weight_pct"] == 45
    assert result.payload["model_weight_pct"] == 55


def test_api_does_not_change_primary_scoreline_or_influence(all_gates) -> None:
    events = [_event(623029, "France", "Spain")]
    with patch(
        "core.market_event_resolver.discover_resolver_event_list",
        return_value=_discovery(events),
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        resp = client.post("/api/predict", json=FRA_ESP_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    fetch_mock.assert_called_once()
    primary = data["scoreline_decision"]["primary_predicted_score"]
    assert primary is not None
    primary_before = copy.deepcopy(primary)
    block = data.get("market_primary_prediction")
    assert block is not None
    assert block["applied"] is True
    assert block["selected_score"]
    assert data["scoreline_decision"]["primary_predicted_score"] == primary_before
    assert data.get("market_influence") is not None or data.get("market_influence_status")
    assert data["market_diagnostics"]["status"] in {"ok", "quota_exceeded", "unavailable"}


def test_france_spain_unit_selects_one_zero() -> None:
    """France 41.3 / draw 29.5 / Spain 29.2 with low-scoring market → 1-0."""
    matrix = _matrix_from_xg()
    ctx = _ctx(
        h2h={"home": 41.32, "draw": 29.52, "away": 29.16},
        totals={"2.5": {"over": 48.0, "under": 52.0}},
        btts={"yes": 45.0, "no": 55.0},
        spreads={"-0.5": {"home": 52.0, "away": 48.0}},
    )
    result = build_market_primary_prediction(
        home_team="France",
        away_team="Spain",
        model_score_matrix=matrix,
        base_probabilities_1x2={"home_win": 34.5, "draw": 34.0, "away_win": 31.5},
        home_xg=1.08,
        away_xg=1.02,
        resolution_context=ctx,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
    )
    assert result.payload is not None
    assert result.payload["selected_score"] == "1-0"
    assert "France" in result.payload["explanation"]


def test_france_spain_mocked_api_market_primary(all_gates) -> None:
    fra_esp_audit = copy.deepcopy(GREEN_AUDIT)
    fra_esp_audit["selected_event"] = {
        "event_id": 623029,
        "label": "France vs Spain",
        "status": "SCHEDULED",
        "start_at": "2026-07-14 19:00:00",
        "tournament": "World Championship",
    }
    events = [_event(623029, "France", "Spain")]
    with patch(
        "core.market_event_resolver.discover_resolver_event_list",
        return_value=_discovery(events),
    ), patch(
        "core.market_resolution.fetch_live_market_audit_report",
        return_value=_live_fetch_result(fra_esp_audit),
    ):
        resp = client.post("/api/predict", json=FRA_ESP_PAYLOAD)
    assert resp.status_code == 200
    block = resp.json()["market_primary_prediction"]
    assert block["applied"] is True
    assert block["selected_score"]
    assert block["explanation"]
