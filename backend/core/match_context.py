"""Gather automatic match context: rest, travel, stage, weather."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import config
from core.weather import WeatherSnapshot, fetch_match_weather
from data.api_football import ApiFootballClient
from data.wc2026_venues import lookup_coordinates

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "team_context_cache.json"


@dataclass
class MatchContextInfo:
    home_rest_days: int | None = None
    away_rest_days: int | None = None
    home_last_city: str | None = None
    away_last_city: str | None = None
    venue_city: str | None = None
    match_date: str | None = None
    stage: str | None = None
    away_travel_km: float | None = None
    home_travel_km: float | None = None
    weather_summary: str | None = None
    weather_temp_c: float | None = None
    weather_rain_mm: float | None = None
    data_source: str = "offline"
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _travel_km(from_city: str | None, to_city: str | None) -> float | None:
    c1 = lookup_coordinates(from_city)
    c2 = lookup_coordinates(to_city)
    if not c1 or not c2:
        return None
    return round(_haversine_km(c1[0], c1[1], c2[0], c2[1]), 0)


def _days_since(fixture_date: str, reference: date) -> int:
    try:
        played = date.fromisoformat(fixture_date[:10])
    except ValueError:
        return 0
    return max(0, (reference - played).days)


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_get_team(team_key: str) -> dict[str, Any] | None:
    entry = _load_cache().get("teams", {}).get(team_key)
    if not entry:
        return None
    fetched = entry.get("fetched_at")
    if not fetched:
        return entry
    try:
        ts = datetime.fromisoformat(fetched)
        if datetime.now() - ts > timedelta(hours=config.CONTEXT_CACHE_HOURS):
            return None
    except ValueError:
        pass
    return entry


def _cache_put_team(team_key: str, data: dict[str, Any]) -> None:
    cache = _load_cache()
    teams = cache.setdefault("teams", {})
    data["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    teams[team_key] = data
    _save_cache(cache)


class MatchContextGatherer:
    """Build match context from API-Football + Open-Meteo."""

    def __init__(self, api: ApiFootballClient | None = None) -> None:
        self._api = api or ApiFootballClient()

    def _last_fixture_info(self, team_key: str, english_name: str) -> dict[str, Any]:
        cached = _cache_get_team(team_key)
        if cached:
            return cached

        empty = {"date": None, "city": None, "round": None, "league": None}
        if not self._api.is_available:
            return empty

        try:
            team = self._api.search_national_team(english_name)
            if not team:
                return empty
            fx = self._api.fetch_last_finished_fixture(int(team["id"]))
            if not fx:
                return empty
            info = self._api.extract_fixture_context(fx)
            _cache_put_team(team_key, info)
            return info
        except Exception as exc:
            logger.warning("Context fetch failed for %s: %s", team_key, exc)
            return empty

    def _scheduled_fixture(
        self,
        home_english: str,
        away_english: str,
    ) -> dict[str, Any] | None:
        if not self._api.is_available:
            return None
        try:
            home = self._api.search_national_team(home_english)
            away = self._api.search_national_team(away_english)
            if not home or not away:
                return None
            return self._api.find_scheduled_h2h_fixture(int(home["id"]), int(away["id"]))
        except Exception as exc:
            logger.warning("Scheduled fixture lookup failed: %s", exc)
            return None

    def gather(
        self,
        home_key: str,
        away_key: str,
        *,
        match_date: str | None = None,
        venue_city: str | None = None,
        enabled: bool = True,
    ) -> MatchContextInfo:
        if not enabled:
            return MatchContextInfo(data_source="disabled")

        ref_day = date.fromisoformat(match_date) if match_date else date.today()
        ref_iso = ref_day.isoformat()
        home_en = home_key.split(" (")[0]
        away_en = away_key.split(" (")[0]

        home_last = self._last_fixture_info(home_key, home_en)
        away_last = self._last_fixture_info(away_key, away_en)
        scheduled = self._scheduled_fixture(home_en, away_en)

        stage = None
        venue = venue_city
        if scheduled:
            stage = scheduled.get("round") or scheduled.get("league")
            venue = venue or scheduled.get("city")
            if scheduled.get("date"):
                ref_iso = scheduled["date"][:10]

        home_rest = (
            _days_since(home_last["date"], date.fromisoformat(ref_iso))
            if home_last.get("date")
            else None
        )
        away_rest = (
            _days_since(away_last["date"], date.fromisoformat(ref_iso))
            if away_last.get("date")
            else None
        )

        home_travel = _travel_km(home_last.get("city"), venue) if venue else None
        away_travel = _travel_km(away_last.get("city"), venue) if venue else None

        weather: WeatherSnapshot | None = None
        if venue:
            weather = fetch_match_weather(venue, ref_iso)

        source = "api+weather" if self._api.is_available else "weather" if weather else "offline"
        if self._api.is_available and not weather:
            source = "api"

        notes: list[str] = []
        if home_last.get("date"):
            notes.append(f"בית: משחק אחרון {home_last['date']}" + (f" ({home_last.get('city')})" if home_last.get("city") else ""))
        if away_last.get("date"):
            notes.append(f"חוץ: משחק אחרון {away_last['date']}" + (f" ({away_last.get('city')})" if away_last.get("city") else ""))

        return MatchContextInfo(
            home_rest_days=home_rest,
            away_rest_days=away_rest,
            home_last_city=home_last.get("city"),
            away_last_city=away_last.get("city"),
            venue_city=venue,
            match_date=ref_iso,
            stage=stage,
            away_travel_km=away_travel,
            home_travel_km=home_travel,
            weather_summary=weather.summary_he if weather else None,
            weather_temp_c=weather.temperature_c if weather else None,
            weather_rain_mm=weather.rain_mm if weather else None,
            data_source=source,
            notes=notes,
        )
