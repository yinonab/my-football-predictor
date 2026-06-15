"""Optional blend of model 1X2 with betting-market implied probabilities."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

THE_ODDS_API = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds"
MODEL_WEIGHT = 0.70
MARKET_WEIGHT = 0.30


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
        """Best-effort lookup; returns None if no market found."""
        if not self.is_available:
            return None
        try:
            response = requests.get(
                THE_ODDS_API,
                params={
                    "apiKey": self.api_key,
                    "regions": "eu",
                    "markets": "h2h",
                },
                timeout=12,
            )
            response.raise_for_status()
            events = response.json()
            home_l = home_team.lower().split(" (")[0]
            away_l = away_team.lower().split(" (")[0]
            for event in events:
                eh = event.get("home_team", "").lower()
                ea = event.get("away_team", "").lower()
                if home_l not in eh and eh not in home_l:
                    continue
                if away_l not in ea and ea not in away_l:
                    continue
                bookmakers = event.get("bookmakers") or []
                if not bookmakers:
                    continue
                market = bookmakers[0].get("markets") or []
                if not market:
                    continue
                outcomes = market[0].get("outcomes") or []
                implied: dict[str, float] = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
                for o in outcomes:
                    price = float(o.get("price") or 0)
                    if price <= 1:
                        continue
                    prob = 100.0 / price
                    name = o.get("name", "").lower()
                    if name in (eh, home_l) or home_l in name:
                        implied["home_win"] = prob
                    elif name in (ea, away_l) or away_l in name:
                        implied["away_win"] = prob
                    elif "draw" in name:
                        implied["draw"] = prob
                if implied["home_win"] or implied["away_win"]:
                    return implied
        except Exception as exc:
            logger.warning("Odds fetch failed: %s", exc)
        return None
