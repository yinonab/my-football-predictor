"""Phase 4R.3 — offline tests for multi-provider recent-form fusion."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.api_football_recent_form import (
    APIF_ERROR_BLOCKED_SEASON,
    ApiFootballRecentFormClient,
    parse_apif_errors,
    parse_apif_fixture_for_team,
)
from core.recent_form_fusion import (
    FUSION_CACHE_PATH,
    FUSION_SOURCE_ID,
    WARN_MIXED_WC_HISTORICAL,
    WARN_MISSING_2025_2026,
    build_fusion_cache_payload,
    build_team_fusion,
    dedupe_fusion_matches,
    fuse_team_matches,
    fusion_match_to_normalized,
    load_fusion_cache,
    normalized_row_to_fusion_match,
    write_fusion_cache_safe,
)
from core.recent_match_history import NormalizedRecentMatch
from core.recent_scoring_form import RECENT_FORM_AFFECTS_SCORELINE


BRAZIL_REGISTRY = "Brazil (ברזיל)"


def _brazil_search_response() -> dict:
    return {
        "response": [
            {"team": {"id": 123, "name": "Flamengo", "national": False, "country": "Brazil"}},
            {"team": {"id": 6, "name": "Brazil", "national": True, "country": "Brazil"}},
        ]
    }


def _brazil_fixture_2024(status: str = "FT", date: str = "2024-07-06") -> dict:
    return {
        "fixture": {"id": 1001, "date": f"{date}T00:00:00+00:00", "status": {"short": status}, "venue": {}},
        "league": {"id": 9, "name": "Copa America", "season": 2024, "type": "Cup"},
        "teams": {
            "home": {"id": 6, "name": "Brazil"},
            "away": {"id": 99, "name": "Uruguay"},
        },
        "goals": {"home": 2, "away": 0},
    }


def _fd_fusion_match(date: str, opponent: str, gf: int, ga: int) -> dict:
    row = NormalizedRecentMatch(
        date=date,
        team="Brazil",
        opponent=opponent,
        goals_for=gf,
        goals_against=ga,
        competition="FIFA World Cup",
        source="recent_form_cache_football_data",
        source_priority="api_cache_fresh",
        source_confidence="high",
        date_confidence="real",
        is_home=True,
        is_neutral=False,
        team_registry_key=BRAZIL_REGISTRY,
    )
    m = normalized_row_to_fusion_match(row)
    m["competition_name"] = "FIFA World Cup"
    m["season"] = 2026
    return m


def _apif_fusion_match(date: str, opponent: str, gf: int, ga: int) -> dict:
    return {
        "provider": "api_football_recent_form",
        "source_priority": 100,
        "provider_fixture_id": f"apif:{date}:{opponent}",
        "team": "Brazil",
        "opponent": opponent,
        "date": date,
        "status": "FT",
        "home_team": "Brazil",
        "away_team": opponent,
        "home_score": gf,
        "away_score": ga,
        "score_for": gf,
        "score_against": ga,
        "result_for_team": "W" if gf > ga else ("L" if gf < ga else "D"),
        "competition_name": "Friendlies",
        "competition_id": 10,
        "season": 2024,
        "is_neutral": None,
        "confidence_level": "high",
        "quality_flags": [],
        "raw_source_ref": {"provider": "api-football"},
        "team_registry_key": BRAZIL_REGISTRY,
    }


def test_apif_team_search_selects_national_team() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key")
    with patch.object(client, "request_raw", return_value=(_brazil_search_response(), None)):
        team, candidates, err = client.search_national_team("Brazil")
    assert err is None
    assert team is not None
    assert team["id"] == 6
    assert team["national"] is True
    assert len(candidates) == 2


def test_apif_blocked_season_non_fatal() -> None:
    err = parse_apif_errors({"errors": {"plan": "Free plans cannot use season 2026"}})
    assert err is not None
    assert err.category == APIF_ERROR_BLOCKED_SEASON

    client = ApiFootballRecentFormClient(api_key="test-key")
    with patch.object(
        client,
        "request_raw",
        return_value=(None, err),
    ):
        fixtures, fetch_err = client.fetch_fixtures_team_season(6, 2026)
    assert fixtures == []
    assert fetch_err is not None


def test_apif_does_not_use_last_param() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key")
    with patch.object(client, "request_raw", return_value=({"response": []}, None)) as mock_req:
        client.fetch_fixtures_team_season(6, 2024)
    params = mock_req.call_args[0][1]
    assert "last" not in params


def test_apif_brazil_fixture_normalizes() -> None:
    parsed = parse_apif_fixture_for_team(
        _brazil_fixture_2024(),
        team_registry_key=BRAZIL_REGISTRY,
        api_team_id=6,
    )
    assert parsed is not None
    assert parsed["competition_name"] == "Copa America"
    assert parsed["score_for"] == 2
    assert parsed["result_for_team"] == "W"


def test_football_data_wc_match_normalizes_via_fusion_row() -> None:
    m = _fd_fusion_match("2026-06-15", "Serbia", 2, 0)
    assert m["provider"] == "football_data_recent_form"
    assert m["season"] == 2026
    norm = fusion_match_to_normalized(m)
    assert norm.source == FUSION_SOURCE_ID
    assert norm.goals_for == 2


def test_fusion_deduplicates_cross_provider() -> None:
    dup_apif = _apif_fusion_match("2026-06-15", "Serbia", 2, 0)
    dup_fd = _fd_fusion_match("2026-06-15", "Serbia", 2, 0)
    deduped, mix = dedupe_fusion_matches([dup_apif, dup_fd])
    assert len(deduped) == 1
    assert deduped[0]["source_priority"] == 110
    assert "api_football_recent_form" in mix
    assert "football_data_recent_form" in mix


def test_fusion_sorts_and_last_10() -> None:
    candidates = [
        _apif_fusion_match(f"2024-0{i}-01", f"Opp{i}", 1, 0)
        for i in range(1, 13)
    ]
    result = fuse_team_matches(BRAZIL_REGISTRY, candidates)
    assert result.candidate_count == 12
    assert len(result.last_10_finished) == 10
    dates = [m["date"] for m in result.last_10_finished]
    assert dates == sorted(dates, reverse=True)


def test_fusion_keeps_candidate_pool_for_diagnostics() -> None:
    candidates = [_apif_fusion_match(f"2023-0{i}-01", f"T{i}", 1, 0) for i in range(1, 16)]
    result = fuse_team_matches(BRAZIL_REGISTRY, candidates)
    assert result.coverage_count == 15
    assert result.last_15_available == 15
    assert len(result.candidates) <= 40


def test_fusion_mixed_coverage_warning() -> None:
    candidates = [
        _fd_fusion_match("2026-06-20", "France", 1, 1),
        _apif_fusion_match("2024-03-01", "England", 2, 1),
    ]
    result = fuse_team_matches(BRAZIL_REGISTRY, candidates)
    assert WARN_MIXED_WC_HISTORICAL in result.coverage_warnings or result.freshness_gap_days


def test_fusion_missing_2025_2026_warning() -> None:
    candidates = [_apif_fusion_match("2024-11-01", "Japan", 1, 0) for _ in range(10)]
    result = fuse_team_matches(BRAZIL_REGISTRY, candidates)
    assert WARN_MISSING_2025_2026 in result.coverage_warnings


def test_empty_provider_does_not_wipe_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "recent_form_fusion_cache.json"
    good = build_fusion_cache_payload(
        {
            BRAZIL_REGISTRY: fuse_team_matches(
                BRAZIL_REGISTRY,
                [_apif_fusion_match("2024-01-01", "X", 1, 0)],
            )
        }
    )
    cache_path.write_text(json.dumps(good), encoding="utf-8")

    empty = build_fusion_cache_payload({})
    path, status = write_fusion_cache_safe(empty, team_results={}, path=cache_path)
    assert path is None
    assert "0" in status
    loaded, err = load_fusion_cache(cache_path)
    assert err is None
    assert loaded is not None
    assert loaded["teams"]


def test_recent_form_affects_scoreline_false() -> None:
    assert RECENT_FORM_AFFECTS_SCORELINE is False


def test_build_team_fusion_static_only_offline() -> None:
    result = build_team_fusion(BRAZIL_REGISTRY, include_live_apis=False)
    assert result.provider_availability.get("football_data") == "cache_only"


def test_fusion_cache_read_path_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.recent_form_fusion import load_fusion_cache_rows

    cache_path = tmp_path / "fusion.json"
    team_result = fuse_team_matches(
        BRAZIL_REGISTRY,
        [_apif_fusion_match("2024-06-01", "Mexico", 3, 0)],
    )
    payload = build_fusion_cache_payload({BRAZIL_REGISTRY: team_result})
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("core.recent_form_fusion.FUSION_CACHE_PATH", cache_path)

    rows, meta = load_fusion_cache_rows()
    assert meta["cache_row_count"] == 1
    assert rows[0].source == FUSION_SOURCE_ID
    assert rows[0].team == "Brazil"


def test_collect_team_fixtures_graceful_season_block() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key")
    season_err = parse_apif_errors({"errors": {"season": "blocked"}})

    def side_effect(path, params=None):
        if path == "/leagues":
            return ({"response": []}, None)
        if path == "/fixtures" and params.get("season") == 2026:
            return (None, season_err)
        return ({"response": [_brazil_fixture_2024()]}, None)

    with patch.object(client, "request_raw", side_effect=side_effect):
        fixtures, meta = client.collect_team_fixtures(6, seasons=[2024, 2026])
    assert fixtures
    assert "2026" in str(meta.get("season_errors", {}))
