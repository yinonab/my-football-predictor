"""RapidAPI Odds Feed → normalized market snapshot parser."""

from __future__ import annotations

import re
from typing import Any

from core.market_devig import devig_three_way, devig_two_way
from core.market_types import (
    BookmakerMarketLine,
    MarketFamily,
    NormalizedMarketSnapshot,
    parse_market_family,
)

_PROVIDER = "rapidapi_odds_feed"
_BOOK_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _book_id(name: str) -> str:
    return _BOOK_SLUG_RE.sub("_", name.lower()).strip("_")


def _parse_h2h_row(
    row: dict[str, Any],
    family: MarketFamily,
) -> list[BookmakerMarketLine]:
    lines: list[BookmakerMarketLine] = []
    market_key = str(row.get("provider_market_name") or "1X2")
    for sample in row.get("sample_odds") or []:
        if not isinstance(sample, dict):
            continue
        book = str(sample.get("book") or "")
        o0, o1, o2 = sample.get("outcome_0"), sample.get("outcome_1"), sample.get("outcome_2")
        if not all(isinstance(x, (int, float)) for x in (o0, o1, o2)):
            continue
        outcomes, overround = devig_three_way(float(o0), float(o1), float(o2))
        if not outcomes:
            continue
        lines.append(
            BookmakerMarketLine(
                bookmaker_id=_book_id(book),
                bookmaker_name=book,
                family=family,
                provider_market_key=market_key,
                line=None,
                outcomes=tuple(outcomes),
                overround=overround,
                placing=row.get("placing"),
                period=row.get("period"),
            )
        )
    return lines


def _parse_two_way_row(
    row: dict[str, Any],
    family: MarketFamily,
    name_a: str,
    name_b: str,
) -> list[BookmakerMarketLine]:
    lines: list[BookmakerMarketLine] = []
    market_key = str(row.get("provider_market_name") or "")
    line_point = row.get("line_point")
    line_val = float(line_point) if isinstance(line_point, (int, float)) else None
    for sample in row.get("sample_odds") or []:
        if not isinstance(sample, dict):
            continue
        book = str(sample.get("book") or "")
        o0, o1 = sample.get("outcome_0"), sample.get("outcome_1")
        if not isinstance(o0, (int, float)) or not isinstance(o1, (int, float)):
            continue
        outcomes, overround = devig_two_way(name_a, float(o0), name_b, float(o1))
        if not outcomes:
            continue
        lines.append(
            BookmakerMarketLine(
                bookmaker_id=_book_id(book),
                bookmaker_name=book,
                family=family,
                provider_market_key=market_key,
                line=line_val,
                outcomes=tuple(outcomes),
                overround=overround,
                placing=row.get("placing"),
                period=row.get("period"),
            )
        )
    return lines


def _family_from_row(row: dict[str, Any]) -> MarketFamily:
    return parse_market_family(str(row.get("mapped_family") or "unknown"))


def parse_market_coverage_table(
    rows: list[dict[str, Any]],
    *,
    event_id: str,
    home_team: str,
    away_team: str,
    tournament: str | None = None,
    fetched_at_utc: str | None = None,
) -> NormalizedMarketSnapshot:
    """Parse audit `market_coverage_table` rows into a snapshot."""
    all_lines: list[BookmakerMarketLine] = []
    totals_lines: set[float] = set()
    spread_lines: set[float] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        family = _family_from_row(row)
        if family == MarketFamily.UNKNOWN:
            continue
        if family == MarketFamily.H2H:
            all_lines.extend(_parse_h2h_row(row, family))
        elif family == MarketFamily.BTTS:
            all_lines.extend(_parse_two_way_row(row, family, "yes", "no"))
        elif family in (MarketFamily.TOTALS, MarketFamily.ALTERNATE_TOTALS):
            lp = row.get("line_point")
            if isinstance(lp, (int, float)):
                totals_lines.add(float(lp))
            all_lines.extend(_parse_two_way_row(row, MarketFamily.TOTALS, "over", "under"))
        elif family in (MarketFamily.SPREADS, MarketFamily.ALTERNATE_SPREADS):
            lp = row.get("line_point")
            if isinstance(lp, (int, float)):
                spread_lines.add(float(lp))
            # line_point = home handicap; outcome_0=home cover, outcome_1=away cover.
            all_lines.extend(
                _parse_two_way_row(row, MarketFamily.SPREADS, "home", "away")
            )

    # Consensus uses line keys; quality uses line counts.
    return NormalizedMarketSnapshot(
        provider=_PROVIDER,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        tournament=tournament,
        fetched_at_utc=fetched_at_utc,
        lines=all_lines,
        providers_seen=(_PROVIDER,),
    )


def parse_audit_report(report: dict[str, Any]) -> NormalizedMarketSnapshot:
    """Parse full Phase 1C audit JSON."""
    selected = report.get("selected_event") or {}
    label = str(selected.get("label") or "")
    home, away = "Home", "Away"
    if " vs " in label:
        parts = label.split(" vs ", 1)
        home, away = parts[0].strip(), parts[1].split(" (")[0].strip()
    rows = report.get("market_coverage_table") or []
    return parse_market_coverage_table(
        rows,
        event_id=str(selected.get("event_id") or ""),
        home_team=home,
        away_team=away,
        tournament=selected.get("tournament"),
        fetched_at_utc=report.get("generated_at_utc"),
    )
