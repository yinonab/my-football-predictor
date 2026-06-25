"""OddsPapi client via RapidAPI (odds-api1) — WC fixtures + weighted 1X2 consensus."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

import config
from core.odds_consensus import weighted_consensus_from_lines
from core.odds_ensemble import (
    BookmakerOddsLine,
    OddsLookupResult,
    OddsMarketFetch,
    _names_match,
)

logger = logging.getLogger(__name__)

TOURNAMENT_CACHE_TTL_SEC = 15 * 60
OUTCOME_CACHE_TTL_SEC = 24 * 60 * 60

_OUTCOME_SIDE_BY_NAME = {
    "1": "home_win",
    "x": "draw",
    "2": "away_win",
    "home": "home_win",
    "draw": "draw",
    "away": "away_win",
}

_tournament_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_outcome_label_cache: dict[int, tuple[float, str]] = {}


class OddsPapiClient:
    """Fetch World Cup 1X2 odds from OddsPapi RapidAPI proxy."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        host: str | None = None,
        base_url: str | None = None,
        tournament_id: int | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = (api_key or config.oddspapi_rapidapi_key()).strip()
        self.host = (host or config.ODDSPAPI_RAPIDAPI_HOST).strip()
        self.base_url = (base_url or config.ODDSPAPI_RAPIDAPI_BASE).rstrip("/")
        self.tournament_id = (
            tournament_id
            if tournament_id is not None
            else config.ODDSPAPI_WC_TOURNAMENT_ID
        )
        self.timeout = timeout or config.ODDSPAPI_TIMEOUT_SECONDS

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def lookup_match_market(
        self,
        home_team: str,
        away_team: str,
    ) -> OddsLookupResult:
        if not self.is_available:
            return OddsLookupResult(
                status="not_configured",
                notes=["ODDSPAPI_RAPIDAPI_KEY not configured on server"],
                odds_key_configured=False,
            )

        fixtures, error = self._load_tournament_odds()
        if error == "quota_exceeded":
            return OddsLookupResult(
                status="quota_exceeded",
                notes=["OddsPapi rate limit exceeded — retry shortly"],
                odds_key_configured=True,
            )
        if error:
            return OddsLookupResult(
                status="api_error",
                notes=[f"OddsPapi request failed: {error}"],
                odds_key_configured=True,
            )

        fixture = self._find_fixture(fixtures, home_team, away_team)
        if fixture is None:
            return OddsLookupResult(
                status="no_odds_for_matchup",
                notes=[
                    f"No OddsPapi fixture found for {home_team} vs {away_team} "
                    f"(tournamentId={self.tournament_id})"
                ],
                odds_key_configured=True,
            )

        swapped = self._is_swapped(fixture, home_team, away_team)
        lines = self._bookmaker_lines_from_fixture(fixture, swapped=swapped)
        if not lines:
            return OddsLookupResult(
                status="no_odds_for_matchup",
                notes=["Fixture found but no parseable 1X2 bookmaker lines"],
                odds_key_configured=True,
            )

        consensus = weighted_consensus_from_lines(lines)
        fetch = OddsMarketFetch(
            sport_key=f"oddspapi:wc:{self.tournament_id}",
            bookmakers=lines,
            consensus_1x2_percent=consensus,
        )
        notes = [
            f"OddsPapi weighted consensus from {len(lines)} bookmakers "
            f"(tournamentId={self.tournament_id})"
        ]
        return OddsLookupResult(
            fetch=fetch,
            status="ok",
            notes=notes,
            odds_key_configured=True,
        )

    def fetch_match_market(
        self,
        home_team: str,
        away_team: str,
    ) -> OddsMarketFetch | None:
        return self.lookup_match_market(home_team, away_team).fetch

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = requests.get(
            url,
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        if response.status_code == 429:
            raise OddsPapiRateLimitError("rate_limited")
        response.raise_for_status()
        return response.json()

    def _load_tournament_odds(
        self,
    ) -> tuple[list[dict[str, Any]], str | None]:
        now = time.time()
        cached = _tournament_cache.get(self.tournament_id)
        if cached and cached[0] > now:
            return cached[1], None

        try:
            payload = self._get(
                "fixtures/odds/main",
                params={"tournamentId": self.tournament_id},
            )
            if not isinstance(payload, list):
                return [], "invalid_response"
            _tournament_cache[self.tournament_id] = (
                now + TOURNAMENT_CACHE_TTL_SEC,
                payload,
            )
            return payload, None
        except OddsPapiRateLimitError:
            return [], "quota_exceeded"
        except requests.RequestException as exc:
            logger.warning("OddsPapi tournament fetch failed: %s", exc)
            return [], str(exc)

    def _find_fixture(
        self,
        fixtures: list[dict[str, Any]],
        home_team: str,
        away_team: str,
    ) -> dict[str, Any] | None:
        for fixture in fixtures:
            participants = fixture.get("participants") or {}
            p1 = str(participants.get("participant1Name") or "")
            p2 = str(participants.get("participant2Name") or "")
            if _names_match(p1, home_team) and _names_match(p2, away_team):
                return fixture
            if _names_match(p1, away_team) and _names_match(p2, home_team):
                return fixture
        return None

    def _is_swapped(
        self,
        fixture: dict[str, Any],
        home_team: str,
        away_team: str,
    ) -> bool:
        participants = fixture.get("participants") or {}
        p1 = str(participants.get("participant1Name") or "")
        return _names_match(p1, away_team) and _names_match(
            str(participants.get("participant2Name") or ""),
            home_team,
        )

    def _bookmaker_lines_from_fixture(
        self,
        fixture: dict[str, Any],
        *,
        swapped: bool,
    ) -> list[BookmakerOddsLine]:
        odds_root = fixture.get("odds") or {}
        if not isinstance(odds_root, dict):
            return []

        outcome_ids: set[int] = set()
        for book_quotes in odds_root.values():
            if not isinstance(book_quotes, dict):
                continue
            for quote in book_quotes.values():
                if isinstance(quote, dict) and quote.get("outcomeId") is not None:
                    outcome_ids.add(int(quote["outcomeId"]))

        outcome_sides = self._resolve_outcome_sides(outcome_ids)
        lines: list[BookmakerOddsLine] = []

        for bookmaker_id, book_quotes in odds_root.items():
            if not isinstance(book_quotes, dict):
                continue
            quotes = [
                q
                for q in book_quotes.values()
                if isinstance(q, dict) and q.get("active", True)
            ]
            by_market: dict[int, list[dict[str, Any]]] = {}
            for quote in quotes:
                market_id = int(quote.get("marketId") or 0)
                by_market.setdefault(market_id, []).append(quote)

            best_market: list[dict[str, Any]] | None = None
            for market_quotes in by_market.values():
                if len(market_quotes) < 3:
                    continue
                main = [q for q in market_quotes if q.get("mainLine")]
                candidate = main if len(main) >= 3 else market_quotes
                if best_market is None or len(candidate) > len(best_market):
                    best_market = candidate[:3]

            if not best_market:
                continue

            implied = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
            home_odds = draw_odds = away_odds = None
            for quote in best_market:
                price = float(quote.get("price") or 0)
                if price <= 1.0:
                    continue
                outcome_id = int(quote.get("outcomeId") or 0)
                side = outcome_sides.get(outcome_id)
                if side is None:
                    continue
                if swapped:
                    if side == "home_win":
                        side = "away_win"
                    elif side == "away_win":
                        side = "home_win"
                implied[side] = 100.0 / price
                if side == "home_win":
                    home_odds = price
                elif side == "draw":
                    draw_odds = price
                elif side == "away_win":
                    away_odds = price

            if not implied["home_win"] and not implied["away_win"]:
                continue

            total = sum(implied.values())
            if total <= 0:
                continue
            implied = {k: round(v / total * 100.0, 2) for k, v in implied.items()}

            lines.append(
                BookmakerOddsLine(
                    id=str(bookmaker_id),
                    display_name=str(bookmaker_id),
                    region="",
                    home_decimal_odds=home_odds,
                    draw_decimal_odds=draw_odds,
                    away_decimal_odds=away_odds,
                    implied_1x2_percent=implied,
                    source_key="oddspapi",
                )
            )

        return lines

    def _resolve_outcome_sides(self, outcome_ids: set[int]) -> dict[int, str]:
        if not outcome_ids:
            return {}

        now = time.time()
        resolved: dict[int, str] = {}
        missing: list[int] = []
        for oid in outcome_ids:
            cached = _outcome_label_cache.get(oid)
            if cached and cached[0] > now:
                resolved[oid] = cached[1]
            else:
                missing.append(oid)

        if missing:
            try:
                payload = self._get(
                    "markets",
                    params={"outcomeIds": ",".join(str(i) for i in sorted(missing))},
                )
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    outcomes = item.get("outcomes") or []
                    for outcome in outcomes:
                        oid = int(outcome.get("outcomeId") or 0)
                        name = str(outcome.get("outcomeName") or "").strip().lower()
                        side = _OUTCOME_SIDE_BY_NAME.get(name)
                        if oid and side:
                            resolved[oid] = side
                            _outcome_label_cache[oid] = (
                                now + OUTCOME_CACHE_TTL_SEC,
                                side,
                            )
            except requests.RequestException as exc:
                logger.debug("OddsPapi outcome label fetch failed: %s", exc)

        # Standard soccer 1X2 ids (market 101) fallback.
        for oid in missing:
            if oid in resolved:
                continue
            tail = oid % 10
            if tail == 1:
                resolved[oid] = "home_win"
            elif tail == 2:
                resolved[oid] = "draw"
            elif tail == 3:
                resolved[oid] = "away_win"

        return resolved


class OddsPapiRateLimitError(Exception):
    pass
