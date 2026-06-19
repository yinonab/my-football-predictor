"""Phase 4L/4O — Match context diagnostics (fixture state + venue/home advantage)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from core.fixture_state import FixtureState
from core.global_ratings import english_name
from core.venue_advantage import VenueAdvantageContext
from core.venue_geo import WC2026_HOST_NATIONS, venue_country_from_city


def _is_host_nation(team_en: str) -> bool:
    base = team_en.split(" (")[0].strip()
    return base in WC2026_HOST_NATIONS or team_en in WC2026_HOST_NATIONS


def detect_host_country_match(
    *,
    home_team: str,
    away_team: str,
    venue_city: str | None,
    venue_country: str | None,
    neutral_ground_requested: bool,
) -> tuple[bool, str | None]:
    """
    True when the home side is a WC2026 co-host playing in that host country.
    Diagnostics only — advantage application is via venue_mode (Phase 4O).
    """
    del away_team, neutral_ground_requested
    home_en = english_name(home_team) or home_team.split(" (")[0].strip()
    if not _is_host_nation(home_en):
        return False, None

    country = venue_country or venue_country_from_city(venue_city)
    if not country:
        return False, None

    host_country = "USA" if home_en in ("USA", "United States") else home_en
    if country == host_country or (host_country == "USA" and country == "USA"):
        return True, home_en
    return False, None


@dataclass
class VenueDiagnostics:
    name: str | None = None
    city: str | None = None
    country: str | None = None
    altitude_meters: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "city": self.city,
            "country": self.country,
            "altitude_meters": self.altitude_meters,
        }


@dataclass
class MatchContextDiagnostics:
    fixture_status: str
    prediction_valid: bool
    prediction_mode: str
    actual_score: dict[str, int] | None
    kickoff_time_utc: str | None
    fixture_source: str
    fixture_source_available: bool
    venue: VenueDiagnostics
    venue_mode: str
    neutral_ground_requested: bool
    home_advantage_team: str
    host_country_match: bool
    host_advantage_candidate_team: str | None
    host_advantage_applied: bool
    home_advantage_value: float
    home_advantage_power_delta: float
    venue_context_available: bool
    altitude_applied: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_status": self.fixture_status,
            "prediction_valid": self.prediction_valid,
            "prediction_mode": self.prediction_mode,
            "actual_score": self.actual_score,
            "kickoff_time_utc": self.kickoff_time_utc,
            "fixture_source": self.fixture_source,
            "fixture_source_available": self.fixture_source_available,
            "venue": self.venue.to_dict(),
            "venue_mode": self.venue_mode,
            "neutral_ground_requested": self.neutral_ground_requested,
            "home_advantage_team": self.home_advantage_team,
            "host_country_match": self.host_country_match,
            "host_advantage_candidate_team": self.host_advantage_candidate_team,
            "host_advantage_applied": self.host_advantage_applied,
            "home_advantage_value": self.home_advantage_value,
            "home_advantage_power_delta": self.home_advantage_power_delta,
            "venue_context_available": self.venue_context_available,
            "altitude_applied": self.altitude_applied,
            "warnings": list(self.warnings),
        }


def build_match_context_diagnostics(
    *,
    fixture_state: FixtureState,
    neutral_ground_requested: bool,
    venue_advantage: VenueAdvantageContext,
    request_venue_city: str | None,
    request_altitude: int,
    extra_warnings: list[str] | None = None,
) -> MatchContextDiagnostics:
    venue_city = fixture_state.venue_city or request_venue_city
    venue_country = fixture_state.venue_country or venue_country_from_city(venue_city)
    venue = VenueDiagnostics(
        name=fixture_state.venue_name,
        city=venue_city,
        country=venue_country,
        altitude_meters=request_altitude if request_altitude > 0 else None,
    )

    warnings = list(fixture_state.warnings)
    warnings.extend(venue_advantage.warnings)
    if extra_warnings:
        warnings.extend(extra_warnings)
    warnings = list(dict.fromkeys(warnings))

    actual_score = None
    if fixture_state.actual_score_available:
        actual_score = {
            "home": int(fixture_state.actual_home_goals or 0),
            "away": int(fixture_state.actual_away_goals or 0),
        }

    altitude_applied = request_altitude > config.ALTITUDE_THRESHOLD_M

    return MatchContextDiagnostics(
        fixture_status=fixture_state.fixture_status,
        prediction_valid=fixture_state.prediction_valid,
        prediction_mode=fixture_state.prediction_mode,
        actual_score=actual_score,
        kickoff_time_utc=fixture_state.kickoff_time_utc,
        fixture_source=fixture_state.source,
        fixture_source_available=fixture_state.source_available,
        venue=venue,
        venue_mode=venue_advantage.venue_mode,
        neutral_ground_requested=neutral_ground_requested,
        home_advantage_team=venue_advantage.home_advantage_team,
        host_country_match=venue_advantage.host_country_match,
        host_advantage_candidate_team=venue_advantage.host_advantage_candidate_team,
        host_advantage_applied=venue_advantage.home_advantage_applied,
        home_advantage_value=venue_advantage.home_advantage_value,
        home_advantage_power_delta=venue_advantage.home_advantage_power_delta,
        venue_context_available=venue_advantage.venue_context_available,
        altitude_applied=altitude_applied,
        warnings=warnings,
    )
