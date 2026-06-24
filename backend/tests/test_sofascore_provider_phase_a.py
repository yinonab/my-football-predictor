"""Phase A — Sofascore provider adapter tests (fixtures only; no live API)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data.sofascore import (
    KNOWN_SOFASCORE_NT_TEAM_IDS,
    PROVIDER_NAMESPACE,
    SofascoreClient,
    extract_expected_goals_from_statistics,
    extract_shot_xg_from_shotmap,
    is_senior_mens_football_team,
    known_sofascore_nt_team_id,
    parse_last_matches,
    parse_next_matches,
    parse_team_search_results,
    select_national_mens_football_team,
    sofascore_provider_ids,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_known_sofascore_nt_team_id_brazil() -> None:
    assert known_sofascore_nt_team_id("Brazil") == 4748
    assert KNOWN_SOFASCORE_NT_TEAM_IDS["brazil"] == 4748


def test_sofascore_provider_ids_namespaced() -> None:
    assert sofascore_provider_ids(4748) == {"sofascore": 4748}
    assert PROVIDER_NAMESPACE == "sofascore"
    assert "football_data" not in sofascore_provider_ids(4748)
    assert "api_football" not in sofascore_provider_ids(4748)


def test_select_national_mens_football_team_brazil() -> None:
    payload = _load_fixture("sofascore_team_search_brazil.json")
    teams = parse_team_search_results(payload)
    assert len(teams) == 4

    selected = select_national_mens_football_team(
        teams,
        expected_name="Brazil",
        expected_code="BRA",
    )
    assert selected is not None
    assert selected["id"] == 4748
    assert selected["name"] == "Brazil"


def test_select_rejects_women_u23_and_non_football() -> None:
    payload = _load_fixture("sofascore_team_search_brazil.json")
    teams = parse_team_search_results(payload)

    for team in teams:
        tid = team["id"]
        if tid == 4748:
            assert is_senior_mens_football_team(team) is True
        else:
            assert is_senior_mens_football_team(team) is False

    filtered = [t for t in teams if is_senior_mens_football_team(t)]
    assert len(filtered) == 1
    assert filtered[0]["id"] == 4748


def test_parse_last_matches_team_perspective() -> None:
    payload = _load_fixture("sofascore_last_matches_brazil_sample.json")
    rows = parse_last_matches(payload, team_id=4748)
    assert len(rows) == 1

    row = rows[0]
    assert row["provider"] == "sofascore"
    assert row["provider_match_id"] == 12456789
    assert row["team"] == "Brazil"
    assert row["opponent"] == "Mexico"
    assert row["goals_for"] == 2
    assert row["goals_against"] == 0
    assert row["is_home"] is True
    assert row["status"]["type"] == "finished"
    assert row["tournament"]["name"] == "International Friendly"
    assert row["uniqueTournament"]["id"] == 851
    assert row["season"]["name"] == "International Friendly 2025"
    assert row["homeTeam"]["nameCode"] == "BRA"
    assert row["awayTeam"]["ranking"] == 14
    assert row["hasXg"] is True


def test_parse_next_matches_world_cup_fields() -> None:
    payload = _load_fixture("sofascore_next_matches_brazil_sample.json")
    rows = parse_next_matches(payload, team_id=4748)
    assert len(rows) == 1

    row = rows[0]
    assert row["provider_match_id"] == 13579246
    assert row["uniqueTournament"]["name"] == "World Cup"
    assert row["season"]["name"] == "World Cup 2026"
    assert row["roundInfo"]["name"] == "Group A"
    assert row["tournament"]["name"] == "World Cup"
    assert row["status"]["type"] == "notstarted"
    assert row["team"] == "Brazil"
    assert row["opponent"] == "Morocco"


def test_extract_expected_goals_from_statistics() -> None:
    payload = _load_fixture("sofascore_statistics_expected_goals_sample.json")
    xg = extract_expected_goals_from_statistics(payload)
    assert xg["home_expected_goals"] == pytest.approx(1.82)
    assert xg["away_expected_goals"] == pytest.approx(0.94)


def test_extract_shot_xg_from_shotmap() -> None:
    payload = _load_fixture("sofascore_shotmap_xg_sample.json")
    shots = extract_shot_xg_from_shotmap(payload)
    assert len(shots) == 2

    goal_shot = shots[0]
    assert goal_shot["player_name"] == "Vinicius Junior"
    assert goal_shot["isHome"] is True
    assert goal_shot["shotType"] == "goal"
    assert goal_shot["xg"] == pytest.approx(0.45)
    assert goal_shot["xgot"] == pytest.approx(0.92)
    assert goal_shot["time"] == 23
    assert goal_shot["incidentType"] == "shot"

    miss_shot = shots[1]
    assert miss_shot["xg"] == pytest.approx(0.12)
    assert "xgot" not in miss_shot


def test_client_204_returns_empty_optional_result() -> None:
    client = SofascoreClient(api_key="test-key", enabled=True)
    response = MagicMock()
    response.status_code = 204
    response.json.side_effect = AssertionError("204 should not call json()")

    with patch("data.sofascore.requests.get", return_value=response) as mock_get:
        result = client.get_match_statistics(999)

    assert result is None
    assert client.last_error_code == "OK"
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["params"] == {"matchId": 999}


@pytest.mark.parametrize(
    ("method_name", "path", "match_id"),
    [
        ("get_match_detail", "/matches/detail", 111),
        ("get_match_statistics", "/matches/get-statistics", 222),
        ("get_match_shotmap", "/matches/get-shotmap", 333),
        ("get_match_incidents", "/matches/get-incidents", 444),
        ("get_match_lineups", "/matches/get-lineups", 555),
        ("get_match_h2h", "/matches/get-h2h", 666),
    ],
)
def test_enrichment_methods_use_match_id_param(
    method_name: str,
    path: str,
    match_id: int,
) -> None:
    client = SofascoreClient(api_key="test-key", enabled=True)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}

    with patch("data.sofascore.requests.get", return_value=response) as mock_get:
        getattr(client, method_name)(match_id)

    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"] == {"matchId": match_id}
    assert "eventId" not in call_kwargs["params"]
    assert path in mock_get.call_args.args[0]


def test_client_non_200_returns_none_without_raising() -> None:
    client = SofascoreClient(api_key="test-key", enabled=True)
    response = MagicMock()
    response.status_code = 429

    with patch("data.sofascore.requests.get", return_value=response):
        result = client.search_teams("Brazil")

    assert result == []
    assert client.last_error_code == "HTTP_ERROR"


def test_client_disabled_without_key_does_not_require_key_for_parsers() -> None:
    client = SofascoreClient(api_key="", enabled=False)
    assert client.is_available is False
    assert client.search_teams("Brazil") == []


def test_get_last_matches_uses_team_id_param() -> None:
    client = SofascoreClient(api_key="test-key", enabled=True)
    fixture = _load_fixture("sofascore_last_matches_brazil_sample.json")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = fixture

    with patch("data.sofascore.requests.get", return_value=response) as mock_get:
        rows = client.get_last_matches(4748)

    assert mock_get.call_args.kwargs["params"] == {"teamId": 4748}
    assert len(rows) == 1
    assert rows[0]["team"] == "Brazil"
