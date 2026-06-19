"""Phase 4O — Venue mode and home advantage resolution (power-scale, no team swap)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import config
from core.fixture_state import HOST_COUNTRY_AUTO_UNAVAILABLE, FixtureState
from core.global_ratings import english_name
from core.venue_geo import venue_country_from_city

VenueMode = Literal["neutral", "first_team_home", "second_team_home", "host_country_auto"]
HomeAdvantageTeam = Literal["none", "home", "away"]

VENUE_MODE_NEUTRAL: VenueMode = "neutral"
VENUE_MODE_FIRST_HOME: VenueMode = "first_team_home"
VENUE_MODE_SECOND_HOME: VenueMode = "second_team_home"
VENUE_MODE_HOST_AUTO: VenueMode = "host_country_auto"

_HOST_NATION_ALIASES: dict[str, frozenset[str]] = {
    "USA": frozenset({"usa", "united states"}),
    "Canada": frozenset({"canada"}),
    "Mexico": frozenset({"mexico"}),
}


def resolve_venue_mode(
    *,
    venue_mode: str | None,
    neutral_ground: bool,
) -> VenueMode:
    """Map API input to venue mode; venue_mode takes precedence over neutral_ground."""
    if venue_mode:
        mode = venue_mode.strip().lower()
        allowed = {
            VENUE_MODE_NEUTRAL,
            VENUE_MODE_FIRST_HOME,
            VENUE_MODE_SECOND_HOME,
            VENUE_MODE_HOST_AUTO,
        }
        if mode in allowed:
            return mode  # type: ignore[return-value]
    return VENUE_MODE_NEUTRAL if neutral_ground else VENUE_MODE_FIRST_HOME


def _team_en(team: str) -> str:
    return english_name(team) or team.split(" (")[0].strip()


def _normalize_host_country(country: str | None) -> str | None:
    if not country:
        return None
    c = country.strip()
    if c in ("USA", "United States"):
        return "USA"
    if c == "Canada":
        return "Canada"
    if c == "Mexico":
        return "Mexico"
    return None


def _team_matches_host_nation(team_en: str, host_nation: str) -> bool:
    key = team_en.lower().replace("'", "")
    aliases = _HOST_NATION_ALIASES.get(host_nation, frozenset())
    return key in aliases or team_en == host_nation


def resolve_host_country_advantage_team(
    *,
    home_team: str,
    away_team: str,
    venue_city: str | None,
    venue_country: str | None,
) -> tuple[HomeAdvantageTeam, str | None, bool, list[str]]:
    """
    Derive which displayed side gets host-country advantage.
    Returns (side, candidate_team_en, host_country_match, warnings).
    """
    country = _normalize_host_country(venue_country) or _normalize_host_country(
        venue_country_from_city(venue_city)
    )
    if not country:
        return "none", None, False, [HOST_COUNTRY_AUTO_UNAVAILABLE]

    home_en = _team_en(home_team)
    away_en = _team_en(away_team)
    home_is_host = _team_matches_host_nation(home_en, country)
    away_is_host = _team_matches_host_nation(away_en, country)

    if home_is_host:
        return "home", home_en, True, []
    if away_is_host:
        return "away", away_en, True, []
    return "none", None, False, []


def effective_home_advantage_points(request_override: float) -> float:
    """Use explicit request override when > 0, else configured default."""
    if request_override > 0:
        return float(request_override)
    return float(config.HOME_ADVANTAGE_POWER_POINTS)


@dataclass
class VenueAdvantageContext:
    venue_mode: VenueMode
    home_advantage_team: HomeAdvantageTeam
    home_advantage_applied: bool
    home_advantage_value: float
    home_advantage_power_delta: float
    host_country_match: bool
    host_advantage_candidate_team: str | None
    venue_context_available: bool
    warnings: list[str] = field(default_factory=list)


def resolve_venue_advantage(
    *,
    home_team: str,
    away_team: str,
    fixture_state: FixtureState,
    venue_mode: str | None,
    neutral_ground: bool,
    request_home_advantage: float,
    request_venue_city: str | None,
    request_altitude: int,
) -> VenueAdvantageContext:
    resolved_mode = resolve_venue_mode(
        venue_mode=venue_mode,
        neutral_ground=neutral_ground,
    )
    venue_city = fixture_state.venue_city or request_venue_city
    venue_country = fixture_state.venue_country or venue_country_from_city(venue_city)
    venue_context_available = bool(
        venue_city or venue_country or fixture_state.venue_name or request_venue_city
    )

    warnings: list[str] = []
    host_match = False
    host_candidate: str | None = None
    advantage_team: HomeAdvantageTeam = "none"

    if resolved_mode == VENUE_MODE_NEUTRAL:
        advantage_team = "none"
    elif resolved_mode == VENUE_MODE_FIRST_HOME:
        advantage_team = "home"
    elif resolved_mode == VENUE_MODE_SECOND_HOME:
        advantage_team = "away"
    elif resolved_mode == VENUE_MODE_HOST_AUTO:
        advantage_team, host_candidate, host_match, auto_warnings = (
            resolve_host_country_advantage_team(
                home_team=home_team,
                away_team=away_team,
                venue_city=venue_city,
                venue_country=venue_country,
            )
        )
        warnings.extend(auto_warnings)

    points = (
        effective_home_advantage_points(request_home_advantage)
        if advantage_team != "none"
        else 0.0
    )
    applied = advantage_team != "none" and points > 0.0
    power_delta = points if applied else 0.0

    if resolved_mode == VENUE_MODE_HOST_AUTO and advantage_team == "none" and host_match:
        host_candidate = host_candidate

    if resolved_mode in (VENUE_MODE_FIRST_HOME, VENUE_MODE_SECOND_HOME):
        host_side, candidate, detected, _ = resolve_host_country_advantage_team(
            home_team=home_team,
            away_team=away_team,
            venue_city=venue_city,
            venue_country=venue_country,
        )
        if detected:
            host_match = True
            host_candidate = candidate
        elif resolved_mode == VENUE_MODE_FIRST_HOME:
            home_en = _team_en(home_team)
            if home_en in ("Canada", "USA", "United States", "Mexico"):
                host_match, host_candidate = True, home_en

    return VenueAdvantageContext(
        venue_mode=resolved_mode,
        home_advantage_team=advantage_team,
        home_advantage_applied=applied,
        home_advantage_value=points if applied else 0.0,
        home_advantage_power_delta=power_delta,
        host_country_match=host_match,
        host_advantage_candidate_team=host_candidate,
        venue_context_available=venue_context_available,
        warnings=warnings,
    )


def elo_advantage_for_pipeline(
    ctx: VenueAdvantageContext,
    *,
    home_elo: float | None,
    away_elo: float | None,
) -> float:
    """
    Dixon-Coles / Maher blend uses Elo gap when Elo is available — mirror HA there.
    When only composite power is used, HA is already in boosted power (return 0).
    """
    if not ctx.home_advantage_applied:
        return 0.0
    if home_elo is not None and away_elo is not None:
        delta = ctx.home_advantage_power_delta
        if ctx.home_advantage_team == "home":
            return delta
        if ctx.home_advantage_team == "away":
            return -delta
    return 0.0


def apply_home_advantage_to_powers(
    home_power: float,
    away_power: float,
    ctx: VenueAdvantageContext,
) -> tuple[float, float]:
    """Add configured home-advantage points to the benefiting side only."""
    if not ctx.home_advantage_applied:
        return home_power, away_power
    delta = ctx.home_advantage_power_delta
    if ctx.home_advantage_team == "home":
        return home_power + delta, away_power
    if ctx.home_advantage_team == "away":
        return home_power, away_power + delta
    return home_power, away_power
