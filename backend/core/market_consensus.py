"""Cross-bookmaker consensus for normalized market snapshots."""

from __future__ import annotations

from collections import defaultdict

from core.market_types import BookmakerMarketLine, MarketConsensus, MarketFamily, NormalizedMarketSnapshot
from core.odds_consensus import bookmaker_weight


def _line_key(line: float | None) -> str:
    if line is None:
        return "main"
    return f"{line:g}"


def _weighted_mean(
    entries: list[tuple[float, float]],
) -> float:
    """entries: (weight, fair_probability percent)."""
    total_w = sum(w for w, _ in entries)
    if total_w <= 0:
        return 0.0
    return sum(w * p for w, p in entries) / total_w


def _consensus_for_outcomes(
    lines: list[BookmakerMarketLine],
    outcome_names: tuple[str, ...],
) -> dict[str, float] | None:
    buckets: dict[str, list[tuple[float, float]]] = {n: [] for n in outcome_names}
    for line in lines:
        w = bookmaker_weight(line.bookmaker_id)
        by_name = {o.name: o.fair_probability for o in line.outcomes}
        for name in outcome_names:
            if name in by_name:
                buckets[name].append((w, by_name[name]))
    result: dict[str, float] = {}
    for name in outcome_names:
        if buckets[name]:
            result[name] = round(_weighted_mean(buckets[name]), 2)
    return result or None


def build_market_consensus(snapshot: NormalizedMarketSnapshot) -> MarketConsensus:
    """Aggregate fair probabilities across bookmakers."""
    h2h_lines = [ln for ln in snapshot.lines if ln.family == MarketFamily.H2H]
    btts_lines = [ln for ln in snapshot.lines if ln.family == MarketFamily.BTTS]

    totals_by_line: dict[str, dict[str, float]] = {}
    totals_grouped: dict[str, list[BookmakerMarketLine]] = defaultdict(list)
    for ln in snapshot.lines:
        if ln.family == MarketFamily.TOTALS:
            totals_grouped[_line_key(ln.line)].append(ln)
    for key, group in totals_grouped.items():
        consensus = _consensus_for_outcomes(group, ("over", "under"))
        if consensus:
            totals_by_line[key] = consensus

    spreads_by_line: dict[str, dict[str, float]] = {}
    spreads_grouped: dict[str, list[BookmakerMarketLine]] = defaultdict(list)
    for ln in snapshot.lines:
        if ln.family == MarketFamily.SPREADS:
            spreads_grouped[_line_key(ln.line)].append(ln)
    for key, group in spreads_grouped.items():
        consensus = _consensus_for_outcomes(group, ("home", "away"))
        if consensus:
            spreads_by_line[key] = consensus

    book_ids = {ln.bookmaker_id for ln in snapshot.lines}
    return MarketConsensus(
        h2h=_consensus_for_outcomes(h2h_lines, ("home", "draw", "away")),
        totals_by_line=totals_by_line,
        spreads_by_line=spreads_by_line,
        btts=_consensus_for_outcomes(btts_lines, ("yes", "no")),
        bookmaker_counts={
            "h2h": len({ln.bookmaker_id for ln in h2h_lines}),
            "totals": len({ln.bookmaker_id for ln in snapshot.lines if ln.family == MarketFamily.TOTALS}),
            "spreads": len({ln.bookmaker_id for ln in snapshot.lines if ln.family == MarketFamily.SPREADS}),
            "btts": len({ln.bookmaker_id for ln in btts_lines}),
            "all": len(book_ids),
        },
    )
