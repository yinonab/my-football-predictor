"""Market data quality scoring for future matrix weighting (not used in predict)."""

from __future__ import annotations

from core.market_types import (
    MarketConsensus,
    MarketFamily,
    MarketQualityResult,
    NormalizedMarketSnapshot,
)

BAND_RED = "RED"
BAND_YELLOW = "YELLOW"
BAND_GREEN = "GREEN"


def _distinct_line_count(snapshot: NormalizedMarketSnapshot, family: MarketFamily) -> int:
    return len(snapshot.distinct_lines_for(family))


def score_market_quality(
    snapshot: NormalizedMarketSnapshot,
    consensus: MarketConsensus | None = None,
) -> MarketQualityResult:
    """Score snapshot readiness for market-implied matrix (infrastructure only)."""
    families = snapshot.families_present() - {MarketFamily.UNKNOWN}
    family_names = tuple(sorted(f.value for f in families))

    total_lines = _distinct_line_count(snapshot, MarketFamily.TOTALS)
    spread_lines = _distinct_line_count(snapshot, MarketFamily.SPREADS)
    has_btts = MarketFamily.BTTS in families
    has_h2h = MarketFamily.H2H in families
    has_totals = MarketFamily.TOTALS in families
    has_spreads = MarketFamily.SPREADS in families

    book_count = len({ln.bookmaker_id for ln in snapshot.lines})
    provider_count = len(snapshot.providers_seen) or (1 if snapshot.provider else 0)

    notes: list[str] = []
    score = 0.0

    if has_h2h:
        score += 25.0
        score += min(snapshot.bookmaker_count_for(MarketFamily.H2H), 10) * 2.0
    if has_totals:
        score += 20.0
        score += min(total_lines, 15) * 1.5
    if has_spreads:
        score += 20.0
        score += min(spread_lines, 15) * 1.0
    if has_btts:
        score += 15.0
        score += min(snapshot.bookmaker_count_for(MarketFamily.BTTS), 8) * 1.0
    if total_lines >= 3 and spread_lines >= 3:
        score += 10.0
        notes.append("multi_line_totals_and_spreads")
    if provider_count >= 2:
        score += 5.0
        notes.append("multi_provider")
    if snapshot.fetched_at_utc:
        score += 2.0
        notes.append("timestamp_present")

    if has_h2h and not has_totals and not has_spreads:
        band = BAND_RED
        notes.append("h2h_only")
    elif has_h2h and has_totals and has_spreads and has_btts and total_lines >= 2 and spread_lines >= 2:
        band = BAND_GREEN
    elif has_h2h and has_totals and has_spreads:
        band = BAND_YELLOW
        if not has_btts:
            notes.append("missing_btts")
    else:
        band = BAND_RED
        notes.append("insufficient_families")

    return MarketQualityResult(
        score=score,
        band=band,
        families_present=family_names,
        bookmaker_count=book_count,
        provider_count=provider_count,
        total_line_count=total_lines,
        spread_line_count=spread_lines,
        has_btts=has_btts,
        notes=tuple(notes),
    )
