"""The Odds API multi-market payload parser (Phase 2 — not wired to live fetch)."""

from __future__ import annotations

import re
from typing import Any

from core.market_devig import devig_three_way, devig_two_way
from core.market_types import (
    BookmakerMarketLine,
    MarketFamily,
    NormalizedMarketSnapshot,
)

_PROVIDER = "the_odds_api"
_BOOK_SLUG_RE = re.compile(r"[^a-z0-9]+")

# The Odds API market key → normalized family.
MARKET_KEY_FAMILY: dict[str, MarketFamily] = {
    "h2h": MarketFamily.H2H,
    "h2h_3_way": MarketFamily.H2H,
    "spreads": MarketFamily.SPREADS,
    "alternate_spreads": MarketFamily.ALTERNATE_SPREADS,
    "totals": MarketFamily.TOTALS,
    "alternate_totals": MarketFamily.ALTERNATE_TOTALS,
    "btts": MarketFamily.BTTS,
}


def _book_id(key: str, title: str) -> str:
    slug = _BOOK_SLUG_RE.sub("_", (key or title).lower()).strip("_")
    return slug or "unknown"


def _family_for_key(market_key: str) -> MarketFamily:
    family = MARKET_KEY_FAMILY.get(market_key)
    if family is None:
        return MarketFamily.UNKNOWN
    if family in (MarketFamily.ALTERNATE_TOTALS,):
        return MarketFamily.TOTALS
    if family in (MarketFamily.ALTERNATE_SPREADS,):
        return MarketFamily.SPREADS
    return family


def _parse_h2h_market(
    market: dict[str, Any],
    book_key: str,
    book_title: str,
    home_team: str,
    away_team: str,
    *,
    swapped: bool,
) -> BookmakerMarketLine | None:
    outcomes_raw = market.get("outcomes") or []
    home_odds = draw_odds = away_odds = None
    for outcome in outcomes_raw:
        if not isinstance(outcome, dict):
            continue
        price = outcome.get("price")
        if not isinstance(price, (int, float)) or price <= 1:
            continue
        name = str(outcome.get("name") or "").lower()
        if "draw" in name:
            draw_odds = float(price)
        elif swapped:
            if away_team.lower() in name or name in away_team.lower():
                home_odds = float(price)
            elif home_team.lower() in name or name in home_team.lower():
                away_odds = float(price)
        else:
            if home_team.lower() in name or name in home_team.lower():
                home_odds = float(price)
            elif away_team.lower() in name or name in away_team.lower():
                away_odds = float(price)
    if home_odds is None or away_odds is None or draw_odds is None:
        return None
    devigged, overround = devig_three_way(home_odds, draw_odds, away_odds)
    if not devigged:
        return None
    return BookmakerMarketLine(
        bookmaker_id=_book_id(book_key, book_title),
        bookmaker_name=book_title or book_key,
        family=MarketFamily.H2H,
        provider_market_key="h2h",
        line=None,
        outcomes=tuple(devigged),
        overround=overround,
    )


def _parse_two_outcome_market(
    market: dict[str, Any],
    book_key: str,
    book_title: str,
    family: MarketFamily,
    label_a: str,
    label_b: str,
) -> BookmakerMarketLine | None:
    outcomes_raw = market.get("outcomes") or []
    if len(outcomes_raw) < 2:
        return None
    parsed: list[tuple[str, float, float | None]] = []
    for outcome in outcomes_raw:
        if not isinstance(outcome, dict):
            continue
        price = outcome.get("price")
        if not isinstance(price, (int, float)) or price <= 1:
            continue
        point = outcome.get("point")
        line = float(point) if isinstance(point, (int, float)) else None
        name = str(outcome.get("name") or "").lower()
        parsed.append((name, float(price), line))
    if len(parsed) < 2:
        return None
    # Over/Under or Yes/No: use first two valid outcomes in API order.
    (n0, p0, line0), (n1, p1, _) = parsed[0], parsed[1]
    if "over" in n0 or "yes" in n0:
        a_name, b_name = label_a, label_b
        a_odds, b_odds = p0, p1
    elif "under" in n0:
        a_name, b_name = label_b, label_a
        a_odds, b_odds = p1, p0
    else:
        a_name, b_name = label_a, label_b
        a_odds, b_odds = p0, p1
    devigged, overround = devig_two_way(a_name, a_odds, b_name, b_odds)
    if not devigged:
        return None
    return BookmakerMarketLine(
        bookmaker_id=_book_id(book_key, book_title),
        bookmaker_name=book_title or book_key,
        family=family,
        provider_market_key=str(market.get("key") or ""),
        line=line0,
        outcomes=tuple(devigged),
        overround=overround,
    )


def parse_event_payload(
    event: dict[str, Any],
    *,
    home_team: str | None = None,
    away_team: str | None = None,
    swapped: bool = False,
    fetched_at_utc: str | None = None,
) -> NormalizedMarketSnapshot:
    """Parse a single The Odds API event dict (bookmakers[].markets[])."""
    home = home_team or str(event.get("home_team") or "Home")
    away = away_team or str(event.get("away_team") or "Away")
    event_id = str(event.get("id") or "")
    lines: list[BookmakerMarketLine] = []

    for bookmaker in event.get("bookmakers") or []:
        if not isinstance(bookmaker, dict):
            continue
        book_key = str(bookmaker.get("key") or "")
        book_title = str(bookmaker.get("title") or book_key)
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict):
                continue
            mkey = str(market.get("key") or "")
            family = _family_for_key(mkey)
            if family == MarketFamily.UNKNOWN:
                continue
            parsed: BookmakerMarketLine | None = None
            if family == MarketFamily.H2H:
                parsed = _parse_h2h_market(
                    market, book_key, book_title, home, away, swapped=swapped
                )
            elif family == MarketFamily.BTTS:
                parsed = _parse_two_outcome_market(
                    market, book_key, book_title, family, "yes", "no"
                )
            elif family == MarketFamily.TOTALS:
                parsed = _parse_two_outcome_market(
                    market, book_key, book_title, family, "over", "under"
                )
            elif family == MarketFamily.SPREADS:
                parsed = _parse_two_outcome_market(
                    market, book_key, book_title, family, "home", "away"
                )
            if parsed is not None:
                lines.append(parsed)

    return NormalizedMarketSnapshot(
        provider=_PROVIDER,
        event_id=event_id,
        home_team=home,
        away_team=away,
        fetched_at_utc=fetched_at_utc,
        lines=lines,
        providers_seen=(_PROVIDER,),
    )
