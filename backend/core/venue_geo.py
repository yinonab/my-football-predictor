"""WC2026 venue city/country helpers (shared by diagnostics and venue advantage)."""

from __future__ import annotations

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
