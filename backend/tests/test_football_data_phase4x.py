"""Phase 4X — football-data.org fixture provider tests (mocked; no live token)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.fixture_state import (
    API_FOOTBALL_ACCOUNT_SUSPENDED,
    EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE,
    MATCH_ALREADY_COMPLETED,
    FixtureState,
    apply_fixture_state_rules,
)
from core.fixture_state_resolver import FixtureStateResolver
from core.football_data_fixture import (
    find_football_data_match,
    map_football_data_status,
    state_from_football_data_match,
)
from core.football_data_teams import normalize_team_key, teams_match
from data.football_data import (
    KEY_MISSING,
    FootballDataClient,
    OK,
    UNAUTHORIZED,
)

CANADA_QATAR_MATCH = {
    "utcDate": "2026-06-18T22:00:00Z",
    "status": "FINISHED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_B",
    "homeTeam": {"name": "Canada", "shortName": "Canada", "tla": "CAN"},
    "awayTeam": {"name": "Qatar", "shortName": "Qatar", "tla": "QAT"},
    "score": {"fullTime": {"home": 6, "away": 0}},
    "venue": None,
}

USA_AUSTRALIA_TIMED = {
    "utcDate": "2026-06-25T22:00:00Z",
    "status": "TIMED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_D",
    "homeTeam": {"name": "United States", "shortName": "USA", "tla": "USA"},
    "awayTeam": {"name": "Australia", "shortName": "Australia", "tla": "AUS"},
    "score": {"fullTime": {"home": None, "away": None}},
    "venue": {"name": "SoFi Stadium", "city": "Inglewood"},
}

BOSNIA_QATAR_SCHEDULED = {
    "utcDate": "2026-06-20T18:00:00Z",
    "status": "SCHEDULED",
    "stage": "GROUP_STAGE",
    "group": "GROUP_A",
    "homeTeam": {
        "name": "Bosnia-Herzegovina",
        "shortName": "Bosnia",
        "tla": "BIH",
    },
    "awayTeam": {"name": "Qatar", "shortName": "Qatar", "tla": "QAT"},
    "score": {"fullTime": {"home": None, "away": None}},
    "venue": None,
}


def _disabled_fd() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


def _fd_with_matches(matches: list[dict]) -> FootballDataClient:
    client = FootballDataClient(api_key="test-key", enabled=True)
    client.get_world_cup_matches = MagicMock(return_value=matches)  # type: ignore[method-assign]
    client.get_competitions = MagicMock(return_value=[{"code": "WC", "name": "World Cup"}])  # type: ignore[method-assign]
    return client


def test_key_missing_disables_provider_gracefully() -> None:
    client = FootballDataClient(api_key="", enabled=True)
    assert client.is_available is False
    with pytest.raises(RuntimeError, match=KEY_MISSING):
        client.get_competitions()


def test_wc_competition_available_mock() -> None:
    client = _fd_with_matches([])
    comps = client.get_competitions()
    assert any(c.get("code") == "WC" for c in comps)


def test_canada_qatar_finished_maps_to_completed() -> None:
    state = apply_fixture_state_rules(
        state_from_football_data_match(
            "Canada (קנדה)",
            "Qatar (קטר)",
            CANADA_QATAR_MATCH,
        )
    )
    assert state.fixture_status == "completed"
    assert state.prediction_valid is False
    assert state.prediction_mode == "historical"
    assert state.actual_home_goals == 6
    assert state.actual_away_goals == 0
    assert state.source == "football-data.org"
    assert MATCH_ALREADY_COMPLETED in state.warnings


def test_timed_match_maps_to_scheduled_prematch() -> None:
    state = apply_fixture_state_rules(
        state_from_football_data_match(
            "USA",
            "Australia",
            USA_AUSTRALIA_TIMED,
        )
    )
    assert state.fixture_status == "scheduled"
    assert state.prediction_valid is True
    assert state.prediction_mode == "pre_match"
    assert state.kickoff_time_utc == "2026-06-25T22:00:00Z"


def test_provider_failure_falls_back_without_crash(tmp_path: Path) -> None:
    fd = FootballDataClient(api_key="bad", enabled=True)
    fd.get_world_cup_matches = MagicMock(side_effect=RuntimeError(UNAUTHORIZED))  # type: ignore[method-assign]

    api = MagicMock()
    api.is_available = False
    resolver = FixtureStateResolver(
        api,
        football_data=fd,
        overrides_path=tmp_path / "empty.json",
    )
    (tmp_path / "empty.json").write_text(json.dumps({"fixtures": []}), encoding="utf-8")

    state = resolver.resolve("Canada", "Qatar")
    assert state.fixture_status == "unknown"


def test_manual_override_beats_football_data(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "home_team": "Canada",
                        "away_team": "Qatar",
                        "fixture_status": "completed",
                        "actual_home_goals": 1,
                        "actual_away_goals": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fd = _fd_with_matches([CANADA_QATAR_MATCH])
    api = MagicMock(is_available=False)
    resolver = FixtureStateResolver(api, football_data=fd, overrides_path=overrides)
    state = resolver.resolve("Canada", "Qatar")
    assert state.source == "manual_override"
    assert state.actual_home_goals == 1


def test_football_data_success_suppresses_api_football_suspended_warning() -> None:
    fd = _fd_with_matches([CANADA_QATAR_MATCH])
    api = MagicMock()
    api.is_available = True
    api.search_national_team.return_value = {"id": 1}
    api.find_h2h_fixtures.side_effect = RuntimeError("Your account is suspended")

    resolver = FixtureStateResolver(api, football_data=fd)
    state = resolver.resolve("Canada", "Qatar")
    assert state.fixture_status == "completed"
    assert state.source == "football-data.org"
    assert API_FOOTBALL_ACCOUNT_SUSPENDED not in state.warnings
    assert EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE not in state.warnings


def test_team_alias_bosnia() -> None:
    assert normalize_team_key("Bosnia and Herzegovina") == normalize_team_key(
        "Bosnia-Herzegovina"
    )
    assert teams_match(
        "Bosnia and Herzegovina",
        BOSNIA_QATAR_SCHEDULED["homeTeam"],
    )


def test_team_alias_usa() -> None:
    assert teams_match("USA", USA_AUSTRALIA_TIMED["homeTeam"])
    assert teams_match("United States", USA_AUSTRALIA_TIMED["homeTeam"])


def test_team_alias_korea_republic() -> None:
    match = {
        "homeTeam": {"name": "Mexico", "shortName": "Mexico", "tla": "MEX"},
        "awayTeam": {"name": "Korea Republic", "shortName": "Korea", "tla": "KOR"},
        "status": "TIMED",
        "utcDate": "2026-06-22T18:00:00Z",
        "score": {"fullTime": {"home": None, "away": None}},
    }
    assert teams_match("South Korea", match["awayTeam"])


def test_find_match_in_list() -> None:
    found = find_football_data_match(
        [USA_AUSTRALIA_TIMED, CANADA_QATAR_MATCH],
        "Canada",
        "Qatar",
    )
    assert found is not None
    assert found["status"] == "FINISHED"


def test_map_status_finished() -> None:
    assert map_football_data_status("FINISHED") == "completed"
    assert map_football_data_status("IN_PLAY") == "live"
    assert map_football_data_status("TIMED") == "scheduled"


def test_client_get_competitions_mock() -> None:
    client = FootballDataClient(api_key="x", enabled=True)

    def fake_get(path: str, params: dict | None = None) -> dict:
        client.last_error_code = OK
        return {"competitions": [{"code": "WC", "name": "World Cup"}]}

    client._get = fake_get  # type: ignore[method-assign]
    comps = client.get_competitions()
    assert client.last_error_code == OK
    assert comps[0]["code"] == "WC"
