"""Phase 6A — market influence on /api/predict exact-score outputs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.market_influence import (
    influence_weight_pct,
    make_event_map_key,
    quality_meets_minimum,
    resolve_provider_event_id,
    try_apply_market_influence_to_predict,
)
from core.market_live_cache import reset_default_cache
from core.market_live_fetch import LiveFetchResult
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVAL_CASES = json.loads((FIXTURES / "market_shadow_eval_cases.json").read_text(encoding="utf-8"))
GREEN_AUDIT = json.loads(
    (FIXTURES / "rapidapi_odds_feed_norway_england.json").read_text(encoding="utf-8")
)
RED_CASE = next(c for c in EVAL_CASES["cases"] if c["name"] == "h2h_only_red_review")
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

SAMPLE_MATRIX = {
    "0-0": 7.5,
    "1-0": 9.5,
    "0-1": 10.5,
    "1-1": 12.0,
    "2-0": 7.0,
    "0-2": 8.5,
    "2-1": 9.0,
    "1-2": 10.0,
    "2-2": 7.5,
    "3-1": 5.0,
    "1-3": 5.5,
    "3-0": 3.5,
    "0-3": 4.0,
}


def _core_snapshot(data: dict) -> dict:
    scoreline = data.get("scoreline_decision") or {}
    primary = scoreline.get("primary_predicted_score") or {}
    return {
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "probabilities_1x2": data["probabilities_1x2"],
        "top_scores": data["top_scores"],
        "primary_predicted_score": primary,
        "primary_score_reason": scoreline.get("primary_score_reason"),
    }


def _live_fetch_result(
    audit: dict,
    *,
    cache_status: str = "miss",
    provider_call_count: int = 1,
) -> LiveFetchResult:
    return LiveFetchResult(
        audit_report=audit,
        cache_status=cache_status,
        provider_call_count=provider_call_count if cache_status != "hit" else 0,
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


@pytest.fixture
def shadow_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_SHADOW_DIAGNOSTICS_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_shadow_diagnostics_enabled", lambda: False)


@pytest.fixture
def live_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_LIVE_PROVIDER_FETCH_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_live_provider_fetch_enabled", lambda: False)


def test_influence_flag_default_false(influence_off) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["market_influence_enabled"] is False


def test_predict_default_unchanged_when_influence_off(influence_off) -> None:
    with patch("core.market_influence.fetch_live_market_audit_report") as fetch_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence" not in data
    fetch_mock.assert_not_called()


def test_influence_true_shadow_false_no_provider_call(all_influence_gates, shadow_off) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_influence.fetch_live_market_audit_report") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence" not in data
    assert _core_snapshot(data) == baseline
    fetch_mock.assert_not_called()


def test_influence_true_live_false_no_provider_call(all_influence_gates, live_off) -> None:
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_influence.fetch_live_market_audit_report") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence" not in data
    assert _core_snapshot(data) == baseline
    fetch_mock.assert_not_called()


def test_influence_true_no_event_id_or_map_unchanged(all_influence_gates, monkeypatch) -> None:
    monkeypatch.setattr(config, "MARKET_PROVIDER_EVENT_MAP_JSON", "{}", raising=False)
    monkeypatch.setattr(config, "load_market_provider_event_map", lambda: {})
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_influence.fetch_live_market_audit_report") as fetch_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    assert _core_snapshot(resp.json()) == baseline
    fetch_mock.assert_not_called()


def test_influence_with_request_event_id_applies_green(
    all_influence_gates,
) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    fetch_mock.assert_called_once()
    data = resp.json()
    influence = data["market_influence"]
    assert influence["market_influence_applied"] is True
    assert influence["quality_band"] == "GREEN"
    assert influence["cache_status"] == "miss"
    assert influence["provider_call_count"] == 1
    assert influence["primary_score_reason"] == "market_influence_applied"


def test_influence_event_map_without_request_event_id(
    all_influence_gates, monkeypatch
) -> None:
    event_map = {make_event_map_key("Canada (קנדה)", "Argentina (ארגנטינה)"): "619963"}
    monkeypatch.setattr(config, "load_market_provider_event_map", lambda: event_map)
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ) as fetch_mock:
        resp = client.post("/api/predict", json=BASELINE_PAYLOAD)
    assert resp.status_code == 200
    fetch_mock.assert_called_once()
    assert resp.json()["market_influence"]["market_influence_applied"] is True
    assert resp.json()["market_influence"]["provider_event_id"] == "619963"


def _green_raw_provider_payload() -> dict:
    books = [f"BOOK_{i}" for i in range(7)]
    h2h_books = [
        {
            "book": book,
            "outcome_0": 4.09,
            "outcome_1": 3.7,
            "outcome_2": 1.85,
            "is_open": True,
        }
        for book in books
    ]
    totals_books = [
        {"book": "BET365", "outcome_0": 1.95, "outcome_1": 1.85, "is_open": True},
        {"book": "PINNACLE", "outcome_0": 1.97, "outcome_1": 1.83, "is_open": True},
    ]
    spread_books = [
        {"book": "BET365", "outcome_0": 1.92, "outcome_1": 1.92, "is_open": True},
        {"book": "PINNACLE", "outcome_0": 1.94, "outcome_1": 1.90, "is_open": True},
    ]
    return {
        "provider": "rapidapi_odds_feed",
        "event_id": "619963",
        "placing": "PREMATCH",
        "http_status": 200,
        "markets": [
            {
                "id": 50679030,
                "market_name": "1X2",
                "period": "FULL_TIME",
                "placing": "PREMATCH",
                "bet_type": "BACK",
                "value": None,
                "market_books": h2h_books,
            },
            {
                "id": 50679031,
                "market_name": "OVER_UNDER",
                "period": "FULL_TIME",
                "placing": "PREMATCH",
                "bet_type": "BACK",
                "value": 2.5,
                "market_books": totals_books,
            },
            {
                "id": 50679032,
                "market_name": "ASIAN_HANDICAP",
                "period": "FULL_TIME",
                "placing": "PREMATCH",
                "bet_type": "BACK",
                "value": -0.5,
                "market_books": spread_books,
            },
        ],
    }


def test_influence_cache_hit_on_second_predict(all_influence_gates) -> None:
    payload = _green_raw_provider_payload()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=payload,
    ) as fetch_mock:
        first = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
        second = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert first.status_code == 200
    assert second.status_code == 200
    fetch_mock.assert_called_once_with("619963")
    assert second.json()["market_influence"]["cache_status"] == "hit"
    assert second.json()["market_influence"]["provider_call_count"] == 0


def test_influence_ttl_zero_calls_provider_each_time(
    all_influence_gates, monkeypatch
) -> None:
    monkeypatch.setattr(config, "MARKET_LIVE_FETCH_CACHE_TTL_SECONDS", 0, raising=False)
    monkeypatch.setattr(config, "market_live_fetch_cache_ttl_seconds", lambda: 0)
    payload = _green_raw_provider_payload()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=payload,
    ) as fetch_mock:
        client.post("/api/predict", json={**BASELINE_PAYLOAD, "provider_event_id": "619963"})
        client.post("/api/predict", json={**BASELINE_PAYLOAD, "provider_event_id": "619963"})
    assert fetch_mock.call_count == 2


def test_red_quality_no_influence(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(RED_CASE["inline_market"]),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()


def test_yellow_quality_limited_weight(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(YELLOW_AUDIT),
    ):
        result = try_apply_market_influence_to_predict(
            home_team="City",
            away_team="County",
            model_score_matrix=SAMPLE_MATRIX,
            provider_event_id="1",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
        )
    assert result.applied is True
    assert result.metadata is not None
    assert result.metadata["quality_band"] == BAND_YELLOW
    assert result.metadata["influence_weight_pct"] == 30


def test_green_quality_uses_max_weight_cap(all_influence_gates) -> None:
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        result = try_apply_market_influence_to_predict(
            home_team="Norway",
            away_team="England",
            model_score_matrix=SAMPLE_MATRIX,
            provider_event_id="619963",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            max_weight=0.50,
        )
    assert result.applied is True
    assert result.metadata is not None
    assert result.metadata["quality_band"] == BAND_GREEN
    assert result.metadata["influence_weight_pct"] == 50


def test_provider_error_prediction_unchanged(all_influence_gates) -> None:
    from core.market_live_fetch import MarketLiveFetchError

    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        side_effect=MarketLiveFetchError("rapidapi_auth_failed"),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "market_influence" not in data
    assert data["home_xg"] == baseline["home_xg"]
    assert data["away_xg"] == baseline["away_xg"]
    assert "rapidapi_auth_failed" not in json.dumps(data)


def test_budget_exceeded_prediction_unchanged(all_influence_gates, monkeypatch) -> None:
    monkeypatch.setattr(config, "MARKET_LIVE_FETCH_MAX_CALLS_PER_REQUEST", 0, raising=False)
    monkeypatch.setattr(config, "market_live_fetch_max_calls_per_request", lambda: 0)
    baseline = _core_snapshot(client.post("/api/predict", json=BASELINE_PAYLOAD).json())
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    assert "market_influence" not in resp.json()
    assert _core_snapshot(resp.json())["home_xg"] == baseline["home_xg"]
    fetch_mock.assert_not_called()


def test_fixture_diagnostics_append_still_works(all_influence_gates, live_off) -> None:
    norway_case = next(
        c for c in EVAL_CASES["cases"] if c["name"] == "norway_england_green"
    )
    with patch("core.market_influence.fetch_live_market_audit_report") as fetch_mock:
        resp = client.post(
            "/api/predict",
            json={
                **BASELINE_PAYLOAD,
                "include_market_shadow_diagnostics": True,
                "market_shadow_fixture": norway_case["fixture"],
            },
        )
    assert resp.status_code == 200
    assert "market_shadow_diagnostics" in resp.json()
    fetch_mock.assert_not_called()


def test_no_api_keys_required(all_influence_gates, monkeypatch) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    with patch(
        "core.market_influence.fetch_live_market_audit_report",
        return_value=_live_fetch_result(GREEN_AUDIT),
    ):
        resp = client.post(
            "/api/predict",
            json={**BASELINE_PAYLOAD, "provider_event_id": "619963"},
        )
    assert resp.status_code == 200
    assert resp.json()["market_influence"]["market_influence_applied"] is True


def test_event_map_key_normalization() -> None:
    assert make_event_map_key("Canada (קנדה)", "Argentina (ארגנטינה)") == "Canada|Argentina"
    assert resolve_provider_event_id(
        home_team="Norway",
        away_team="England",
        request_event_id=None,
        event_map={"Norway|England": "619963"},
    ) == "619963"
    assert resolve_provider_event_id(
        home_team="England",
        away_team="Norway",
        request_event_id=None,
        event_map={"Norway|England": "619963"},
    ) == "619963"


def test_weight_helpers() -> None:
    assert influence_weight_pct(quality_band=BAND_RED, max_weight=0.5) is None
    assert influence_weight_pct(quality_band=BAND_YELLOW, max_weight=0.5) == 30
    assert influence_weight_pct(quality_band=BAND_GREEN, max_weight=0.5) == 50
    assert quality_meets_minimum(BAND_RED, BAND_YELLOW) is False
    assert quality_meets_minimum(BAND_YELLOW, BAND_YELLOW) is True
    assert quality_meets_minimum(BAND_GREEN, BAND_YELLOW) is True
