"""Maher-style attack/defense xG from per-team goal rates."""

from __future__ import annotations


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
