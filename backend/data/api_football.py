"""Optional live stats from API-Football (api-football.com)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from data.nt_match import NationalTeamMatch, competition_weight

logger = logging.getLogger(__name__)

API_BASE = "https://v3.football.api-sports.io"
REQUEST_TIMEOUT = 15

# API-Football league IDs for WC 2026 qualification (v3)
QUALIFIER_LEAGUE_IDS: tuple[tuple[int, str], ...] = (
    (32, "World Cup - Qualification Europe"),
    (34, "World Cup - Qualification South America"),
    (29, "World Cup - Qualification Africa"),
    (30, "World Cup - Qualification Asia"),
    (31, "World Cup - Qualification CONCACAF"),
)


class ApiFootballClient:
    """Fetch recent team form when API_FOOTBALL_KEY is configured."""

    def __init__(self, api_key: str | None = None, *, max_requests: int | None = None) -> None:
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = os.getenv("API_FOOTBALL_KEY", "").strip()
        self._max_requests = max_requests
        self.request_count = 0

    @property
    def requests_remaining(self) -> int | None:
        if self._max_requests is None:
            return None
        return max(0, self._max_requests - self.request_count)

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-apisports-key": self.api_key,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_available:
            raise RuntimeError("API_FOOTBALL_KEY is not set")
        if self._max_requests is not None and self.request_count >= self._max_requests:
            raise RuntimeError(
                f"API request budget exhausted ({self._max_requests} calls)"
            )
        self.request_count += 1
        url = f"{API_BASE}{path}"
        response = requests.get(
            url,
            headers=self._headers(),
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(str(payload["errors"]))
        return payload

    def search_team(self, name: str) -> dict[str, Any] | None:
        """Resolve team name to API-Football team record."""
        return self.search_national_team(name)

    def search_national_team(self, name: str) -> dict[str, Any] | None:
        """Prefer national-team records over clubs with similar names."""
        data = self._get("/teams", params={"search": name})
        items = data.get("response") or []
        for item in items:
            team = item["team"]
            if team.get("national"):
                return team
        return items[0]["team"] if items else None

    def fetch_last_finished_fixture(self, team_id: int) -> dict[str, Any] | None:
        """Most recent finished match for a national team."""
        data = self._get(
            "/fixtures",
            params={"team": team_id, "last": 5},
        )
        items = data.get("response") or []
        for fx in items:
            status = (fx.get("fixture") or {}).get("status", {}).get("short", "")
            if status in ("FT", "AET", "PEN"):
                return fx
        return items[0] if items else None

    def extract_fixture_context(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Date, city, round, league from a fixture payload."""
        fix = fixture.get("fixture") or {}
        league = fixture.get("league") or {}
        venue = fix.get("venue") or {}
        return {
            "date": (fix.get("date") or "")[:10] or None,
            "city": venue.get("city"),
            "round": league.get("round"),
            "league": league.get("name"),
        }

    def find_scheduled_h2h_fixture(
        self,
        team_a_id: int,
        team_b_id: int,
    ) -> dict[str, Any] | None:
        """Next scheduled fixture between two teams (if any)."""
        data = self._get(
            "/fixtures/headtohead",
            params={"h2h": f"{team_a_id}-{team_b_id}", "status": "NS"},
        )
        items = data.get("response") or []
        if not items:
            return None
        items_sorted = sorted(
            items,
            key=lambda fx: (fx.get("fixture") or {}).get("date") or "",
        )
        return self.extract_fixture_context(items_sorted[0])

    def fetch_team_fixtures(
        self,
        team_id: int,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """All finished fixtures for a team in a date range (paginated)."""
        fixtures: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                "/fixtures",
                params={
                    "team": team_id,
                    "from": date_from,
                    "to": date_to,
                    "status": "FT",
                    "page": page,
                },
            )
            fixtures.extend(data.get("response") or [])
            paging = data.get("paging") or {}
            total_pages = int(paging.get("total") or 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.2)
        return fixtures

    def parse_fixture(self, fixture: dict[str, Any]) -> NationalTeamMatch | None:
        """Convert API fixture payload to NationalTeamMatch (national teams only)."""
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        if not (home.get("national") or away.get("national")):
            return None

        goals = fixture["goals"]
        if goals["home"] is None or goals["away"] is None:
            return None

        league_name = fixture["league"]["name"]
        fixture_date = fixture["fixture"]["date"][:10]
        venue = fixture.get("fixture", {}).get("venue", {}) or {}
        neutral = not bool(venue.get("city"))

        return NationalTeamMatch(
            date=fixture_date,
            home=home["name"],
            away=away["name"],
            home_goals=int(goals["home"]),
            away_goals=int(goals["away"]),
            neutral=neutral,
            competition=league_name,
            weight=competition_weight(league_name),
        )

    def fetch_head_to_head(
        self,
        team_a_id: int,
        team_b_id: int,
    ) -> list[dict[str, Any]]:
        """Historical fixtures between two national teams."""
        fixtures: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                "/fixtures/headtohead",
                params={"h2h": f"{team_a_id}-{team_b_id}", "status": "FT", "page": page},
            )
            fixtures.extend(data.get("response") or [])
            paging = data.get("paging") or {}
            total_pages = int(paging.get("total") or 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.2)
        return fixtures

    def fetch_league_fixtures(
        self,
        league_id: int,
        season: int,
    ) -> list[dict[str, Any]]:
        """All finished fixtures for a qualifier league season."""
        fixtures: list[dict[str, Any]] = []
        page = 1
        while True:
            params: dict[str, Any] = {
                "league": league_id,
                "season": season,
                "status": "FT",
            }
            if page > 1:
                params["page"] = page
            try:
                data = self._get("/fixtures", params=params)
            except RuntimeError as exc:
                if page == 1 and "page" in str(exc).lower():
                    data = self._get(
                        "/fixtures",
                        params={
                            "league": league_id,
                            "season": season,
                            "status": "FT",
                        },
                    )
                else:
                    raise
            batch = data.get("response") or []
            fixtures.extend(batch)
            paging = data.get("paging") or {}
            total_pages = int(paging.get("total") or 1)
            current_page = int(paging.get("current") or page)
            if current_page >= total_pages or not batch:
                break
            page += 1
            time.sleep(6.5)
        return fixtures

    def fetch_all_qualifiers(
        self,
        seasons: tuple[int, ...] = (2023, 2024, 2025, 2026),
        *,
        league_ids: tuple[tuple[int, str], ...] | None = None,
    ) -> list[NationalTeamMatch]:
        """Fetch WC qualifier fixtures across confederations when API key is set."""
        collected: list[NationalTeamMatch] = []
        leagues = league_ids or QUALIFIER_LEAGUE_IDS
        for league_id, label in leagues:
            for season in seasons:
                try:
                    fixtures = self.fetch_league_fixtures(league_id, season)
                    for fx in fixtures:
                        parsed = self.parse_fixture(fx)
                        if parsed:
                            collected.append(parsed)
                    logger.info("%s season %s: %d fixtures", label, season, len(fixtures))
                except Exception as exc:
                    logger.warning("Qualifier fetch %s %s: %s", label, season, exc)
                time.sleep(6.5)
        return collected

    def fetch_recent_form(
        self,
        team_id: int,
        last_n: int = 10,
    ) -> dict[str, float] | None:
        """
        Derive attack/defense/form from last N finished matches.
        Returns values in 0–1 scale compatible with LiveDataManager.
        """
        data = self._get(
            "/fixtures",
            params={"team": team_id, "last": last_n, "status": "FT"},
        )
        fixtures = data.get("response") or []
        if not fixtures:
            return None

        goals_for = 0
        goals_against = 0
        points = 0

        for fx in fixtures:
            home = fx["teams"]["home"]
            away = fx["teams"]["away"]
            score = fx["goals"]
            hg = score["home"] or 0
            ag = score["away"] or 0

            if home["id"] == team_id:
                gf, ga = hg, ag
            else:
                gf, ga = ag, hg

            goals_for += gf
            goals_against += ga
            if gf > ga:
                points += 3
            elif gf == ga:
                points += 1

        n = len(fixtures)
        avg_gf = goals_for / n
        avg_ga = goals_against / n
        form = points / (n * 3)

        attack = min(0.95, 0.15 + avg_gf * 0.22)
        defense = min(0.95, 0.15 + (2.2 - min(avg_ga, 2.2)) * 0.35)
        form = round(min(0.95, max(0.05, form)), 2)

        return {
            "form": form,
            "attack": round(attack, 2),
            "defense": round(defense, 2),
        }

    def enrich_team_data(
        self,
        team_name: str,
        base: dict[str, float],
    ) -> dict[str, float]:
        """Merge API form into existing team vector; fallback to base on error."""
        if not self.is_available:
            return base
        try:
            team = self.search_team(team_name.split(" (")[0])
            if not team:
                return base
            live = self.fetch_recent_form(team["id"])
            if not live:
                return base
            merged = dict(base)
            merged.update(live)
            logger.info("Enriched %s from API-Football", team_name)
            return merged
        except Exception as exc:
            logger.warning("API-Football enrichment failed for %s: %s", team_name, exc)
            return base
