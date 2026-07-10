"""Official RapidAPI Odds Feed HTTP client (diagnostics only — not wired to predict)."""

from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = "https://odds-feed.p.rapidapi.com"
HOST = "odds-feed.p.rapidapi.com"
API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT_SEC = 25.0


class RapidApiOddsFeedClientError(Exception):
    """Safe client error; never includes API keys."""


def rapidapi_key() -> str:
    return (os.getenv("RAPIDAPI_KEY") or "").strip()


def _headers() -> dict[str, str]:
    key = rapidapi_key()
    if not key:
        raise RapidApiOddsFeedClientError("rapidapi_key_not_configured")
    return {
        "x-rapidapi-key": key,
        "x-rapidapi-host": HOST,
        "Content-Type": "application/json",
    }


def _paginated_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def _sanitize_error_message(message: str) -> str:
    key = rapidapi_key()
    if key and key in message:
        return message.replace(key, "[redacted]")
    return message


def fetch_event_markets(event_id: str, *, timeout: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """Fetch raw provider markets for one event. Returns provider JSON wrapper only."""
    event_id = str(event_id or "").strip()
    if not event_id.isdigit():
        raise RapidApiOddsFeedClientError("invalid_provider_event_id")

    markets: list[dict[str, Any]] = []
    last_status = 0
    last_error = ""
    for placing in ("PREMATCH", "LIVE"):
        url = f"{BASE_URL}{API_PREFIX}/events/markets"
        try:
            resp = requests.get(
                url,
                headers=_headers(),
                params={"event_id": int(event_id), "placing": placing},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RapidApiOddsFeedClientError(
                f"rapidapi_request_failed:{_sanitize_error_message(str(exc))}"
            ) from exc

        last_status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"_raw": (resp.text or "")[:400]}

        if resp.status_code >= 400:
            last_error = f"http_{resp.status_code}"
            continue

        batch = _paginated_items(body)
        markets.extend(batch)
        if markets:
            return {
                "provider": "rapidapi_odds_feed",
                "event_id": event_id,
                "placing": placing,
                "http_status": resp.status_code,
                "markets": markets,
            }

    if last_status == 401 or last_status == 403:
        raise RapidApiOddsFeedClientError("rapidapi_auth_failed")
    if last_status == 429:
        raise RapidApiOddsFeedClientError("rapidapi_rate_limited")
    if last_error:
        raise RapidApiOddsFeedClientError(last_error)
    return {
        "provider": "rapidapi_odds_feed",
        "event_id": event_id,
        "placing": None,
        "http_status": last_status,
        "markets": [],
    }
