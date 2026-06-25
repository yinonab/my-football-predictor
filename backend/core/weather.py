"""Open-Meteo weather for match-day context (free, no API key)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests

from data.wc2026_venues import lookup_coordinates

logger = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 12


@dataclass(frozen=True)
class WeatherSnapshot:
    city: str
    match_date: str
    temperature_c: float | None
    rain_mm: float | None
    summary_he: str
    fetched_at: str | None = None


def fetch_match_weather(
    city: str,
    match_date: str | None = None,
) -> WeatherSnapshot | None:
    """Hourly aggregate for match day at venue city."""
    coords = lookup_coordinates(city)
    if not coords:
        return None

    day = match_date or date.today().isoformat()
    lat, lon = coords
    try:
        response = requests.get(
            OPEN_METEO,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "precipitation,temperature_2m",
                "start_date": day,
                "end_date": day,
                "timezone": "auto",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        hourly = response.json().get("hourly") or {}
        temps = hourly.get("temperature_2m") or []
        rain = hourly.get("precipitation") or []
        if not temps:
            return None

        temp = round(sum(temps) / len(temps), 1)
        rain_total = round(sum(rain), 1) if rain else 0.0

        parts: list[str] = [f"{city}: {temp}°C"]
        if rain_total >= 1.0:
            parts.append(f"גשם ~{rain_total} מ\"מ")
        elif rain_total >= 0.2:
            parts.append("גשם קל")
        if temp >= 32:
            parts.append("חום")
        elif temp <= 5:
            parts.append("קור")

        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return WeatherSnapshot(
            city=city,
            match_date=day,
            temperature_c=temp,
            rain_mm=rain_total,
            summary_he=", ".join(parts),
            fetched_at=fetched_at,
        )
    except Exception as exc:
        logger.warning("Weather fetch failed for %s: %s", city, exc)
        return None
