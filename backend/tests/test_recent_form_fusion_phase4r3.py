"""Phase 4R.3 — offline tests for multi-provider recent-form fusion."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.api_football_recent_form import (
    APIF_ACCOUNT_SUSPENDED,
    APIF_ERROR_BLOCKED_SEASON,
    ApiFootballRecentFormClient,
    ApiFootballRequestError,
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


HAITI_REGISTRY = "Haiti (האיטי)"
NZ_REGISTRY = "New Zealand (ניו זילנד)"
HAITI_API_ID = 2386
NZ_API_ID = 4673


def _apif_fixture(
    *,
    fixture_id: int,
    team_id: int,
    team_name: str,
    opponent_id: int,
    opponent_name: str,
    date: str,
    gf: int,
    ga: int,
    competition: str,
    status: str = "FT",
    is_home: bool = True,
) -> dict:
    if is_home:
        home_id, away_id = team_id, opponent_id
        home_name, away_name = team_name, opponent_name
        hg, ag = gf, ga
    else:
        home_id, away_id = opponent_id, team_id
        home_name, away_name = opponent_name, team_name
        hg, ag = ga, gf
    return {
        "fixture": {
            "id": fixture_id,
            "date": f"{date}T00:00:00+00:00",
            "status": {"short": status},
            "venue": {},
        },
        "league": {"id": 10, "name": competition, "season": 2024, "type": "Cup"},
        "teams": {
            "home": {"id": home_id, "name": home_name},
            "away": {"id": away_id, "name": away_name},
        },
        "goals": {"home": hg, "away": ag},
    }


def _haiti_2024_fixtures() -> list[dict]:
    opponents = [
        ("Honduras", 2001, "2024-03-24", 1, 0),
        ("Costa Rica", 2002, "2024-03-27", 0, 0),
        ("Mexico", 2003, "2024-06-22", 1, 2),
        ("Jamaica", 2004, "2024-06-28", 2, 1),
        ("Canada", 2005, "2024-07-05", 0, 1),
        ("Trinidad and Tobago", 2006, "2024-10-12", 3, 0),
        ("Cuba", 2007, "2024-10-15", 1, 1),
    ]
    return [
        _apif_fixture(
            fixture_id=3000 + i,
            team_id=HAITI_API_ID,
            team_name="Haiti",
            opponent_id=oid,
            opponent_name=opp,
            date=date,
            gf=gf,
            ga=ga,
            competition="CONCACAF Nations League" if i < 5 else "Friendlies",
        )
        for i, (opp, oid, date, gf, ga) in enumerate(opponents)
    ]


def _nz_2024_fixtures() -> list[dict]:
    rows = [
        ("China", 2101, "2024-03-21", 0, 0),
        ("Australia", 2102, "2024-03-26", 1, 2),
        ("Fiji", 2103, "2024-06-05", 3, 0),
        ("Vanuatu", 2104, "2024-06-08", 4, 0),
        ("Solomon Islands", 2105, "2024-06-11", 2, 1),
        ("Tahiti", 2106, "2024-09-06", 1, 0),
        ("Oman", 2107, "2024-09-10", 0, 1),
        ("Malaysia", 2108, "2024-10-11", 2, 0),
        ("India", 2109, "2024-10-15", 1, 1),
    ]
    fixtures = [
        _apif_fixture(
            fixture_id=4000 + i,
            team_id=NZ_API_ID,
            team_name="New Zealand",
            opponent_id=oid,
            opponent_name=opp,
            date=date,
            gf=gf,
            ga=ga,
            competition="Friendlies" if i < 2 else "OFC Nations Cup",
            is_home=i % 2 == 0,
        )
        for i, (opp, oid, date, gf, ga) in enumerate(rows)
    ]
    fixtures.append(
        _apif_fixture(
            fixture_id=4999,
            team_id=NZ_API_ID,
            team_name="New Zealand",
            opponent_id=2110,
            opponent_name="Thailand",
            date="2024-11-18",
            gf=0,
            ga=0,
            competition="Friendlies",
            status="CANC",
        )
    )
    return fixtures


def test_known_nt_team_id_haiti_and_new_zealand() -> None:
    from core.api_football_recent_form import known_nt_team_id

    assert known_nt_team_id("Haiti") == HAITI_API_ID
    assert known_nt_team_id("New Zealand") == NZ_API_ID


def test_search_falls_back_to_known_senior_id_when_teams_endpoint_errors() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key")
    err = ApiFootballRequestError(APIF_ACCOUNT_SUSPENDED, "account suspended")
    with patch.object(client, "request_raw", return_value=(None, err)):
        team, candidates, search_err = client.search_national_team("Haiti")
    assert search_err is None
    assert team is not None
    assert int(team["id"]) == HAITI_API_ID
    assert candidates == []


def test_search_prefers_senior_men_over_youth() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key")
    payload = {
        "response": [
            {"team": {"id": 9001, "name": "Haiti U23", "national": True, "country": "Haiti"}},
            {"team": {"id": 9002, "name": "Haiti W", "national": True, "country": "Haiti"}},
        ]
    }
    with patch.object(client, "request_raw", return_value=(payload, None)):
        team, _, err = client.search_national_team("Haiti")
    assert err is None
    assert team is not None
    assert int(team["id"]) == HAITI_API_ID


def test_collect_team_fixtures_always_merges_team_season() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key", sleep_seconds=0)
    league_fixture = _apif_fixture(
        fixture_id=5001,
        team_id=HAITI_API_ID,
        team_name="Haiti",
        opponent_id=2001,
        opponent_name="Honduras",
        date="2024-03-24",
        gf=1,
        ga=0,
        competition="CONCACAF Nations League",
    )
    team_season_only = _apif_fixture(
        fixture_id=5002,
        team_id=HAITI_API_ID,
        team_name="Haiti",
        opponent_id=2007,
        opponent_name="Cuba",
        date="2024-10-15",
        gf=1,
        ga=1,
        competition="Friendlies",
    )

    def side_effect(path, params=None):
        if path == "/leagues":
            return ({"response": [{"league": {"id": 99, "name": "CONCACAF Nations League"}}]}, None)
        if path == "/fixtures" and params.get("league") == 99:
            return ({"response": [league_fixture]}, None)
        if path == "/fixtures" and params.get("team") == HAITI_API_ID and params.get("season") == 2024:
            return ({"response": [league_fixture, team_season_only]}, None)
        return ({"response": []}, None)

    with patch.object(client, "request_raw", side_effect=side_effect):
        fixtures, _ = client.collect_team_fixtures(HAITI_API_ID, seasons=[2024])
    ids = {int((fx.get("fixture") or {}).get("id")) for fx in fixtures}
    assert ids == {5001, 5002}


def test_haiti_fusion_from_apif_2024_fixtures() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key", sleep_seconds=0)
    haiti_fixtures = _haiti_2024_fixtures()
    suspended = ApiFootballRequestError(APIF_ACCOUNT_SUSPENDED, "account suspended")

    def side_effect(path, params=None):
        if path == "/teams":
            return (None, suspended)
        if path == "/leagues":
            return ({"response": []}, None)
        if path == "/fixtures" and params.get("team") == HAITI_API_ID:
            return ({"response": haiti_fixtures}, None)
        return ({"response": []}, None)

    with patch.object(client, "request_raw", side_effect=side_effect):
        team, _, err = client.search_national_team("Haiti")
        assert err is None
        assert int(team["id"]) == HAITI_API_ID
        result = build_team_fusion(HAITI_REGISTRY, apif_client=client, include_live_apis=True)

    apif_rows = [c for c in result.candidates if c.get("provider") == "api_football_recent_form"]
    assert len(apif_rows) == 7
    assert result.coverage_count >= 7
    assert result.coverage_quality in {"low", "medium", "high"}
    assert result.coverage_quality != "unavailable"
    assert result.provider_ids.get("api_football") == HAITI_API_ID
    assert "api_football_recent_form" in (result.source_mix or {})


def test_new_zealand_fusion_ignores_cancelled_fixtures() -> None:
    client = ApiFootballRecentFormClient(api_key="test-key", sleep_seconds=0)
    nz_fixtures = _nz_2024_fixtures()

    def side_effect(path, params=None):
        if path == "/teams":
            return ({"response": []}, None)
        if path == "/leagues":
            return ({"response": []}, None)
        if path == "/fixtures" and params.get("team") == NZ_API_ID:
            return ({"response": nz_fixtures}, None)
        return ({"response": []}, None)

    with patch.object(client, "request_raw", side_effect=side_effect):
        result = build_team_fusion(NZ_REGISTRY, apif_client=client, include_live_apis=True)

    apif_rows = [c for c in result.candidates if c.get("provider") == "api_football_recent_form"]
    assert len(apif_rows) == 9
    assert all(r.get("status") == "FT" for r in apif_rows)
    assert result.coverage_count == 9
    assert result.coverage_quality in {"low", "medium", "high"}
    assert result.coverage_quality != "unavailable"
    assert result.provider_ids.get("api_football") == NZ_API_ID
