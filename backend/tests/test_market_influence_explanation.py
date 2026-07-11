"""Phase 6C — user-facing market influence explanation tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_influence_explanation import build_market_influence_explanation
from core.market_live_cache import reset_default_cache
from core.market_live_fetch import LiveFetchResult
from core.market_quality import BAND_GREEN, BAND_YELLOW

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GREEN_AUDIT = json.loads(
    (FIXTURES / "rapidapi_odds_feed_norway_england.json").read_text(encoding="utf-8")
)
YELLOW_AUDIT = {
    "selected_event": {"event_id": "y1", "label": "City vs County", "tournament": "Test"},
    "market_coverage_table": [
        {
            "provider_market_name": "1X2",
            "mapped_family": "h2h",
            "sample_odds": [
                {"book": "BET365", "outcome_0": 2.1, "outcome_1": 3.3, "outcome_2": 3.4},
                {"book": "PINNACLE", "outcome_0": 2.15, "outcome_1": 3.25, "outcome_2": 3.35},
            ],
        },
        {
            "provider_market_name": "OVER_UNDER",
            "mapped_family": "totals",
            "line_point": 2.5,
            "sample_odds": [{"book": "BET365", "outcome_0": 1.9, "outcome_1": 1.9}],
        },
        {
            "provider_market_name": "ASIAN_HANDICAP",
            "mapped_family": "spreads",
            "line_point": -0.5,
            "sample_odds": [{"book": "BET365", "outcome_0": 1.92, "outcome_1": 1.92}],
        },
    ],
}

BASELINE_PAYLOAD = {
    "home_team": "Canada (קנדה)",
    "away_team": "Argentina (ארגנטינה)",
    "neutral_ground": True,
    "use_match_context": False,
    "top_n": 3,
}

_TECHNICAL_LEAK_TERMS = (
    "provider_event_id",
    "provider_call_count",
    "cache_status",
    "619963",
)


def _live_fetch_result(audit: dict) -> LiveFetchResult:
    return LiveFetchResult(
        audit_report=audit,
        cache_status="miss",
        provider_call_count=1,
    )


@pytest.fixture(autouse=True)
def _clear_live_cache() -> None:
    reset_default_cache()
    yield
    reset_default_cache()


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


def test_green_away_win_builder() -> None:
    expl = build_market_influence_explanation(
        home_team="Norway",
        away_team="England",
        quality_band=BAND_GREEN,
        influence_weight_pct=50,
        selected_score="1-2",
        outcome="away_win",
    )
    assert expl["title"] == "Market-adjusted prediction"
    assert expl["signal_label"] == "Strong market signal"
    assert expl["influence_label"] == "50% market influence"
    assert expl["selected_score_label"] == "Selected market-adjusted score: 1-2"
    assert "England" in expl["summary"]
    assert "1-2" in expl["summary"]
    assert "away win" in expl["summary"]


def test_yellow_away_win_builder() -> None:
    expl = build_market_influence_explanation(
        home_team="Norway",
        away_team="England",
        quality_band=BAND_YELLOW,
        influence_weight_pct=30,
        selected_score="0-2",
        outcome="away_win",
    )
    assert expl["signal_label"] == "Partial market signal"
    assert "incomplete" in expl["summary"]
    assert "30%" in expl["influence_label"]


def test_home_favorite_builder() -> None:
    expl = build_market_influence_explanation(
        home_team="France",
        away_team="Germany",
        quality_band=BAND_GREEN,
        influence_weight_pct=50,
        selected_score="2-1",
        outcome="home_win",
    )
    assert "France" in expl["summary"]
    assert "home win" in expl["summary"]
    assert "2-1" in expl["summary"]


def test_draw_balanced_builder() -> None:
    expl = build_market_influence_explanation(
        home_team="Spain",
        away_team="Italy",
        quality_band=BAND_GREEN,
        influence_weight_pct=50,
        selected_score="1-1",
        outcome="draw",
    )
    assert "balanced match" in expl["summary"]
    assert "narrow result" in expl["summary"]
    assert "1-1" in expl["details"][2]


def test_api_green_influence_returns_explanation(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    influence = resp.json()["market_influence"]
    assert influence["market_influence_applied"] is True
    assert influence["quality_band"] == "GREEN"
    expl = influence["explanation"]
    assert expl["title"] == "Market-adjusted prediction"
    assert expl["signal_label"] == "Strong market signal"
    assert "50%" in expl["influence_label"]
    assert "Argentina" in expl["summary"]
    primary = resp.json()["scoreline_decision"]["primary_predicted_score"]
    score = f"{primary['home_goals']}-{primary['away_goals']}"
    assert score in expl["summary"] or score in expl["selected_score_label"]


def test_api_yellow_influence_returns_partial_signal(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(YELLOW_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    expl = resp.json()["market_influence"]["explanation"]
    assert expl["signal_label"] == "Partial market signal"
    assert "incomplete" in expl["summary"]
    assert "30%" in expl["influence_label"]


def test_influence_off_no_explanation(influence_off) -> None:
    resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()


def test_provider_error_no_explanation(all_influence_gates) -> None:
    from core.market_live_fetch import MarketLiveFetchError

    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        side_effect=MarketLiveFetchError("provider_markets_empty"),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()


def test_explanation_does_not_leak_technical_fields(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    expl_text = json.dumps(resp.json()["market_influence"]["explanation"]).lower()
    for term in _TECHNICAL_LEAK_TERMS:
        assert term.lower() not in expl_text
