"""Optional blend of model 1X2 with betting-market implied probabilities."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

THE_ODDS_API = "https://api.the-odds-api.com/v4"
MODEL_WEIGHT = 0.70
MARKET_WEIGHT = 0.30

# Try WC / international soccer keys (The Odds API sport slugs).
MATCH_SPORT_KEYS: tuple[str, ...] = (
    "soccer_fifa_world_cup",
    "soccer_fifa_world_cup_winner",
    "soccer_international_friendlies",
)


def _normalize(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        return probs
    return {k: v / total for k, v in probs.items()}


def blend_1x2(
    model: dict[str, float],
    market: dict[str, float] | None,
    *,
    model_weight: float = MODEL_WEIGHT,
) -> dict[str, float]:
    """Blend percentage dicts (home_win, draw, away_win)."""
    if not market:
        return model
    mw = model_weight
    keys = ("home_win", "draw", "away_win")
    m = _normalize({k: model.get(k, 0) / 100.0 for k in keys})
    mk = _normalize({k: market.get(k, 0) / 100.0 for k in keys})
    out = {k: (mw * m[k] + (1 - mw) * mk[k]) * 100.0 for k in keys}
    return {k: round(v, 1) for k, v in out.items()}


def _team_tokens(name: str) -> set[str]:
    base = name.lower().split(" (")[0].strip()
    return {base, base.replace("'", ""), name.lower()}


def _names_match(a: str, b: str) -> bool:
    ta, tb = _team_tokens(a), _team_tokens(b)
    return any(x in y or y in x for x in ta for y in tb if x and y)


def _implied_from_outcomes(
    outcomes: list[dict[str, Any]],
    home_label: str,
    away_label: str,
) -> dict[str, float] | None:
    implied: dict[str, float] = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    for outcome in outcomes:
        price = float(outcome.get("price") or 0)
        if price <= 1:
            continue
        prob = 100.0 / price
        name = str(outcome.get("name", "")).lower()
        if "draw" in name:
            implied["draw"] = prob
        elif _names_match(name, home_label):
            implied["home_win"] = prob
        elif _names_match(name, away_label):
            implied["away_win"] = prob
    if implied["home_win"] or implied["away_win"]:
        return _normalize(implied)
    return None


class OddsClient:
    """Fetch match odds when THE_ODDS_API_KEY is set (optional)."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("THE_ODDS_API_KEY", "")).strip()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def fetch_match_odds(
        self,
        home_team: str,
        away_team: str,
    ) -> dict[str, float] | None:
        """Best-effort lookup across international soccer markets."""
        if not self.is_available:
            return None

        for sport_key in MATCH_SPORT_KEYS:
            market = self._fetch_sport_odds(sport_key, home_team, away_team)
            if market:
                return {k: round(v * 100.0, 1) for k, v in market.items()}
        return None

    def _fetch_sport_odds(
        self,
        sport_key: str,
        home_team: str,
        away_team: str,
    ) -> dict[str, float] | None:
        try:
            response = requests.get(
                f"{THE_ODDS_API}/sports/{sport_key}/odds",
                params={
                    "apiKey": self.api_key,
                    "regions": "eu,uk",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
                timeout=12,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            events = response.json()
            for event in events:
                eh = event.get("home_team", "")
                ea = event.get("away_team", "")
                if not (_names_match(eh, home_team) and _names_match(ea, away_team)):
                    continue
                for bookmaker in event.get("bookmakers") or []:
                    for market in bookmaker.get("markets") or []:
                        if market.get("key") != "h2h":
                            continue
                        implied = _implied_from_outcomes(
                            market.get("outcomes") or [],
                            home_team,
                            away_team,
                        )
                        if implied:
                            return implied
        except Exception as exc:
            logger.debug("Odds fetch %s: %s", sport_key, exc)
        return None
