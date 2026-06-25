"""WC 2026 host city coordinates for weather and travel distance."""

from __future__ import annotations

# lat, lon — major World Cup 2026 venue cities
VENUE_COORDINATES: dict[str, tuple[float, float]] = {
    "atlanta": (33.75, -84.39),
    "boston": (42.36, -71.06),
    "dallas": (32.78, -96.80),
    "east rutherford": (40.81, -74.07),
    "new york": (40.71, -74.01),
    "houston": (29.76, -95.37),
    "kansas city": (39.10, -94.58),
    "los angeles": (34.05, -118.24),
    "miami": (25.76, -80.19),
    "philadelphia": (39.95, -75.17),
    "san francisco": (37.77, -122.42),
    "santa clara": (37.35, -121.97),
    "seattle": (47.61, -122.33),
    "guadalajara": (20.67, -103.35),
    "mexico city": (19.43, -99.13),
    "monterrey": (25.67, -100.31),
    "toronto": (43.65, -79.38),
    "vancouver": (49.28, -123.12),
}


def normalize_city(name: str) -> str:
    return name.strip().lower().replace("'", "")


def lookup_coordinates(city: str | None) -> tuple[float, float] | None:
    if not city:
        return None
    key = normalize_city(city)
    if key in VENUE_COORDINATES:
        return VENUE_COORDINATES[key]
    for label, coords in VENUE_COORDINATES.items():
        if label in key or key in label:
            return coords
    from data.wc2026_stadiums import lookup_coordinates_from_stadiums

    return lookup_coordinates_from_stadiums(city)
