"""WC2026 venue environment resolution and diagnostics (Phase W1+W2).

Diagnostic-only: auto-resolved altitude is never passed into active power math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import config
from core.context_adjustments import _weather_xg_delta
from core.fixture_state import FixtureState
from core.match_context import MatchContextInfo
from data.wc2026_stadiums import (
    Wc2026Stadium,
    altitude_bucket_for_elevation,
    lookup_stadium,
)

AltitudeSource = Literal["static_metadata", "request_override", "unknown"]
WeatherSource = Literal["open-meteo", "not_requested", "unavailable", "disabled"]
WeatherAdjustmentMode = Literal[
    "none", "active_existing", "shadow_only", "unavailable", "disabled"
]
AutomaticAltitudeMode = Literal["diagnostic_only", "active_when_resolved"]


def normalize_venue_key(value: str | None) -> str:
    if not value:
        return ""
    return (
        str(value)
        .strip()
        .lower()
        .replace("'", "")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


@dataclass
class ResolvedVenueEnvironment:
    stadium_name: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: int | None = None
    altitude_bucket: str = "unknown"
    altitude_source: AltitudeSource = "unknown"
    stadium: Wc2026Stadium | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stadium_name": self.stadium_name,
            "city": self.city,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "altitude_bucket": self.altitude_bucket,
            "altitude_source": self.altitude_source,
            "warnings": list(self.warnings),
        }


def resolve_wc2026_venue_environment(
    *,
    venue_city: str | None = None,
    venue_name: str | None = None,
    venue_country: str | None = None,
    fixture_venue_city: str | None = None,
    fixture_venue_name: str | None = None,
    fixture_venue_country: str | None = None,
) -> ResolvedVenueEnvironment:
    """Resolve WC2026 stadium metadata from request and fixture hints."""
    warnings: list[str] = []
    candidates: list[tuple[str, str]] = []
    if venue_name:
        candidates.append(("request", venue_name))
    if venue_city:
        candidates.append(("request", venue_city))
    if fixture_venue_name:
        candidates.append(("fixture", fixture_venue_name))
    if fixture_venue_city:
        candidates.append(("fixture", fixture_venue_city))

    stadium: Wc2026Stadium | None = None
    matched_from: str | None = None
    for source, value in candidates:
        hit = lookup_stadium(value)
        if hit is not None:
            if stadium is not None and hit.stadium_id != stadium.stadium_id:
                warnings.append(
                    f"ambiguous_venue_match:{normalize_venue_key(value)}"
                )
            stadium = hit
            matched_from = source

    if stadium is None:
        unresolved = venue_city or fixture_venue_city or venue_name or fixture_venue_name
        if unresolved:
            warnings.append(f"venue_not_in_wc2026_metadata:{unresolved}")
        return ResolvedVenueEnvironment(
            city=venue_city or fixture_venue_city,
            country=venue_country or fixture_venue_country,
            stadium_name=venue_name or fixture_venue_name,
            warnings=warnings,
        )

    country = venue_country or fixture_venue_country or stadium.country
    return ResolvedVenueEnvironment(
        stadium_name=stadium.stadium_name,
        city=stadium.city,
        country=country,
        latitude=stadium.latitude,
        longitude=stadium.longitude,
        elevation_m=stadium.elevation_m,
        altitude_bucket=stadium.altitude_bucket,
        altitude_source="static_metadata",
        stadium=stadium,
        warnings=warnings if matched_from == "fixture" and (venue_city or venue_name) else warnings,
    )


def resolve_effective_altitude_m(
    *,
    request_altitude: int,
    venue_city: str | None,
    fixture_venue_city: str | None = None,
    fixture_venue_name: str | None = None,
) -> tuple[int, bool, str]:
    """
    Effective altitude for power modifiers.

    Manual request.altitude wins. Otherwise, when enabled, use WC2026 stadium
    metadata elevation from venue_city / fixture hints.
    """
    if request_altitude > 0:
        return request_altitude, False, "request_override"

    if not config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION:
        return 0, False, "disabled"

    resolved = resolve_wc2026_venue_environment(
        venue_city=venue_city,
        fixture_venue_city=fixture_venue_city,
        fixture_venue_name=fixture_venue_name,
    )
    if resolved.elevation_m is None:
        return 0, False, "unknown"
    return resolved.elevation_m, True, "static_metadata"


def _automatic_altitude_mode(*, auto_stadium_applied: bool) -> AutomaticAltitudeMode:
    if not config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION:
        return "diagnostic_only"
    return "active_when_resolved"


def _shadow_altitude_power_multiplier(elevation_m: int | None) -> float | None:
    if elevation_m is None:
        return None
    if elevation_m > config.ALTITUDE_THRESHOLD_M:
        return round(1.0 - config.ALTITUDE_PENALTY, 4)
    return 1.0


def _weather_adjustment_mode(
    *,
    use_match_context: bool,
    venue_requested: bool,
    weather_available: bool,
    active_xg_delta: float,
) -> WeatherAdjustmentMode:
    if not use_match_context:
        return "disabled"
    if not venue_requested:
        return "none"
    if not weather_available:
        return "unavailable"
    if abs(active_xg_delta) > 1e-6:
        return "active_existing"
    return "none"


def build_environment_diagnostics(
    *,
    request_venue_city: str | None,
    request_altitude: int,
    use_match_context: bool,
    fixture_state: FixtureState,
    ctx_info: MatchContextInfo,
    active_weather_xg_delta: float,
    weather_fetched_at: str | None = None,
    effective_altitude_m: int = 0,
    auto_stadium_altitude_applied: bool = False,
) -> dict[str, Any]:
    resolved = resolve_wc2026_venue_environment(
        venue_city=request_venue_city,
        fixture_venue_city=fixture_state.venue_city,
        fixture_venue_name=fixture_state.venue_name,
        fixture_venue_country=fixture_state.venue_country,
    )

    venue_for_weather = (
        request_venue_city
        or ctx_info.venue_city
        or fixture_state.venue_city
        or resolved.city
    )
    venue_requested = bool(venue_for_weather)

    weather_available = (
        ctx_info.weather_temp_c is not None or ctx_info.weather_rain_mm is not None
    )

    if not use_match_context:
        weather_source: WeatherSource = "disabled"
    elif not venue_requested:
        weather_source = "not_requested"
    elif weather_available:
        weather_source = "open-meteo"
    else:
        weather_source = "unavailable"

    shadow_xg_delta, _ = _weather_xg_delta(
        ctx_info.weather_rain_mm,
        ctx_info.weather_temp_c,
    )
    if not weather_available and venue_requested and use_match_context:
        shadow_xg_delta = 0.0

    weather_mode = _weather_adjustment_mode(
        use_match_context=use_match_context,
        venue_requested=venue_requested,
        weather_available=weather_available,
        active_xg_delta=active_weather_xg_delta if use_match_context else 0.0,
    )

    manual_altitude_applied = (
        request_altitude > config.ALTITUDE_THRESHOLD_M
        or (
            auto_stadium_altitude_applied
            and effective_altitude_m > config.ALTITUDE_THRESHOLD_M
        )
    )
    request_elevation = request_altitude if request_altitude > 0 else None

    display_elevation = resolved.elevation_m
    altitude_source = resolved.altitude_source
    altitude_bucket = resolved.altitude_bucket
    if request_elevation is not None:
        display_elevation = request_elevation
        altitude_source = "request_override"
        altitude_bucket = altitude_bucket_for_elevation(request_elevation)
    elif auto_stadium_altitude_applied and effective_altitude_m > 0:
        display_elevation = effective_altitude_m
        altitude_source = "static_metadata"
        altitude_bucket = altitude_bucket_for_elevation(effective_altitude_m)

    shadow_alt_mult = _shadow_altitude_power_multiplier(
        display_elevation or resolved.elevation_m
    )

    auto_alt_mode = _automatic_altitude_mode(
        auto_stadium_applied=auto_stadium_altitude_applied
    )

    notes: list[str] = []
    if resolved.altitude_source == "static_metadata" and resolved.elevation_m:
        if resolved.elevation_m > config.ALTITUDE_THRESHOLD_M:
            if auto_stadium_altitude_applied:
                notes.append(
                    f"High-altitude venue ({resolved.elevation_m}m) — "
                    "stadium altitude power adjustment is active"
                )
            else:
                notes.append(
                    f"High-altitude venue ({resolved.elevation_m}m) — "
                    "automatic altitude adjustment is disabled"
                )
    if weather_mode == "shadow_only":
        notes.append(
            "Weather data available but match context disabled — "
            "weather xG adjustment not applied"
        )
    if weather_mode == "active_existing":
        notes.append("Existing weather xG adjustment is active for this request")

    warnings = list(resolved.warnings)
    if weather_source == "unavailable" and venue_requested and use_match_context:
        warnings.append("WEATHER_FETCH_UNAVAILABLE")
    if altitude_source == "unknown" and venue_requested:
        warnings.append("VENUE_ALTITUDE_UNKNOWN")

    return {
        "venue_city": resolved.city or venue_for_weather,
        "venue_country": resolved.country or fixture_state.venue_country,
        "venue_stadium": resolved.stadium_name or fixture_state.venue_name,
        "venue_latitude": resolved.latitude,
        "venue_longitude": resolved.longitude,
        "venue_altitude_m": display_elevation,
        "altitude_bucket": altitude_bucket,
        "altitude_source": altitude_source,
        "request_altitude_m": request_elevation,
        "manual_altitude_applied": manual_altitude_applied,
        "active_altitude_threshold_m": config.ALTITUDE_THRESHOLD_M,
        "automatic_altitude_adjustment_mode": auto_alt_mode,
        "weather_source": weather_source,
        "weather_fetched_at": weather_fetched_at,
        "temperature_c": ctx_info.weather_temp_c,
        "precipitation_mm": ctx_info.weather_rain_mm,
        "weather_summary": ctx_info.weather_summary,
        "weather_adjustment_mode": weather_mode,
        "active_weather_xg_delta": round(
            active_weather_xg_delta if use_match_context else 0.0, 4
        ),
        "shadow_weather_xg_delta": round(shadow_xg_delta, 4),
        "shadow_altitude_power_multiplier": shadow_alt_mult,
        "environment_notes": notes,
        "environment_warnings": warnings,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
