"""Blowout adjustment for heavy mismatches (e.g. Germany 7-1, Spain 5-1)."""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class BlowoutAdjustment:
    home_xg: float
    away_xg: float
    alpha: float
    max_goals: int
    active: bool
    note: str = ""
    fusion_favorite_uplift_capped: bool = False
    fusion_favorite_uplift_cap: float | None = None
    original_uncapped_favorite_xg: float | None = None
    capped_favorite_xg: float | None = None
    dog_floor_adaptive_applied: bool = False
    dog_floor_original: float | None = None
    dog_floor_adaptive: float | None = None
    dog_floor_reason: str | None = None
    underdog_attack: float | None = None
    favorite_defense: float | None = None
    underdog_gf_ga_fallback: bool | None = None


def compute_adaptive_dog_floor(
    standard_floor: float,
    *,
    underdog_attack: float | None,
    favorite_defense: float | None,
    gf_ga_fallback: bool,
    power_gap: float,
    weak_attack_threshold: float,
    weak_floor_low: float,
    weak_floor_high: float,
    favorite_defense_strong: float,
    favorite_defense_max_penalty: float,
    fallback_extra_reduction: float,
    floor_min: float,
    gap_threshold: float,
) -> tuple[float, str]:
    """Attack-aware blowout dog floor shared by Fusion and Standard Blowout.

    Only *relaxes* the standard floor (never raises it) and only for genuinely weak
    underdogs (low attack + large gap). Strong underdogs and small gaps keep the
    standard floor. Returns (floor, reason).
    """
    if underdog_attack is None:
        return standard_floor, "standard_dog_floor_no_attack"
    if underdog_attack > weak_attack_threshold:
        return standard_floor, "standard_dog_floor_strong_attack"
    if abs(power_gap) <= gap_threshold:
        return standard_floor, "standard_dog_floor_small_gap"

    threshold = max(weak_attack_threshold, 1e-6)
    attack_frac = max(0.0, min(1.0, underdog_attack / threshold))
    weak_floor = weak_floor_low + attack_frac * (weak_floor_high - weak_floor_low)

    if favorite_defense is not None and favorite_defense > favorite_defense_strong:
        span = favorite_defense - favorite_defense_strong
        weak_floor -= min(favorite_defense_max_penalty, span * 0.25)

    if gf_ga_fallback:
        weak_floor -= fallback_extra_reduction

    weak_floor = max(floor_min, weak_floor)
    adaptive = min(standard_floor, weak_floor)
    reason = (
        "adaptive_weak_dog_floor_fallback"
        if gf_ga_fallback
        else "adaptive_weak_dog_floor"
    )
    return round(adaptive, 2), reason


from core.maher import signed_mismatch_gap


def apply_blowout_adjustment(
    home_xg: float,
    away_xg: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    base_alpha: float = 0.0,
    gap_start: float = 180.0,
    gap_full: float = 450.0,
    home_elo: float | None = None,
    away_elo: float | None = None,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    home_gf_ga_fallback: bool = False,
    away_gf_ga_fallback: bool = False,
) -> BlowoutAdjustment:
    """
    When Elo/power gap is extreme, inflate favorite xG and variance so 4-0, 5-1,
    7-1 style scorelines get meaningful probability mass.

    Part 4 (Stage 3): the underdog floor is attack-aware for very weak underdogs
    (parity with the Fusion path). Favorite amplification is unchanged. Extra
    team-signal args are optional and keyword-only, so existing callers are
    unaffected.
    """
    gap = signed_mismatch_gap(
        home_power,
        away_power,
        advantage,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    abs_gap = abs(gap)
    if abs_gap < gap_start:
        return BlowoutAdjustment(
            home_xg=home_xg,
            away_xg=away_xg,
            alpha=base_alpha,
            max_goals=6,
            active=False,
        )

    t = min(1.0, (abs_gap - gap_start) / max(gap_full - gap_start, 1.0))

    if gap >= 0:
        fav_xg, dog_xg = home_xg, away_xg
        underdog_attack, favorite_defense = away_attack, home_defense
        underdog_fallback = away_gf_ga_fallback
    else:
        fav_xg, dog_xg = away_xg, home_xg
        underdog_attack, favorite_defense = home_attack, away_defense
        underdog_fallback = home_gf_ga_fallback

    # Target favorite lambda up to ~4.2; underdog still scores in blowouts (5-1, 4-1)
    fav_target = 2.8 + t * 1.6
    fav_xg = fav_xg + t * max(0.0, fav_target - fav_xg)
    standard_dog_floor = round(0.55 + 0.4 * t, 4)

    dog_floor = standard_dog_floor
    dog_floor_reason = "standard_dog_floor"
    if config.STANDARD_BLOWOUT_ADAPTIVE_DOG_FLOOR_ENABLED:
        dog_floor, dog_floor_reason = compute_adaptive_dog_floor(
            standard_dog_floor,
            underdog_attack=underdog_attack,
            favorite_defense=favorite_defense,
            gf_ga_fallback=underdog_fallback,
            power_gap=gap,
            weak_attack_threshold=config.FUSION_WEAK_ATTACK_THRESHOLD,
            weak_floor_low=config.FUSION_WEAK_DOG_FLOOR_LOW,
            weak_floor_high=config.FUSION_WEAK_DOG_FLOOR_HIGH,
            favorite_defense_strong=config.FUSION_DOG_FLOOR_FAVORITE_DEFENSE_STRONG,
            favorite_defense_max_penalty=config.FUSION_DOG_FLOOR_FAVORITE_DEFENSE_MAX_PENALTY,
            fallback_extra_reduction=config.FUSION_DOG_FLOOR_FALLBACK_EXTRA_REDUCTION,
            floor_min=config.FUSION_DOG_FLOOR_MIN,
            gap_threshold=config.FUSION_DOG_FLOOR_GAP_THRESHOLD,
        )
    dog_floor_adaptive_applied = dog_floor < standard_dog_floor - 1e-9
    dog_xg = max(dog_floor, dog_xg * (1.0 - 0.08 * t))

    if gap >= 0:
        home_adj, away_adj = fav_xg, dog_xg
        fav_label = "home"
    else:
        home_adj, away_adj = dog_xg, fav_xg
        fav_label = "away"

    alpha = max(base_alpha, 0.08 + 0.22 * t)
    max_goals = 8 if t >= 0.35 else 7 if t > 0 else 6

    note = (
        f"מצב גולנט ({abs_gap:.0f} נק' פער): xG מורחב {round(home_adj, 2)}-{round(away_adj, 2)} "
        f"— תוצאות 4-0 עד 6+ שערים אפשריות"
    )

    return BlowoutAdjustment(
        home_xg=round(home_adj, 2),
        away_xg=round(away_adj, 2),
        alpha=round(alpha, 3),
        max_goals=max_goals,
        active=True,
        note=note if fav_label == "home" else note.replace("מורחב", "מורחב (חוץ)"),
        dog_floor_adaptive_applied=dog_floor_adaptive_applied,
        dog_floor_original=standard_dog_floor,
        dog_floor_adaptive=dog_floor,
        dog_floor_reason=dog_floor_reason,
        underdog_attack=underdog_attack,
        favorite_defense=favorite_defense,
        underdog_gf_ga_fallback=underdog_fallback,
    )
