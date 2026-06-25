"""Weighted bookmaker consensus for 1X2 market probabilities."""

from __future__ import annotations

from core.odds_ensemble import BookmakerOddsLine, _normalize

# Sharp / liquid books get higher weight in consensus.
BOOKMAKER_WEIGHTS: dict[str, float] = {
    "pinnacle": 2.5,
    "betfair": 2.0,
    "betfair exchange": 2.0,
    "matchbook": 1.8,
    "3et": 1.6,
    "smarkets": 1.5,
    "bet365": 1.4,
    "williamhill": 1.3,
    "william hill": 1.3,
    "skybet": 1.2,
    "sky bet": 1.2,
    "888sport": 1.1,
}


def bookmaker_weight(bookmaker_id: str) -> float:
    key = bookmaker_id.lower().strip().replace("_", "")
    if key in BOOKMAKER_WEIGHTS:
        return BOOKMAKER_WEIGHTS[key]
    for slug, weight in BOOKMAKER_WEIGHTS.items():
        if slug.replace(" ", "") in key or key in slug.replace(" ", ""):
            return weight
    return 1.0


def weighted_consensus_from_lines(
    lines: list[BookmakerOddsLine],
) -> dict[str, float] | None:
    """Weighted average implied 1X2 percentages (sharp books count more)."""
    if not lines:
        return None
    keys = ("home_win", "draw", "away_win")
    totals = {k: 0.0 for k in keys}
    weight_sum = 0.0
    for line in lines:
        w = bookmaker_weight(line.id)
        weight_sum += w
        for key in keys:
            totals[key] += line.implied_1x2_percent.get(key, 0.0) * w
    if weight_sum <= 0:
        return None
    avg = {k: totals[k] / weight_sum for k in keys}
    normalized = _normalize({k: v / 100.0 for k, v in avg.items()})
    return {k: round(v * 100.0, 2) for k, v in normalized.items()}
