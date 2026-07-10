"""Live provider snapshot fetch for diagnostics only (Phase 5A — not wired to predict)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.providers.rapidapi_odds_feed_client import (
    RapidApiOddsFeedClientError,
    fetch_event_markets,
)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"rapidapi_odds_feed"})

_EXACT_FAMILY: dict[str, str] = {
    "1X2": "h2h",
    "HOME_AWAY": "h2h",
    "OVER_UNDER": "totals",
    "ASIAN_HANDICAP": "spreads",
    "BOTH_TEAMS_TO_SCORE": "btts",
    "BTTS": "btts",
    "TEAM_TOTAL": "team_totals",
    "TEAM_TOTALS": "team_totals",
    "HOME_TEAM_OVER_UNDER": "team_totals",
    "AWAY_TEAM_OVER_UNDER": "team_totals",
    "CORRECT_SCORE": "correct_score",
    "WINNING_MARGIN": "winning_margin",
    "WIN_MARGIN": "winning_margin",
    "CLEAN_SHEET": "clean_sheet",
    "WIN_TO_NIL": "win_to_nil",
    "TO_WIN_TO_NIL": "win_to_nil",
}

_PATTERN_FAMILY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"1\s*x\s*2|match\s*odds|moneyline|full\s*time\s*result", re.I), "h2h"),
    (re.compile(r"over.?under|total\s*goals|goals?\s*over", re.I), "totals"),
    (re.compile(r"handicap|spread|asian", re.I), "spreads"),
    (re.compile(r"both\s*teams?\s*to\s*score|btts", re.I), "btts"),
    (re.compile(r"team\s*total", re.I), "team_totals"),
    (re.compile(r"correct\s*score|exact\s*score", re.I), "correct_score"),
    (re.compile(r"winning\s*margin|win\s*margin|margin\s*of\s*victory", re.I), "winning_margin"),
    (re.compile(r"clean\s*sheet", re.I), "clean_sheet"),
    (re.compile(r"win\s*to\s*nil|to\s*win\s*to\s*nil", re.I), "win_to_nil"),
]

_MATRIX_PRIORITY = {
    "h2h": "required",
    "totals": "required",
    "spreads": "required",
    "btts": "strong",
    "team_totals": "strong",
    "alternate_totals": "strong",
    "alternate_spreads": "preferred",
    "correct_score": "optional",
    "winning_margin": "optional",
    "clean_sheet": "optional",
    "win_to_nil": "optional",
    "unknown": "optional",
}


class MarketLiveFetchError(ValueError):
    """Safe live-fetch error for diagnostics endpoints."""


def _norm_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _classify_market(market_name: str) -> str:
    key = _norm_name(market_name).upper().replace(" ", "_")
    if key in _EXACT_FAMILY:
        return _EXACT_FAMILY[key]
    for pattern, family in _PATTERN_FAMILY:
        if pattern.search(market_name):
            return family
    return "unknown"


def _decimal_odds_present(market_books: list[dict[str, Any]]) -> bool:
    for book in market_books:
        for key in ("outcome_0", "outcome_1", "outcome_2"):
            val = book.get(key)
            if isinstance(val, (int, float)) and val > 1.0:
                return True
    return False


def _outcome_labels(market_name: str, market_books: list[dict[str, Any]]) -> list[str]:
    name = market_name.upper()
    if name in ("1X2",):
        return ["home", "draw", "away"]
    if name in ("HOME_AWAY",):
        return ["home", "away"]
    if "OVER_UNDER" in name or "TOTAL" in name:
        return ["over", "under"]
    if "HANDICAP" in name or "SPREAD" in name:
        return ["home", "away"]
    if "BOTH_TEAMS" in name or "BTTS" in name:
        return ["yes", "no"]
    labels: list[str] = []
    if market_books:
        book = market_books[0]
        for idx, label in enumerate(("outcome_0", "outcome_1", "outcome_2")):
            if book.get(label) is not None:
                labels.append(f"outcome_{idx}")
    return labels


def _parsing_confidence(
    family: str,
    *,
    bookmaker_count: int,
    has_line: bool,
    decimal_odds: bool,
) -> str:
    if family == "unknown" or not decimal_odds or bookmaker_count == 0:
        return "LOW"
    if family in ("h2h", "totals", "spreads", "btts") and bookmaker_count >= 2:
        return "HIGH"
    if family in ("team_totals", "alternate_totals", "alternate_spreads"):
        return "MEDIUM" if bookmaker_count >= 1 and has_line else "LOW"
    if bookmaker_count >= 1:
        return "MEDIUM"
    return "LOW"


def summarize_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw RapidAPI markets into Phase 1C audit table rows."""
    rows: list[dict[str, Any]] = []
    for market in markets:
        market_name = _norm_name(market.get("market_name"))
        family = _classify_market(market_name)
        books = [b for b in (market.get("market_books") or []) if isinstance(b, dict)]
        book_names = sorted({_norm_name(b.get("book")) for b in books if b.get("book")})
        line = market.get("value")
        rows.append(
            {
                "provider_market_id": market.get("id"),
                "provider_market_name": market_name,
                "mapped_family": family,
                "period": market.get("period"),
                "placing": market.get("placing"),
                "bet_type": market.get("bet_type"),
                "line_point": line,
                "value_type": market.get("value_type"),
                "bookmaker_count": len(books),
                "bookmaker_names": book_names[:20],
                "outcome_labels": _outcome_labels(market_name, books),
                "decimal_odds_available": _decimal_odds_present(books),
                "sample_odds": [
                    {
                        "book": b.get("book"),
                        "outcome_0": b.get("outcome_0"),
                        "outcome_1": b.get("outcome_1"),
                        "outcome_2": b.get("outcome_2"),
                        "is_open": b.get("is_open"),
                    }
                    for b in books[:3]
                ],
                "parsing_confidence": _parsing_confidence(
                    family,
                    bookmaker_count=len(books),
                    has_line=line is not None,
                    decimal_odds=_decimal_odds_present(books),
                ),
                "matrix_priority": _MATRIX_PRIORITY.get(family, "optional"),
            }
        )
    return rows


