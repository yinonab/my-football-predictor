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
    home_elo: float | None = None,
    away_elo: float | None = None,
) -> tuple[float, float]:
    """Split total goals by Elo-style win probability (used when mismatch is large)."""
    if home_elo is not None and away_elo is not None:
        delta = home_elo - away_elo + advantage
    else:
        delta = home_power - away_power + advantage
    prob_home = 1.0 / (1.0 + math.pow(10, -delta / 400))
    home_xg = prob_home * global_avg
    away_xg = (1.0 - prob_home) * global_avg
    return round(home_xg, 2), round(away_xg, 2)


def mismatch_gap(
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    home_elo: float | None = None,
    away_elo: float | None = None,
) -> float:
    """Gap for blend/blowout — Elo gap when much larger than composite power gap."""
    power_gap = abs(home_power - away_power + advantage)
    if home_elo is None or away_elo is None:
        return power_gap
    elo_gap = abs(home_elo - away_elo + advantage)
    return max(power_gap, elo_gap)


def signed_mismatch_gap(
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    home_elo: float | None = None,
    away_elo: float | None = None,
) -> float:
    power_gap = home_power - away_power + advantage
    if home_elo is None or away_elo is None:
        return power_gap
    elo_gap = home_elo - away_elo + advantage
    if abs(elo_gap) > abs(power_gap):
        return elo_gap
    return power_gap


def scale_rho_for_gap(rho: float, gap: float) -> float:
    """Reduce Dixon-Coles draw boost on clear mismatches."""
    g = abs(gap)
    if g >= 220:
        return rho * 0.25
    if g >= 150:
        return rho * 0.45
    if g >= 90:
        return rho * 0.70
    return rho


def floor_underdog_xg(
    home_xg: float,
    away_xg: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    home_elo: float | None = None,
    away_elo: float | None = None,
) -> tuple[float, float]:
    """Keep a realistic goal expectation for the weaker side on large gaps."""
    gap = signed_mismatch_gap(
        home_power, away_power, advantage, home_elo=home_elo, away_elo=away_elo
    )
    if gap > 200:
        floor = min(0.8, 0.42 + abs(gap) / 650.0)
        away_xg = max(away_xg, round(floor, 2))
    elif gap < -200:
        floor = min(0.8, 0.42 + abs(gap) / 650.0)
        home_xg = max(home_xg, round(floor, 2))
    return home_xg, away_xg


def blend_maher_with_power(
    maher_home: float,
    maher_away: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    global_avg: float = 3.0,
    home_elo: float | None = None,
    away_elo: float | None = None,
) -> tuple[float, float]:
    """
    Blend Maher goal rates with Elo-based xG.
    Uses Elo gap when composite power compresses mismatches (e.g. Portugal vs DR Congo).
    """
    power_home, power_away = power_based_xg(
        home_power,
        away_power,
        advantage,
        global_avg=global_avg,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    gap = mismatch_gap(
        home_power, away_power, advantage, home_elo=home_elo, away_elo=away_elo
    )
    if gap >= 220:
        maher_w = 0.12
    elif gap >= 150:
        maher_w = 0.22
    elif gap >= 100:
        maher_w = 0.35
    elif gap >= 50:
        maher_w = 0.55
    else:
        maher_w = 0.80

    home = maher_home * maher_w + power_home * (1.0 - maher_w)
    away = maher_away * maher_w + power_away * (1.0 - maher_w)
    total = home + away
    if total <= 0:
        return power_home, power_away
    scale = global_avg / total
    return round(home * scale, 2), round(away * scale, 2)
