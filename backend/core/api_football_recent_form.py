"""Phase 4R.3 — API-Football national-team recent-form provider (historical seasons)."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import config
from core.football_data_teams import normalize_team_key
from data.nt_match import registry_key_for_nt
from data.nt_team_aliases import registry_english_for_alias

logger = logging.getLogger(__name__)

PROVIDER_ID = "api_football_recent_form"
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})

INTERNATIONAL_LEAGUE_KEYWORDS = (
    "world cup",
    "friendlies",
    "copa america",
    "euro",
    "european championship",
    "africa cup",
    "afcon",
    "asian cup",
    "gold cup",
    "nations league",
    "qualification",
    "confederations",
)

APIF_ERROR_BLOCKED_SEASON = "APIF_BLOCKED_SEASON"
APIF_ERROR_BLOCKED_LAST = "APIF_BLOCKED_LAST"
APIF_ERROR_RATE_LIMIT = "APIF_RATE_LIMIT"
APIF_ERROR_NO_RESULTS = "APIF_NO_RESULTS"
APIF_ERROR_KEY_MISSING = "APIF_KEY_MISSING"


@dataclass(frozen=True)
class ApiFootballRequestError:
    category: str
    message: str
    http_status: int | None = None


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_search_name(name: str) -> str:
    base = name.split(" (")[0].strip()
    return _strip_accents(base).lower()


def is_international_league(league_name: str) -> bool:
    blob = normalize_search_name(league_name)
    return any(kw in blob for kw in INTERNATIONAL_LEAGUE_KEYWORDS)


def parse_apif_errors(payload: dict[str, Any]) -> ApiFootballRequestError | None:
    errors = payload.get("errors")
    if not errors:
        return None
    if isinstance(errors, dict):
        text = " ".join(f"{k}:{v}" for k, v in errors.items())
    else:
        text = str(errors)
    lower = text.lower()
    if "last" in lower and ("plan" in lower or "free" in lower or "blocked" in lower):
        return ApiFootballRequestError(APIF_ERROR_BLOCKED_LAST, text[:200])
    if "season" in lower or "2025" in lower or "2026" in lower:
        return ApiFootballRequestError(APIF_ERROR_BLOCKED_SEASON, text[:200])
    if "rate" in lower or "limit" in lower:
        return ApiFootballRequestError(APIF_ERROR_RATE_LIMIT, text[:200])
    return ApiFootballRequestError("APIF_ERROR", text[:200])


class ApiFootballRecentFormClient:
    """Safe read-only API-Football client for NT fixture history (no `last` param)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: int | None = None,
        sleep_seconds: float | None = None,
    ) -> None:
        import os

        self.api_key = (api_key or os.getenv("API_FOOTBALL_API_KEY") or os.getenv("API_FOOTBALL_KEY") or "").strip()
        self.base_url = (base_url or config.API_FOOTBALL_BASE_URL).rstrip("/")
        self.timeout = timeout or config.API_FOOTBALL_TIMEOUT_SECONDS
        self.sleep_seconds = sleep_seconds if sleep_seconds is not None else config.API_FOOTBALL_SLEEP_SECONDS
        self.last_error: ApiFootballRequestError | None = None

    @property
    def is_available(self) -> bool:
        return config.api_football_recent_form_enabled()

    def _headers(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key, "Accept": "application/json"}

    def request_raw(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, ApiFootballRequestError | None]:
        if not self.api_key:
            err = ApiFootballRequestError(APIF_ERROR_KEY_MISSING, "API key missing")
            self.last_error = err
            return None, err
        import requests

        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self.timeout,
            )
        except requests.Timeout:
            err = ApiFootballRequestError("APIF_TIMEOUT", "request timed out")
            self.last_error = err
            return None, err
        except requests.RequestException as exc:
            err = ApiFootballRequestError("APIF_NETWORK", str(exc)[:200])
            self.last_error = err
            return None, err

        try:
            payload = response.json()
        except ValueError:
            err = ApiFootballRequestError("APIF_JSON", "invalid json")
            self.last_error = err
            return None, err

        if not isinstance(payload, dict):
            err = ApiFootballRequestError("APIF_JSON", "unexpected payload")
            self.last_error = err
            return None, err

        api_err = parse_apif_errors(payload)
        if api_err is not None:
            self.last_error = api_err
            return None, api_err

        if response.status_code == 429:
            err = ApiFootballRequestError(APIF_ERROR_RATE_LIMIT, "HTTP 429")
            self.last_error = err
            return None, err

        if response.status_code >= 400:
            err = ApiFootballRequestError(f"APIF_HTTP_{response.status_code}", response.text[:200])
            self.last_error = err
            return None, err

        self.last_error = None
        return payload, None

    def search_national_team(
        self,
        name: str,
        *,
        registry: set[str] | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], ApiFootballRequestError | None]:
        """Return (best match, all candidates, error)."""
        search = registry_english_for_alias(name.split(" (")[0].strip())
        payload, err = self.request_raw("/teams", {"search": search})
        if err is not None:
            return None, [], err
        items = list((payload or {}).get("response") or [])
        candidates: list[dict[str, Any]] = []
        for item in items:
            team = item.get("team") or {}
            candidates.append(team)

        req_norm = normalize_team_key(search)
        national = [t for t in candidates if t.get("national")]
        for team in national:
            team_norm = normalize_team_key(str(team.get("name") or ""))
            if team_norm == req_norm or normalize_team_key(str(team.get("country") or "")) == req_norm:
                return team, candidates, None

        if registry:
            canonical = registry_key_for_nt(search, registry)
            if canonical:
                english = canonical.split(" (")[0]
                eng_norm = normalize_team_key(english)
                for team in national:
                    if normalize_team_key(str(team.get("name") or "")) == eng_norm:
                        return team, candidates, None

        if len(national) == 1:
            return national[0], candidates, None
        if national:
            return national[0], candidates, None
        return (candidates[0] if candidates else None), candidates, None

    def fetch_team_leagues(self, team_id: int) -> tuple[list[dict[str, Any]], ApiFootballRequestError | None]:
        payload, err = self.request_raw("/leagues", {"team": team_id})
        if err is not None:
            return [], err
        leagues: list[dict[str, Any]] = []
        for item in (payload or {}).get("response") or []:
            league = item.get("league") or {}
            if is_international_league(str(league.get("name") or "")):
                leagues.append(item)
        return leagues, None

    def fetch_fixtures_team_season(
        self,
        team_id: int,
        season: int,
    ) -> tuple[list[dict[str, Any]], ApiFootballRequestError | None]:
        payload, err = self.request_raw("/fixtures", {"team": team_id, "season": season})
        if err is not None:
            if err.category == APIF_ERROR_BLOCKED_SEASON:
                return [], err
            return [], err
        fixtures = list((payload or {}).get("response") or [])
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        return fixtures, None

    def fetch_fixtures_team_league_season(
        self,
        team_id: int,
        league_id: int,
        season: int,
    ) -> tuple[list[dict[str, Any]], ApiFootballRequestError | None]:
        payload, err = self.request_raw(
            "/fixtures",
            {"team": team_id, "league": league_id, "season": season},
        )
        if err is not None:
            return [], err
        fixtures = list((payload or {}).get("response") or [])
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        return fixtures, None

    def collect_team_fixtures(
        self,
        team_id: int,
        *,
        seasons: list[int] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch fixtures for configured seasons; non-fatal per-season errors."""
        seasons = seasons or config.api_football_seasons_list()
        meta: dict[str, Any] = {
            "seasons_requested": seasons,
            "season_errors": {},
            "league_fetch_count": 0,
            "fixture_count_raw": 0,
        }
        all_fixtures: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        leagues, league_err = self.fetch_team_leagues(team_id)
        if league_err:
            meta["league_error"] = league_err.category

        for season in seasons:
            season_fixtures: list[dict[str, Any]] = []
            if leagues:
                for league_item in leagues:
                    league = league_item.get("league") or {}
                    league_id = league.get("id")
                    if league_id is None:
                        continue
                    meta["league_fetch_count"] += 1
                    batch, err = self.fetch_fixtures_team_league_season(team_id, int(league_id), season)
                    if err:
                        meta["season_errors"][f"{league_id}:{season}"] = err.category
                        continue
                    season_fixtures.extend(batch)
            if not season_fixtures:
                batch, err = self.fetch_fixtures_team_season(team_id, season)
                if err:
                    meta["season_errors"][str(season)] = err.category
                    continue
                season_fixtures = batch

            for fx in season_fixtures:
                fix = fx.get("fixture") or {}
                fid = fix.get("id")
                if fid is not None and int(fid) in seen_ids:
                    continue
                if fid is not None:
                    seen_ids.add(int(fid))
                all_fixtures.append(fx)

        meta["fixture_count_raw"] = len(all_fixtures)
        return all_fixtures, meta


def parse_apif_fixture_for_team(
    fixture: dict[str, Any],
    *,
    team_registry_key: str,
    api_team_id: int,
) -> dict[str, Any] | None:
    """Parse one API-Football fixture into fusion match dict for focal team."""
    fix = fixture.get("fixture") or {}
    status = (fix.get("status") or {}).get("short") or ""
    if status not in FINISHED_STATUSES:
        return None

    home = fixture.get("teams") or {}
    home_team = home.get("home") or {}
    away_team = home.get("away") or {}
    goals = fixture.get("goals") or {}
    hg, ag = goals.get("home"), goals.get("away")
    if hg is None or ag is None:
        return None

    league = fixture.get("league") or {}
    venue = fix.get("venue") or {}
    date_str = str(fix.get("date") or "")[:10]
    if not date_str:
        return None

    english = team_registry_key.split(" (")[0]
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    is_home: bool | None = None
    if home_id == api_team_id:
        score_for, score_against = int(hg), int(ag)
        opponent = str(away_team.get("name") or "unknown")
        is_home = True
    elif away_id == api_team_id:
        score_for, score_against = int(ag), int(hg)
        opponent = str(home_team.get("name") or "unknown")
        is_home = False
    else:
        return None

    if score_for > score_against:
        result = "W"
    elif score_for < score_against:
        result = "L"
    else:
        result = "D"

    neutral = venue.get("city") in (None, "") if venue else None

    return {
        "provider": PROVIDER_ID,
        "source_priority": 100,
        "provider_fixture_id": str(fix.get("id")),
        "team": english,
        "opponent": opponent,
        "date": date_str,
        "status": status,
        "home_team": str(home_team.get("name") or ""),
        "away_team": str(away_team.get("name") or ""),
        "home_score": int(hg),
        "away_score": int(ag),
        "score_for": score_for,
        "score_against": score_against,
        "result_for_team": result,
        "competition_name": str(league.get("name") or "unknown"),
        "competition_id": league.get("id"),
        "competition_code": league.get("type"),
        "season": league.get("season"),
        "is_neutral": neutral,
        "confidence_level": "high",
        "quality_flags": [],
        "raw_source_ref": {"provider": "api-football", "fixture_id": fix.get("id")},
        "team_registry_key": team_registry_key,
    }
