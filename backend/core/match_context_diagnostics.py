"""Phase 4L — Match context diagnostics (fixture state + host/venue visibility)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from core.fixture_state import (
    HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO,
    FixtureState,
)
from core.global_ratings import english_name
from data.wc2026_venues import lookup_coordinates, normalize_city

WC2026_HOST_NATIONS: frozenset[str] = frozenset(
    {
        "Canada",
        "USA",
        "United States",
        "Mexico",
        "מקסיקו",
    }
)

_CANADA_CITIES = frozenset({"toronto", "vancouver"})
_MEXICO_CITIES = frozenset({"guadalajara", "mexico city", "monterrey"})


def venue_country_from_city(city: str | None) -> str | None:
    """Map WC2026 venue city to host country when known in repo metadata."""
    if not city:
        return None
    key = normalize_city(city)
    if key in _CANADA_CITIES:
        return "Canada"
    if key in _MEXICO_CITIES:
        return "Mexico"
    if lookup_coordinates(city) is not None:
        return "USA"
    return None


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
    Does not apply advantage — diagnostics only.
    """
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
    neutral_ground_requested: bool
    host_country_match: bool
    host_advantage_candidate_team: str | None
    host_advantage_applied: bool
    home_advantage_value: float
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
            "neutral_ground_requested": self.neutral_ground_requested,
            "host_country_match": self.host_country_match,
            "host_advantage_candidate_team": self.host_advantage_candidate_team,
            "host_advantage_applied": self.host_advantage_applied,
            "home_advantage_value": self.home_advantage_value,
            "venue_context_available": self.venue_context_available,
            "altitude_applied": self.altitude_applied,
            "warnings": list(self.warnings),
        }


def build_match_context_diagnostics(
    *,
    fixture_state: FixtureState,
    neutral_ground_requested: bool,
    home_advantage_value: float,
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

    host_match, host_candidate = detect_host_country_match(
        home_team=fixture_state.home_team,
        away_team=fixture_state.away_team,
        venue_city=venue_city,
        venue_country=venue_country,
        neutral_ground_requested=neutral_ground_requested,
    )

    if neutral_ground_requested:
        advantage_applied = False
        effective_adv = 0.0
    else:
        effective_adv = float(home_advantage_value)
        advantage_applied = effective_adv > 0.0

    warnings = list(fixture_state.warnings)
    if extra_warnings:
        warnings.extend(extra_warnings)
    warnings = list(dict.fromkeys(warnings))

    if host_match and host_candidate and effective_adv <= 0.0:
        if HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO not in warnings:
            warnings.append(HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO)

    actual_score = None
    if fixture_state.actual_score_available:
        actual_score = {
            "home": int(fixture_state.actual_home_goals or 0),
            "away": int(fixture_state.actual_away_goals or 0),
        }

    venue_context_available = bool(
        venue.city or venue.country or venue.name or request_venue_city
    )
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
        neutral_ground_requested=neutral_ground_requested,
        host_country_match=host_match,
        host_advantage_candidate_team=host_candidate,
        host_advantage_applied=advantage_applied,
        home_advantage_value=effective_adv,
        venue_context_available=venue_context_available,
        altitude_applied=altitude_applied,
        warnings=warnings,
    )