def build_rapidapi_audit_report(
    *,
    provider_event_id: str,
    home_team: str,
    away_team: str,
    raw_markets: list[dict[str, Any]],
    tournament: str | None = None,
) -> dict[str, Any]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_event": {
            "event_id": provider_event_id,
            "label": f"{home_team.strip()} vs {away_team.strip()}",
            "tournament": tournament,
            "selection_note": "live_provider_fetch",
        },
        "market_coverage_table": summarize_markets(raw_markets),
    }


def fetch_live_market_audit_report(
    *,
    provider: str,
    provider_event_id: str,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    """Fetch and normalize a live provider snapshot into RapidAPI audit JSON shape."""
    provider_name = _norm_name(provider).lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        raise MarketLiveFetchError("unsupported_provider")
    if not str(provider_event_id or "").strip():
        raise MarketLiveFetchError("provider_event_id_required")

    if provider_name == "rapidapi_odds_feed":
        try:
            payload = fetch_event_markets(provider_event_id)
        except RapidApiOddsFeedClientError as exc:
            detail = str(exc)
            if detail == "rapidapi_key_not_configured":
                raise MarketLiveFetchError("rapidapi_key_not_configured") from exc
            raise MarketLiveFetchError(detail) from exc

        markets = payload.get("markets") or []
        if not markets:
            raise MarketLiveFetchError("provider_markets_empty")
        return build_rapidapi_audit_report(
            provider_event_id=str(provider_event_id),
            home_team=home_team,
            away_team=away_team,
            raw_markets=markets,
        )

    raise MarketLiveFetchError("unsupported_provider")
