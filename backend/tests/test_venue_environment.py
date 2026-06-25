"""Phase W1+W2 — venue environment resolver and altitude bucket tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.venue_environment import (
    altitude_bucket_for_elevation,
    normalize_venue_key,
    resolve_wc2026_venue_environment,
)
from data.wc2026_stadiums import lookup_stadium


def test_mexico_city_azteca_very_high() -> None:
    stadium = lookup_stadium("Estadio Azteca")
    assert stadium is not None
    assert stadium.elevation_m == 2240
    assert stadium.altitude_bucket == "very_high"

    resolved = resolve_wc2026_venue_environment(venue_city="Mexico City")
    assert resolved.elevation_m == 2240
    assert resolved.altitude_bucket == "very_high"
    assert resolved.altitude_source == "static_metadata"
    assert resolved.stadium_name == "Estadio Azteca"


def test_guadalajara_high() -> None:
    resolved = resolve_wc2026_venue_environment(venue_city="Guadalajara")
    assert resolved.elevation_m == 1566
    assert resolved.altitude_bucket == "high"


def test_monterrey_low() -> None:
    resolved = resolve_wc2026_venue_environment(venue_city="Monterrey")
    assert resolved.elevation_m == 540
    assert resolved.altitude_bucket == "low"


def test_miami_sea_level() -> None:
    resolved = resolve_wc2026_venue_environment(venue_city="Miami")
    assert resolved.elevation_m == 3
    assert resolved.altitude_bucket == "sea_level"
    assert resolved.country == "USA"


def test_toronto_sea_level() -> None:
    resolved = resolve_wc2026_venue_environment(venue_city="Toronto")
    assert resolved.elevation_m == 75
    assert resolved.altitude_bucket == "sea_level"
    assert resolved.country == "Canada"


def test_unknown_venue_no_crash() -> None:
    resolved = resolve_wc2026_venue_environment(venue_city="Lisbon")
    assert resolved.elevation_m is None
    assert resolved.altitude_bucket == "unknown"
    assert resolved.altitude_source == "unknown"
    assert any("venue_not_in_wc2026_metadata" in w for w in resolved.warnings)


def test_normalize_venue_key_strips_accents() -> None:
    assert normalize_venue_key("Ciudad de México") == "ciudad de mexico"


def test_altitude_bucket_thresholds() -> None:
    assert altitude_bucket_for_elevation(50) == "sea_level"
    assert altitude_bucket_for_elevation(500) == "low"
    assert altitude_bucket_for_elevation(900) == "moderate"
    assert altitude_bucket_for_elevation(1400) == "high"
    assert altitude_bucket_for_elevation(2240) == "very_high"
    assert altitude_bucket_for_elevation(None) == "unknown"
