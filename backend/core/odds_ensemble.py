"""Optional blend of model 1X2 with betting-market implied probabilities."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
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


def _decimal_odds_from_outcomes(
    outcomes: list[dict[str, Any]],
    home_label: str,
    away_label: str,
) -> tuple[float | None, float | None, float | None]:
    home_odds = draw_odds = away_odds = None
    for outcome in outcomes:
        price = float(outcome.get("price") or 0)
        if price <= 1:
            continue
        name = str(outcome.get("name", "")).lower()
        if "draw" in name:
            draw_odds = price
        elif _names_match(name, home_label):
            home_odds = price
        elif _names_match(name, away_label):
            away_odds = price
    return home_odds, draw_odds, away_odds


def _implied_from_outcomes(
    outcomes: list[dict[str, Any]],
    home_label: str,
    away_label: str,
) -> dict[str, float] | None:
    implied: dict[str, float] = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    home_odds, draw_odds, away_odds = _decimal_odds_from_outcomes(
        outcomes, home_label, away_label
    )
    if home_odds:
        implied["home_win"] = 100.0 / home_odds
    if draw_odds:
        implied["draw"] = 100.0 / draw_odds
    if away_odds:
        implied["away_win"] = 100.0 / away_odds
    if implied["home_win"] or implied["away_win"]:
        return _normalize(implied)
    return None


@dataclass
class BookmakerOddsLine:
    id: str
    display_name: str
    region: str
    home_decimal_odds: float | None
    draw_decimal_odds: float | None
    away_decimal_odds: float | None
    implied_1x2_percent: dict[str, float]
    source_key: str = "the_odds_api"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "region": self.region,
            "home_decimal_odds": self.home_decimal_odds,
            "draw_decimal_odds": self.draw_decimal_odds,
            "away_decimal_odds": self.away_decimal_odds,
            "implied_1x2_percent": {
                k: round(v, 2) for k, v in self.implied_1x2_percent.items()
            },
            "source_key": self.source_key,
        }


@dataclass
class OddsMarketFetch:
    sport_key: str
    bookmakers: list[BookmakerOddsLine] = field(default_factory=list)
    consensus_1x2_percent: dict[str, float] | None = None

    def legacy_consensus_percent(self) -> dict[str, float] | None:
        """Backward-compatible single consensus dict for probability pipeline."""
        if not self.consensus_1x2_percent:
            return None
        return {k: round(v, 1) for k, v in self.consensus_1x2_percent.items()}


def _consensus_from_bookmakers(
    lines: list[BookmakerOddsLine],
) -> dict[str, float] | None:
    if not lines:
        return None
    keys = ("home_win", "draw", "away_win")
    totals = {k: 0.0 for k in keys}
    for line in lines:
        for key in keys:
            totals[key] += line.implied_1x2_percent.get(key, 0.0)
    n = float(len(lines))
    avg = {k: totals[k] / n for k in keys}
    normalized = _normalize(avg)
    return {k: round(v * 100.0, 2) for k, v in normalized.items()}


def _bookmakers_from_event(
    event: dict[str, Any],
    home_team: str,
    away_team: str,
) -> list[BookmakerOddsLine]:
    lines: list[BookmakerOddsLine] = []
    for bookmaker in event.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes") or []
            implied = _implied_from_outcomes(outcomes, home_team, away_team)
            if not implied:
                continue
            home_odds, draw_odds, away_odds = _decimal_odds_from_outcomes(
                outcomes, home_team, away_team
            )
            bm_id = str(bookmaker.get("key") or bookmaker.get("title") or "unknown")
            lines.append(
                BookmakerOddsLine(
                    id=bm_id,
                    display_name=str(bookmaker.get("title") or bm_id),
                    region=str(bookmaker.get("region") or ""),
                    home_decimal_odds=home_odds,
                    draw_decimal_odds=draw_odds,
                    away_decimal_odds=away_odds,
                    implied_1x2_percent={
                        k: round(v * 100.0, 2) for k, v in implied.items()
                    },
                )
            )
            break
    return lines


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
        """Best-effort consensus 1X2 percentages for probability pipeline."""
        fetch = self.fetch_match_market(home_team, away_team)
        if fetch is None:
            return None
        return fetch.legacy_consensus_percent()

    def fetch_match_market(
        self,
        home_team: str,
        away_team: str,
    ) -> OddsMarketFetch | None:
        """All bookmaker lines + consensus for market_diagnostics."""
        if not self.is_available:
            return None

        for sport_key in MATCH_SPORT_KEYS:
            result = self._fetch_sport_market(sport_key, home_team, away_team)
            if result is not None:
                return result
        return None

    def _fetch_sport_market(
        self,
        sport_key: str,
        home_team: str,
        away_team: str,
    ) -> OddsMarketFetch | None:
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
                lines = _bookmakers_from_event(event, home_team, away_team)
                if not lines:
                    continue
                consensus = _consensus_from_bookmakers(lines)
                return OddsMarketFetch(
                    sport_key=sport_key,
                    bookmakers=lines,
                    consensus_1x2_percent=consensus,
                )
        except Exception as exc:
            logger.debug("Odds fetch %s: %s", sport_key, exc)
        return None

    def _fetch_sport_odds(
        self,
        sport_key: str,
        home_team: str,
        away_team: str,
    ) -> dict[str, float] | None:
        """Legacy: first bookmaker implied probs (fractions 0-1)."""
        fetch = self._fetch_sport_market(sport_key, home_team, away_team)
        if fetch is None or not fetch.consensus_1x2_percent:
            return None
        return {
            k: v / 100.0 for k, v in fetch.consensus_1x2_percent.items()
        }
