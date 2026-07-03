"""Maher-style attack/defense xG from per-team goal rates."""

from __future__ import annotations

import math

import config


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


def _standard_underdog_floor(gap: float) -> float:
    """Pre-Stage-2 flat floor: ~0.42 rising with gap, capped at 0.80."""
    return round(min(0.8, 0.42 + abs(gap) / 650.0), 2)


def compute_adaptive_underdog_floor(
    gap: float,
    *,
    underdog_attack: float | None,
    favorite_defense: float | None,
    gf_ga_fallback: bool,
) -> tuple[float, str]:
    """
    Stage 2 adaptive floor for the weaker side on large gaps.

    Returns (floor, reason). Lowers the standard flat floor only for genuinely
    weak underdogs (very low attack rating). A low attack is a real weakness
    signal even when the team has recent GF/GA, so it — not the GF/GA source — is
    the primary trigger; fallback GF/GA only lowers the floor a little more.
    Stronger underdogs (attack above threshold) keep the standard floor and are
    never suppressed like Haiti/Cape Verde.
    """
    standard = _standard_underdog_floor(gap)
    if not config.ADAPTIVE_UNDERDOG_FLOOR_ENABLED:
        return standard, "standard_floor_disabled"
    if underdog_attack is None:
        return standard, "standard_floor_no_attack_signal"
    if underdog_attack > config.ADAPTIVE_UNDERDOG_WEAK_ATTACK_THRESHOLD:
        return standard, "standard_floor_strong_attack"

    threshold = max(config.ADAPTIVE_UNDERDOG_WEAK_ATTACK_THRESHOLD, 1e-6)
    attack_frac = max(0.0, min(1.0, underdog_attack / threshold))
    low = config.ADAPTIVE_UNDERDOG_WEAK_ATTACK_FLOOR_LOW
    high = config.ADAPTIVE_UNDERDOG_WEAK_ATTACK_MAX_FLOOR
    weak_floor = low + attack_frac * (high - low)

    if (
        favorite_defense is not None
        and favorite_defense > config.ADAPTIVE_UNDERDOG_FAVORITE_DEFENSE_STRONG
    ):
        span = favorite_defense - config.ADAPTIVE_UNDERDOG_FAVORITE_DEFENSE_STRONG
        penalty = min(config.ADAPTIVE_UNDERDOG_FAVORITE_DEFENSE_MAX_PENALTY, span * 0.25)
        weak_floor -= penalty

    if gf_ga_fallback:
        weak_floor -= config.ADAPTIVE_UNDERDOG_FALLBACK_EXTRA_REDUCTION

    weak_floor = max(config.ADAPTIVE_UNDERDOG_FLOOR_MIN, weak_floor)
    # Never raise above the standard floor — this stage only relaxes it.
    adaptive = min(standard, weak_floor)
    reason = (
        "adaptive_weak_underdog_floor_fallback"
        if gf_ga_fallback
        else "adaptive_weak_underdog_floor"
    )
    return round(adaptive, 2), reason


def floor_underdog_xg(
    home_xg: float,
    away_xg: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    home_elo: float | None = None,
    away_elo: float | None = None,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    home_gf_ga_fallback: bool = False,
    away_gf_ga_fallback: bool = False,
    diagnostics: dict | None = None,
) -> tuple[float, float]:
    """Keep a realistic goal expectation for the weaker side on large gaps.

    Stage 2: the floor is adaptive for very weak underdogs with fallback GF/GA
    (see ``compute_adaptive_underdog_floor``). Extra team-signal args are optional
    and keyword-only, so existing callers keep the standard behaviour.
    """
    gap = signed_mismatch_gap(
        home_power, away_power, advantage, home_elo=home_elo, away_elo=away_elo
    )
    if gap > 200:
        standard = _standard_underdog_floor(gap)
        floor, reason = compute_adaptive_underdog_floor(
            gap,
            underdog_attack=away_attack,
            favorite_defense=home_defense,
            gf_ga_fallback=away_gf_ga_fallback,
        )
        original_away = away_xg
        away_xg = max(away_xg, floor)
        if diagnostics is not None:
            diagnostics.update(
                {
                    "underdog_side": "away",
                    "underdog_floor_applied": away_xg > original_away + 1e-9,
                    "underdog_floor_standard": standard,
                    "underdog_floor_adaptive": floor,
                    "underdog_floor_reason": reason,
                    "underdog_attack": away_attack,
                    "favorite_defense": home_defense,
                    "underdog_gf_ga_fallback": away_gf_ga_fallback,
                }
            )
    elif gap < -200:
        standard = _standard_underdog_floor(gap)
        floor, reason = compute_adaptive_underdog_floor(
            gap,
            underdog_attack=home_attack,
            favorite_defense=away_defense,
            gf_ga_fallback=home_gf_ga_fallback,
        )
        original_home = home_xg
        home_xg = max(home_xg, floor)
        if diagnostics is not None:
            diagnostics.update(
                {
                    "underdog_side": "home",
                    "underdog_floor_applied": home_xg > original_home + 1e-9,
                    "underdog_floor_standard": standard,
                    "underdog_floor_adaptive": floor,
                    "underdog_floor_reason": reason,
                    "underdog_attack": home_attack,
                    "favorite_defense": away_defense,
                    "underdog_gf_ga_fallback": home_gf_ga_fallback,
                }
            )
    elif diagnostics is not None:
        diagnostics.update(
            {
                "underdog_side": "away" if gap >= 0 else "home",
                "underdog_floor_applied": False,
                "underdog_floor_standard": None,
                "underdog_floor_adaptive": None,
                "underdog_floor_reason": "no_floor_small_gap",
            }
        )
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
    maher_confidence: float = 1.0,
) -> tuple[float, float]:
    """
    Blend Maher goal rates with Elo-based xG.
    Uses Elo gap when composite power compresses mismatches (e.g. Portugal vs DR Congo).

    ``maher_confidence`` (Stage 2) scales the Maher blend weight. When GF/GA is a
    fallback the Maher pair carries no real signal, so callers pass < 1.0 to let
    power/Elo differentiation lead. 1.0 preserves the original blend.
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

    maher_w *= max(0.0, min(1.0, maher_confidence))

    home = maher_home * maher_w + power_home * (1.0 - maher_w)
    away = maher_away * maher_w + power_away * (1.0 - maher_w)
    total = home + away
    if total <= 0:
        return power_home, power_away
    scale = global_avg / total
    return round(home * scale, 2), round(away * scale, 2)
