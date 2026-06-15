"""Maher-style attack/defense xG from per-team goal rates."""

from __future__ import annotations

import math


def estimate_xg_pair(
    home_gf: float,
    home_ga: float,
    away_gf: float,
    away_ga: float,
    *,
    global_avg: float = 3.0,
    fallback_half: float | None = None,
) -> tuple[float, float]:
    """
    λ_home = (home GF rate) × (away GA rate) / league_avg_per_team, scaled to global_avg.
  Uses goals_for/against_per_game from team history when available.
    """
    half = fallback_half if fallback_half is not None else global_avg / 2.0
    half = max(half, 0.5)

    h_gf = max(home_gf, 0.2) if home_gf > 0 else half
    h_ga = max(home_ga, 0.2) if home_ga > 0 else half
    a_gf = max(away_gf, 0.2) if away_gf > 0 else half
    a_ga = max(away_ga, 0.2) if away_ga > 0 else half

    home_xg = (h_gf / half) * (a_ga / half) * half
    away_xg = (a_gf / half) * (h_ga / half) * half

    total = home_xg + away_xg
    if total <= 0:
        return half, half
    scale = global_avg / total
    return round(home_xg * scale, 2), round(away_xg * scale, 2)


def power_based_xg(
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    global_avg: float = 3.0,
) -> tuple[float, float]:
    """Split total goals by Elo-style win probability (used when mismatch is large)."""
    delta = home_power - away_power + advantage
    prob_home = 1.0 / (1.0 + math.pow(10, -delta / 400))
    home_xg = prob_home * global_avg
    away_xg = (1.0 - prob_home) * global_avg
    return round(home_xg, 2), round(away_xg, 2)


def blend_maher_with_power(
    maher_home: float,
    maher_away: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    global_avg: float = 3.0,
) -> tuple[float, float]:
    """
    Blend Maher goal rates with power-based xG.
    Large Elo gaps (e.g. Spain vs Cape Verde) weight power more — avoids 2-0 on
    mismatches where historical averages compress the favorite.
    """
    power_home, power_away = power_based_xg(
        home_power, away_power, advantage, global_avg=global_avg
    )
    gap = abs(home_power - away_power + advantage)
    if gap >= 200:
        maher_w = 0.25
    elif gap >= 100:
        maher_w = 0.45
    elif gap >= 50:
        maher_w = 0.65
    else:
        maher_w = 0.85

    home = maher_home * maher_w + power_home * (1.0 - maher_w)
    away = maher_away * maher_w + power_away * (1.0 - maher_w)
    total = home + away
    if total <= 0:
        return power_home, power_away
    scale = global_avg / total
    return round(home * scale, 2), round(away * scale, 2)
