"""football-data.org API client (World Cup fixtures — env key only; never log token)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# Diagnostic codes (safe for logs/API)
KEY_MISSING = "KEY_MISSING"
UNAUTHORIZED = "UNAUTHORIZED"
RATE_LIMITED = "RATE_LIMITED"
NETWORK_ERROR = "NETWORK_ERROR"
WC_NOT_AVAILABLE = "WC_NOT_AVAILABLE"
OK = "OK"


class FootballDataClient:
    """Read-only football-data.org v4 client for WC fixture/status data."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        timeout: int | None = None,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
        self.base_url = (base_url or config.FOOTBALL_DATA_BASE_URL).rstrip("/")
        self.enabled = (
            config.FOOTBALL_DATA_ENABLED if enabled is None else enabled
        )
        self.timeout = timeout or config.FOOTBALL_DATA_REQUEST_TIMEOUT
        self.last_error_code: str | None = None

    @property
    def key_present(self) -> bool:
        return bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self.enabled and self.key_present

    def _headers(self) -> dict[str, str]:
        return {
            "X-Auth-Token": self.api_key,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_available:
            self.last_error_code = KEY_MISSING
            raise RuntimeError(KEY_MISSING)
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            self.last_error_code = NETWORK_ERROR
            raise RuntimeError(NETWORK_ERROR) from exc

        if response.status_code in (401, 403):
            self.last_error_code = UNAUTHORIZED
            raise RuntimeError(UNAUTHORIZED)
        if response.status_code == 429:
            self.last_error_code = RATE_LIMITED
            raise RuntimeError(RATE_LIMITED)

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            self.last_error_code = NETWORK_ERROR
            raise RuntimeError(NETWORK_ERROR) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            self.last_error_code = NETWORK_ERROR
            raise RuntimeError(NETWORK_ERROR) from exc

        if not isinstance(payload, dict):
            self.last_error_code = NETWORK_ERROR
            raise RuntimeError(NETWORK_ERROR)

        self.last_error_code = OK
        return payload

    def get_competitions(self) -> list[dict[str, Any]]:
        data = self._get("/competitions")
        return list(data.get("competitions") or [])

    def find_world_cup_competition(self) -> dict[str, Any] | None:
        for comp in self.get_competitions():
            if (comp.get("code") or "").upper() == config.FOOTBALL_DATA_WC_CODE:
                return comp
        self.last_error_code = WC_NOT_AVAILABLE
        return None

    def get_world_cup_matches(self, season: int | None = None) -> list[dict[str, Any]]:
        season = season or config.FOOTBALL_DATA_WC_SEASON
        data = self._get(
            f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/matches",
            params={"season": season},
        )
        return list(data.get("matches") or [])

    def get_world_cup_matches_by_date_range(
        self,
        date_from: str,
        date_to: str,
        *,
        season: int | None = None,
    ) -> list[dict[str, Any]]:
        season = season or config.FOOTBALL_DATA_WC_SEASON
        data = self._get(
            f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/matches",
            params={"season": season, "dateFrom": date_from, "dateTo": date_to},
        )
        return list(data.get("matches") or [])
