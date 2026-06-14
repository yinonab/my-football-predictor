"""Optional live stats from API-Football (api-football.com)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://v3.football.api-sports.io"
REQUEST_TIMEOUT = 15


class ApiFootballClient:
    """Fetch recent team form when API_FOOTBALL_KEY is configured."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "").strip()

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
        data = self._get("/teams", params={"search": name})
        items = data.get("response") or []
        return items[0]["team"] if items else None

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
