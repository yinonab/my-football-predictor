"""Phase 4R.2 — football-data recent form cache tests (offline fixtures)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from core.football_data_recent_form import (
    CACHE_SCHEMA_VERSION,
    RECENT_FORM_CACHE_CORRUPT,
    RECENT_FORM_CACHE_MISSING,
    build_cache_payload,
    cache_dict_to_normalized,
    cache_rows_from_payload,
    discover_football_data_team_ids,
    format_error_detail,
    is_finished_fd_match,
    load_recent_form_cache,
    normalized_match_to_cache_dict,
    parse_fd_match_for_registry_team,
    refresh_enabled,
    write_recent_form_cache,
)
from core.recent_form_sources_audit import classify_confidence_bucket
from core.recent_match_history import (
    build_normalized_recent_match_history,
    get_recent_form_cache_status,
    load_recent_form_cache_rows,
)
from core.recent_scoring_form import RECENT_FORM_AFFECTS_SCORELINE, get_recent_scoring_form
from core.scoreline_decision import build_scoreline_decision
from core.underdog_goal_gate import compute_underdog_goal_gate
from data.football_data import (
    FootballDataClient,
    FootballDataErrorDetail,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_429_RATE_LIMITED,
    NETWORK_ERROR,
    build_error_detail,
    category_from_http_status,
    sanitize_fd_response_body,
)

FINISHED_BRAZIL = {
    "id": 1001,
    "utcDate": "2025-06-10T19:00:00Z",
    "status": "FINISHED",
    "competition": {"name": "International Friendly"},
    "homeTeam": {"id": 26, "name": "Brazil", "shortName": "Brazil", "tla": "BRA"},
    "awayTeam": {"id": 99, "name": "Mexico", "shortName": "Mexico", "tla": "MEX"},
    "score": {"fullTime": {"home": 2, "away": 0}},
    "venue": {"city": "Brasilia"},
}

SCHEDULED_BRAZIL = {
    "id": 1002,
    "utcDate": "2026-07-01T12:00:00Z",
    "status": "SCHEDULED",
    "homeTeam": {"id": 26, "name": "Brazil", "shortName": "Brazil", "tla": "BRA"},
    "awayTeam": {"id": 10, "name": "France", "shortName": "France", "tla": "FRA"},
    "score": {"fullTime": {"home": None, "away": None}},
}

TIMED_BRAZIL = {
    **SCHEDULED_BRAZIL,
    "id": 1003,
    "status": "TIMED",
}


def test_is_finished_vs_scheduled() -> None:
    assert is_finished_fd_match(FINISHED_BRAZIL) is True
    assert is_finished_fd_match(SCHEDULED_BRAZIL) is False
    assert is_finished_fd_match(TIMED_BRAZIL) is False


def test_parse_finished_match_team_perspective() -> None:
    rows = parse_fd_match_for_registry_team(
        FINISHED_BRAZIL,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=26,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.goals_for == 2
    assert row.goals_against == 0
    assert row.date == "2025-06-10"
    assert row.date_confidence == "real"
    assert row.source == "recent_form_cache_football_data"
    assert row.opponent == "Mexico"


def test_discover_team_ids_from_wc_matches(monkeypatch) -> None:
    client = FootballDataClient(api_key="test", enabled=True)

    def fake_request_raw(path: str, params: dict | None = None):
        if path.endswith("/teams"):
            return {
                "teams": [
                    {"team": {"id": 26, "name": "Brazil", "shortName": "Brazil", "tla": "BRA"}},
                    {"team": {"id": 55, "name": "Netherlands", "shortName": "Netherlands", "tla": "NED"}},
                ]
            }, None
        if path.endswith("/matches"):
            return {"matches": []}, None
        return {}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]

    id_map, missing, _ = discover_football_data_team_ids(client)
    assert id_map["Brazil (ברזיל)"] == 26
    assert id_map["Netherlands (הולנד)"] == 55
    assert "Brazil" not in missing


def _sample_cache_payload() -> dict:
    rows = parse_fd_match_for_registry_team(
        FINISHED_BRAZIL,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=26,
    )
    matches = [normalized_match_to_cache_dict(r) for r in rows]
    for i in range(9):
        clone = dict(matches[0])
        clone["date"] = f"2025-0{(i % 8) + 1}-10"
        clone["goals_for"] = 1 + (i % 3)
        matches.append(clone)
    return build_cache_payload(
        team_results={
            "Brazil (ברזיל)": {"status": "ok", "warnings": [], "matches": matches},
            "New Zealand (ניו זילנד)": {
                "status": "ok",
                "warnings": [],
                "matches": [
                    {
                        **matches[0],
                        "team": "New Zealand",
                        "team_registry_key": "New Zealand (ניו זילנד)",
                        "date": f"2025-05-{i + 1:02d}",
                        "goals_for": 1 + (i % 2),
                    }
                    for i in range(10)
                ],
            },
        },
        id_map={"Brazil (ברזיל)": 26, "New Zealand (ניו זילנד)": 777},
        refresh_errors=[],
    )


def test_cache_roundtrip(tmp_path: Path) -> None:
    payload = _sample_cache_payload()
    path = tmp_path / "recent_form_cache.json"
    write_recent_form_cache(payload, path)
    loaded, err = load_recent_form_cache(path)
    assert err is None
    assert loaded is not None
    assert loaded["schema_version"] == CACHE_SCHEMA_VERSION
    rows, meta = cache_rows_from_payload(loaded)
    assert len(rows) >= 10
    assert meta["cache_found"] is True


def test_corrupt_cache_fallback(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(
        "core.football_data_recent_form.RECENT_FORM_CACHE_PATH",
        path,
    )
    payload, err = load_recent_form_cache(path)
    assert payload is None
    assert err == RECENT_FORM_CACHE_CORRUPT
    rows, meta = load_recent_form_cache_rows()
    assert rows == []
    assert RECENT_FORM_CACHE_CORRUPT in meta.get("reason_codes", []) or meta.get("cache_error") == RECENT_FORM_CACHE_CORRUPT


def test_missing_cache_static_fallback(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "missing.json"
    monkeypatch.setattr(
        "core.football_data_recent_form.RECENT_FORM_CACHE_PATH",
        path,
    )
    history = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_fusion_cache=False,
    )
    assert len(history) >= 300
    rows, meta = load_recent_form_cache_rows()
    assert rows == []
    assert meta["cache_error"] == RECENT_FORM_CACHE_MISSING


def test_api_cache_priority_over_static(tmp_path: Path, monkeypatch) -> None:
    payload = _sample_cache_payload()
    path = tmp_path / "recent_form_cache.json"
    write_recent_form_cache(payload, path)
    monkeypatch.setattr(
        "core.football_data_recent_form.RECENT_FORM_CACHE_PATH",
        path,
    )
    history = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_fusion_cache=False,
    )
    brazil_api = [
        r
        for r in history
        if r.team_registry_key == "Brazil (ברזיל)"
        and r.source == "recent_form_cache_football_data"
    ]
    assert len(brazil_api) >= 10
    form = get_recent_scoring_form("Brazil (ברזיל)", history=history)
    assert "recent_form_cache_football_data" in (form.source_breakdown or {})


def test_coverage_improves_with_cache_fixture(tmp_path: Path, monkeypatch) -> None:
    static = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_recent_form_cache=False,
        include_fusion_cache=False,
    )
    nz_static = get_recent_scoring_form("New Zealand (ניו זילנד)", history=static)
    assert nz_static.recent_form_confidence == "unavailable"

    payload = _sample_cache_payload()
    path = tmp_path / "recent_form_cache.json"
    write_recent_form_cache(payload, path)
    monkeypatch.setattr(
        "core.football_data_recent_form.RECENT_FORM_CACHE_PATH",
        path,
    )
    merged = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_fusion_cache=False,
    )
    nz_merged = get_recent_scoring_form("New Zealand (ניו זילנד)", history=merged)
    assert nz_merged.recent_form_available is True
    assert nz_merged.recent_form_confidence in {"high", "medium", "low"}


def test_config_missing_key_disables_refresh(monkeypatch) -> None:
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.setenv("RECENT_FORM_API_ENABLED", "true")
    import importlib

    import config as cfg

    importlib.reload(cfg)
    assert cfg.recent_form_api_enabled() is False


def test_recent_form_affects_scoreline_false() -> None:
    assert RECENT_FORM_AFFECTS_SCORELINE is False


def test_gate_regression_unchanged() -> None:
    from core.underdog_goal_gate import build_underdog_match_context

    ctx = build_underdog_match_context(
        favorite_outcome="home_win",
        probabilities_1x2={"home_win": 62.0, "draw": 22.0, "away_win": 16.0},
        home_team="Netherlands",
        away_team="Sweden",
        home_xg=1.9,
        away_xg=0.75,
        favorite_power=900.0,
        underdog_power=700.0,
        power_gap=200.0,
    )
    assert ctx is not None
    gate = compute_underdog_goal_gate(
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    assert gate.level in {"BLOCK", "WEAK_ALLOW", "ALLOW", "STRONG_ALLOW", "BALANCED"}


def test_scoreline_primary_regression() -> None:
    from core.math_engine import AdvancedDixonColesEngine

    engine = AdvancedDixonColesEngine(alpha=0.0)
    result = engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=1.81,
        away_xg_override=0.79,
    )
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
        top_scores=result["top_scores"],
        all_scores=result["all_scores"],
        home_xg=1.81,
        away_xg=0.79,
        home_team="Netherlands",
        away_team="Sweden",
    )
    assert decision.representative_score_method == "representative_v2_composite"


def _mock_response(status: int, body: str) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = body
    if body.startswith("{"):
        response.json.return_value = json.loads(body)
    else:
        response.json.side_effect = ValueError("not json")
    return response


def test_http_403_not_network_error(monkeypatch) -> None:
    client = FootballDataClient(api_key="test-key", enabled=True)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(
            403,
            '{"message":"Forbidden","errorCode":403}',
        ),
    )
    payload, detail = client.request_raw("/teams/764/matches", {"status": "FINISHED"})
    assert payload is None
    assert detail is not None
    assert detail.category == HTTP_403_FORBIDDEN
    assert detail.http_status == 403
    assert client.last_error_code != NETWORK_ERROR
    assert detail.likely_cause == "tier_or_permission_issue"


def test_http_429_rate_limited_category(monkeypatch) -> None:
    client = FootballDataClient(api_key="test-key", enabled=True)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(
            429,
            '{"message":"Too many requests","errorCode":429}',
        ),
    )
    _, detail = client.request_raw("/teams/764/matches", {})
    assert detail is not None
    assert detail.category == HTTP_429_RATE_LIMITED
    assert detail.likely_cause == "rate_limit"


def test_http_404_not_found_category(monkeypatch) -> None:
    client = FootballDataClient(api_key="test-key", enabled=True)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(404, '{"message":"Not found"}'),
    )
    _, detail = client.request_raw("/teams/999999/matches", {})
    assert detail is not None
    assert detail.category == HTTP_404_NOT_FOUND


def test_response_body_sanitized_and_truncated() -> None:
    long_body = "x" * 400
    sanitized = sanitize_fd_response_body(long_body, max_len=240)
    assert len(sanitized) <= 240
    assert "..." in sanitized
    redacted = sanitize_fd_response_body("X-Auth-Token: secret-value-here")
    assert "secret-value" not in redacted
    assert "***" in redacted


def test_format_error_detail_never_includes_api_key() -> None:
    detail = build_error_detail(
        endpoint_path="/teams/764/matches",
        http_status=403,
        category=HTTP_403_FORBIDDEN,
        raw_body='{"message":"Forbidden"}',
        params={"status": "FINISHED"},
    )
    text = format_error_detail(detail, verbose=True)
    assert "test-key" not in text
    assert "X-Auth-Token" not in text
    assert "HTTP_403_FORBIDDEN" in text


def test_refresh_cli_parse_teams_with_spaces() -> None:
    from core.football_data_recent_form import parse_cli_team_names, resolve_cli_team_registry_keys

    csv_names = parse_cli_team_names("Brazil,Sweden,Haiti,New Zealand", [])
    assert csv_names == ["Brazil", "Sweden", "Haiti", "New Zealand"]
    repeat_names = parse_cli_team_names(None, ["Brazil", "Sweden", "Haiti", "New Zealand"])
    assert repeat_names == ["Brazil", "Sweden", "Haiti", "New Zealand"]
    assert csv_names == repeat_names
    keys = resolve_cli_team_registry_keys(csv_names)
    assert len(keys) == 4
    assert {k.split(" (")[0] for k in keys} == {"Brazil", "Sweden", "Haiti", "New Zealand"}


def test_date_window_never_exceeds_750_days() -> None:
    from core.football_data_recent_form import (
        FD_MAX_DATE_SPAN_DAYS,
        FD_SAFE_WINDOW_DAYS,
        build_safe_date_window,
        date_window_span_days,
        iter_rolling_date_windows,
    )

    date_from, date_to = build_safe_date_window()
    span = date_window_span_days(date_from, date_to)
    assert span <= FD_SAFE_WINDOW_DAYS
    assert span <= FD_MAX_DATE_SPAN_DAYS
    for win_from, win_to in iter_rolling_date_windows(max_windows=2):
        assert date_window_span_days(win_from, win_to) <= FD_SAFE_WINDOW_DAYS
        assert win_from < win_to


def test_fetch_uses_paired_safe_window(monkeypatch) -> None:
    from core.football_data_recent_form import (
        FD_SAFE_WINDOW_DAYS,
        build_safe_date_window,
        date_window_span_days,
        fetch_team_recent_matches,
    )

    client = FootballDataClient(api_key="test", enabled=True)
    captured: list[dict] = []
    expected_from, expected_to = build_safe_date_window()

    def fake_request_raw(path: str, params: dict | None = None):
        captured.append({"path": path, "params": dict(params or {})})
        return {"matches": []}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    result = fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=764,
        sleep_seconds=0,
        min_matches=999,
        max_windows=1,
    )
    assert result.error_category is None
    assert len(captured) >= 1
    first = captured[0]["params"]
    assert first.get("dateFrom") == expected_from
    assert first.get("dateTo") == expected_to
    assert date_window_span_days(first["dateFrom"], first["dateTo"]) <= FD_SAFE_WINDOW_DAYS


def test_bosnia_h_shortname_matches() -> None:
    from core.football_data_teams import normalize_team_key, teams_match

    fd_team = {
        "name": "Bosnia-Herzegovina",
        "shortName": "Bosnia-H.",
        "tla": "BIH",
    }
    assert normalize_team_key("Bosnia-H.") == normalize_team_key("Bosnia and Herzegovina")
    assert teams_match("Bosnia", fd_team) is True
    assert teams_match("Bosnia and Herzegovina", fd_team) is True


def test_discover_bosnia_from_wc_match_object(monkeypatch) -> None:
    client = FootballDataClient(api_key="test", enabled=True)
    bosnia_team = {
        "id": 1060,
        "name": "Bosnia-Herzegovina",
        "shortName": "Bosnia-H.",
        "tla": "BIH",
    }

    def fake_request_raw(path: str, params: dict | None = None):
        if path.endswith("/teams"):
            return {"teams": []}, None
        if path.endswith("/matches"):
            return {
                "matches": [
                    {
                        "homeTeam": bosnia_team,
                        "awayTeam": {"id": 1, "name": "Qatar", "shortName": "Qatar", "tla": "QAT"},
                    }
                ]
            }, None
        return {}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    id_map, missing, _ = discover_football_data_team_ids(client)
    assert id_map.get("Bosnia (בוסניה)") == 1060
    assert "Bosnia" not in missing


def test_category_from_http_status_mapping() -> None:
    assert category_from_http_status(403) == HTTP_403_FORBIDDEN
    assert category_from_http_status(404) == HTTP_404_NOT_FOUND
    assert category_from_http_status(429) == HTTP_429_RATE_LIMITED


def test_fetch_rejects_unpaired_or_overwide_custom_window() -> None:
    from data.football_data import HTTP_400_BAD_REQUEST

    from core.football_data_recent_form import fetch_team_recent_matches

    client = FootballDataClient(api_key="test", enabled=True)
    client.request_raw = MagicMock(return_value=({"matches": []}, None))  # type: ignore[method-assign]

    result = fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=764,
        date_from="2024-01-01",
        date_to=None,
        sleep_seconds=0,
    )
    assert result.error_category == HTTP_400_BAD_REQUEST
    client.request_raw.assert_not_called()

    result = fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=764,
        date_from="2020-01-01",
        date_to="2026-06-21",
        sleep_seconds=0,
    )
    assert result.error_category == HTTP_400_BAD_REQUEST


def test_first_window_is_most_recent() -> None:
    from core.football_data_recent_form import _utc_today, iter_rolling_date_windows

    today = _utc_today()
    windows = iter_rolling_date_windows(date_to=today, max_windows=2)
    assert len(windows) == 2
    assert windows[0][1] == today.isoformat()
    assert windows[1][1] < windows[0][0]


def test_undated_fallback_on_dated_403() -> None:
    from core.football_data_recent_form import (
        RECENT_FORM_API_UNDATED_FALLBACK_USED,
        fetch_team_recent_matches,
    )
    from data.football_data import HTTP_403_FORBIDDEN, build_error_detail

    client = FootballDataClient(api_key="test", enabled=True)
    calls: list[dict] = []

    def fake_request_raw(path: str, params: dict | None = None):
        calls.append(dict(params or {}))
        if params and params.get("dateFrom"):
            detail = build_error_detail(
                endpoint_path=path,
                http_status=403,
                category=HTTP_403_FORBIDDEN,
                raw_body="restricted",
            )
            return None, detail
        return {"matches": [FINISHED_BRAZIL]}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    result = fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=26,
        sleep_seconds=0,
        min_matches=1,
        max_windows=1,
    )
    assert len(result.rows) == 1
    assert RECENT_FORM_API_UNDATED_FALLBACK_USED in result.reason_codes
    assert result.fetch_strategy == "undated_fallback"
    assert calls[0].get("dateFrom")
    assert "dateFrom" not in calls[-1]


def test_probe_stops_on_rate_limit() -> None:
    from core.football_data_recent_form import probe_team_match_endpoint_variants
    from data.football_data import HTTP_429_RATE_LIMITED, build_error_detail

    client = FootballDataClient(api_key="test", enabled=True)
    call_count = 0

    def fake_request_raw(path: str, params: dict | None = None):
        nonlocal call_count
        call_count += 1
        detail = build_error_detail(
            endpoint_path=path,
            http_status=429,
            category=HTTP_429_RATE_LIMITED,
            raw_body="Wait 47 seconds.",
        )
        return None, detail

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    results = probe_team_match_endpoint_variants(client, team_id=764, team_label="Brazil")
    assert len(results) == 1
    assert call_count == 1


def test_unsafe_write_blocked_when_discovery_empty(tmp_path: Path) -> None:
    from core.football_data_recent_form import build_cache_payload, write_recent_form_cache_safe

    payload = build_cache_payload(team_results={}, id_map={}, refresh_errors=["discovery:empty"])
    path, reason = write_recent_form_cache_safe(
        payload,
        id_map={},
        team_results={},
        path=tmp_path / "recent_form_cache.json",
    )
    assert path is None
    assert "0 IDs" in reason
    assert not (tmp_path / "recent_form_cache.json").exists()


def test_unsafe_write_blocked_when_all_teams_fail(tmp_path: Path) -> None:
    from core.football_data_recent_form import build_cache_payload, write_recent_form_cache_safe

    team_results = {
        "Brazil (ברזיל)": {
            "status": "http_429_rate_limited",
            "warnings": [],
            "matches": [],
        }
    }
    payload = build_cache_payload(
        team_results=team_results,
        id_map={"Brazil (ברזיל)": 764},
        refresh_errors=["Brazil:http_429_rate_limited"],
    )
    path, reason = write_recent_form_cache_safe(
        payload,
        id_map={"Brazil (ברזיל)": 764},
        team_results=team_results,
        path=tmp_path / "recent_form_cache.json",
    )
    assert path is None
    assert not (tmp_path / "recent_form_cache.json").exists()


def test_existing_cache_preserved_on_failed_write(tmp_path: Path) -> None:
    from core.football_data_recent_form import (
        write_recent_form_cache,
        write_recent_form_cache_safe,
    )

    cache_path = tmp_path / "recent_form_cache.json"
    good = _sample_cache_payload()
    write_recent_form_cache(good, cache_path)
    original = cache_path.read_text(encoding="utf-8")

    bad_payload = build_cache_payload(team_results={}, id_map={}, refresh_errors=[])
    path, _ = write_recent_form_cache_safe(
        bad_payload,
        id_map={},
        team_results={},
        path=cache_path,
    )
    assert path is None
    assert cache_path.read_text(encoding="utf-8") == original


def test_atomic_write_succeeds_with_rows(tmp_path: Path) -> None:
    from core.football_data_recent_form import write_recent_form_cache_safe

    payload = _sample_cache_payload()
    team_results = {
        "Brazil (ברזיל)": {"status": "ok", "warnings": [], "matches": payload["teams"]["Brazil (ברזיל)"]["matches"]},
        "New Zealand (ניו זילנד)": {
            "status": "ok",
            "warnings": [],
            "matches": payload["teams"]["New Zealand (ניו זילנד)"]["matches"],
        },
    }
    path, status = write_recent_form_cache_safe(
        payload,
        id_map={"Brazil (ברזיל)": 26, "New Zealand (ניו זילנד)": 777},
        team_results=team_results,
        path=tmp_path / "recent_form_cache.json",
    )
    assert status == "ok"
    assert path is not None
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_partial_success_keeps_window0_on_window1_429() -> None:
    from core.football_data_recent_form import (
        FD_DEFAULT_ROLLING_WINDOWS,
        RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT,
        fetch_team_recent_matches,
        team_fetch_status_for_result,
    )
    from data.football_data import HTTP_429_RATE_LIMITED, build_error_detail

    client = FootballDataClient(api_key="test", enabled=True)
    call_idx = 0

    def fake_request_raw(path: str, params: dict | None = None):
        nonlocal call_idx
        call_idx += 1
        if params and params.get("dateFrom"):
            if call_idx == 1:
                return {"matches": [FINISHED_BRAZIL]}, None
            detail = build_error_detail(
                endpoint_path=path,
                http_status=429,
                category=HTTP_429_RATE_LIMITED,
                raw_body="Wait 47 seconds.",
            )
            return None, detail
        return {"matches": []}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    result = fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=26,
        sleep_seconds=0,
        min_matches=10,
        max_windows=2,
    )
    assert len(result.rows) == 1
    assert result.partial_success is True
    assert RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT in result.reason_codes
    assert team_fetch_status_for_result(result) == "partial_success"
    assert result.rate_limit_wait_seconds == 47


def test_default_fetch_uses_one_window_only() -> None:
    from core.football_data_recent_form import FD_DEFAULT_ROLLING_WINDOWS, fetch_team_recent_matches

    assert FD_DEFAULT_ROLLING_WINDOWS == 1
    client = FootballDataClient(api_key="test", enabled=True)
    dated_calls = 0

    def fake_request_raw(path: str, params: dict | None = None):
        nonlocal dated_calls
        if params and params.get("dateFrom"):
            dated_calls += 1
        return {"matches": []}, None

    client.request_raw = fake_request_raw  # type: ignore[method-assign]
    fetch_team_recent_matches(
        client,
        team_registry_key="Brazil (ברזיל)",
        football_data_team_id=764,
        sleep_seconds=0,
        min_matches=999,
    )
    assert dated_calls == 1


def test_partial_success_allows_cache_write(tmp_path: Path) -> None:
    from core.football_data_recent_form import (
        TEAM_FETCH_STATUS_PARTIAL,
        build_cache_payload,
        write_recent_form_cache_safe,
    )

    matches = [
        normalized_match_to_cache_dict(
            parse_fd_match_for_registry_team(
                FINISHED_BRAZIL,
                team_registry_key="Brazil (ברזיל)",
                football_data_team_id=26,
            )[0]
        )
    ]
    team_results = {
        "Brazil (ברזיל)": {
            "status": TEAM_FETCH_STATUS_PARTIAL,
            "warnings": ["RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT"],
            "reason_codes": ["RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT"],
            "matches": matches,
        }
    }
    payload = build_cache_payload(
        team_results=team_results,
        id_map={"Brazil (ברזיל)": 764},
        refresh_errors=["partial"],
    )
    path, status = write_recent_form_cache_safe(
        payload,
        id_map={"Brazil (ברזיל)": 764},
        team_results=team_results,
        path=tmp_path / "recent_form_cache.json",
    )
    assert status == "ok"
    assert path is not None
