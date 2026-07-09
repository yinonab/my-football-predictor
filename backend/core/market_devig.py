"""Multiplicative de-vig for normalized market lines."""

from __future__ import annotations

from core.market_types import OutcomeQuote


def raw_implied_from_decimal(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        return 0.0
    return 100.0 / decimal_odds


def overround_from_raw(raw_implied: list[float]) -> float:
    return sum(raw_implied)


def multiplicative_devig(
    outcomes: list[tuple[str, float]],
) -> tuple[list[OutcomeQuote], float]:
    """Return de-vigged outcomes and overround (sum of raw implied %)."""
    quotes: list[tuple[str, float, float]] = []
    for name, decimal in outcomes:
        if decimal <= 1.0:
            continue
        raw = raw_implied_from_decimal(decimal)
        quotes.append((name, decimal, raw))
    if not quotes:
        return [], 0.0
    total_raw = sum(q[2] for q in quotes)
    if total_raw <= 0:
        return [], 0.0
    result = [
        OutcomeQuote(
            name=name,
            decimal_odds=decimal,
            raw_implied=round(raw, 4),
            fair_probability=round(raw / total_raw * 100.0, 4),
        )
        for name, decimal, raw in quotes
    ]
    return result, round(total_raw, 4)


def devig_two_way(
    name_a: str,
    odds_a: float,
    name_b: str,
    odds_b: float,
) -> tuple[list[OutcomeQuote], float]:
    return multiplicative_devig([(name_a, odds_a), (name_b, odds_b)])


def devig_three_way(
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    *,
    home_name: str = "home",
    draw_name: str = "draw",
    away_name: str = "away",
) -> tuple[list[OutcomeQuote], float]:
    return multiplicative_devig(
        [
            (home_name, home_odds),
            (draw_name, draw_odds),
            (away_name, away_odds),
        ]
    )
