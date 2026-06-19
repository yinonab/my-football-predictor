"""Convert football-data.org matches to internal FixtureState."""

from __future__ import annotations

from typing import Any

from core.fixture_state import (
    FIXTURE_POSTPONED_OR_CANCELLED,
    MATCH_IN_PROGRESS,
    FixtureState,
)
from core.football_data_teams import normalize_team_key, teams_match

_FINISHED = frozenset({"FINISHED"})
_LIVE = frozenset({"IN_PLAY", "PAUSED"})
_SCHEDULED = frozenset({"TIMED", "SCHEDULED"})
_UNAVAILABLE = frozenset({"POSTPONED", "SUSPENDED", "CANCELED", "CANCELLED"})


def map_football_data_status(status: str) -> str:
    s = (status or "").upper()
    if s in _FINISHED:
        return "completed"
    if s in _LIVE:
        return "live"
    if s in _SCHEDULED:
        return "scheduled"
    if s in _UNAVAILABLE:
        return "unknown"
    return "unknown"


def find_football_data_match(
    matches: list[dict[str, Any]],
    home_en: str,
    away_en: str,
) -> dict[str, Any] | None:
    """Find best WC match for a home/away pair (home side orientation preserved)."""
    candidates: list[dict[str, Any]] = []
    for match in matches:
        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}
        if teams_match(home_en, home_team) and teams_match(away_en, away_team):
            candidates.append(match)
        elif teams_match(home_en, away_team) and teams_match(away_en, home_team):
            candidates.append(match)

    if not candidates:
        return None

    def priority(m: dict[str, Any]) -> tuple[int, str]:
        status = map_football_data_status(str(m.get("status") or ""))
        rank = {"completed": 3, "live": 2, "scheduled": 1}.get(status, 0)
        return (rank, str(m.get("utcDate") or ""))

    return sorted(candidates, key=priority, reverse=True)[0]


def _is_swapped(match: dict[str, Any], home_en: str) -> bool:
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    if teams_match(home_en, home_team):
        return False
    if teams_match(home_en, away_team):
        return True
    return normalize_team_key(home_en) != normalize_team_key(
        str(home_team.get("name") or "")
    )


def state_from_football_data_match(
    home_resolved: str,
    away_resolved: str,
    match: dict[str, Any],
) -> FixtureState:
    home_en = home_resolved.split(" (")[0].strip()
    swap = _is_swapped(match, home_en)

    status_raw = str(match.get("status") or "")
    fixture_status = map_football_data_status(status_raw)
    kickoff = match.get("utcDate")

    ah: int | None = None
    aa: int | None = None
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    if full_time.get("home") is not None and full_time.get("away") is not None:
        ah = int(full_time["home"])
        aa = int(full_time["away"])
        if swap:
            ah, aa = aa, ah

    venue = match.get("venue") or {}
    warnings: list[str] = []
    if fixture_status == "live":
        warnings.append(MATCH_IN_PROGRESS)
    if status_raw.upper() in _UNAVAILABLE:
        warnings.append(FIXTURE_POSTPONED_OR_CANCELLED)

    return FixtureState(
        home_team=home_resolved,
        away_team=away_resolved,
        fixture_status=fixture_status,  # type: ignore[arg-type]
        kickoff_time_utc=kickoff,
        actual_home_goals=ah,
        actual_away_goals=aa,
        actual_score_available=ah is not None and aa is not None,
        source="football-data.org",
        source_available=True,
        venue_name=venue.get("name") if isinstance(venue, dict) else None,
        venue_city=venue.get("city") if isinstance(venue, dict) else None,
        warnings=warnings,
    )
