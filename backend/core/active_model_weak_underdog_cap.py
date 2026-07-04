"""Attack-aware cap on the served (NR3-FCC) weak-underdog xG.

Why this exists
---------------
The production served model is ``v2.3.0-nr3-fcc-served``. Its base xG comes from
the NR3 strength generator (``generate_strength_based_xg``), which:

* caps the favorite's share of total xG at ``max_favorite_share`` (~0.68), and
* runs with ``use_attack_defense=False`` (attack/defense ratings are ignored).

In a large mismatch (e.g. Argentina vs Cape Verde) the favorite hits that share
cap, so the underdog is structurally floored at ~32% of a ~2.9 total (~0.9 xG),
regardless of how weak the underdog's attack actually is. Fusion then only
preserves that high base. The Stage 3 adaptive *dog floor* cannot help here: it
lowers a minimum, but the served underdog xG already sits well above the floor.

This module applies a **cap** (a maximum), not another floor reduction. For a
weak-attack underdog in a large power mismatch it lowers the served underdog xG
into a target band and never raises it. Underdogs with a real attacking signal
(attack above threshold) are never touched, so competitive/strong underdogs are
preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import config


@dataclass(frozen=True)
class WeakUnderdogCapResult:
    home_xg: float
    away_xg: float
    applied: bool
    reason: str
    underdog_side: str | None = None
    original_underdog_xg: float | None = None
    capped_underdog_xg: float | None = None
    cap_value: float | None = None
    underdog_attack: float | None = None
    favorite_defense: float | None = None
    power_gap: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_model_weak_underdog_cap_applied": self.applied,
            "active_model_weak_underdog_cap_reason": self.reason,
            "active_model_weak_underdog_side": self.underdog_side,
            "active_model_weak_underdog_cap_original_xg": self.original_underdog_xg,
            "active_model_weak_underdog_cap_xg": self.capped_underdog_xg,
            "active_model_weak_underdog_cap_value": self.cap_value,
            "active_model_weak_underdog_attack": self.underdog_attack,
            "active_model_favorite_defense": self.favorite_defense,
            "active_model_power_gap": self.power_gap,
        }


def compute_weak_underdog_cap(
    underdog_attack: float,
    *,
    favorite_defense: float | None,
    gf_ga_fallback: bool,
) -> float:
    """Target cap band, scaled by how weak the underdog's attack is.

    attack 0 -> MAX_XG_LOW; attack == threshold -> MAX_XG_HIGH. Strong favorite
    defense and fallback GF/GA tighten the cap a little. Never below MIN_XG.
    """
    threshold = config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD
    low = config.ACTIVE_MODEL_WEAK_UNDERDOG_MAX_XG_LOW
    high = config.ACTIVE_MODEL_WEAK_UNDERDOG_MAX_XG_HIGH
    frac = max(0.0, min(1.0, underdog_attack / threshold)) if threshold > 0 else 0.0
    cap = low + frac * (high - low)
    if (
        favorite_defense is not None
        and favorite_defense >= config.ACTIVE_MODEL_WEAK_UNDERDOG_FAVORITE_DEFENSE_STRONG
    ):
        cap -= config.ACTIVE_MODEL_WEAK_UNDERDOG_FAVORITE_DEFENSE_PENALTY
    if gf_ga_fallback:
        cap -= config.ACTIVE_MODEL_WEAK_UNDERDOG_FALLBACK_PENALTY
    return max(config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG, round(cap, 4))


def apply_weak_underdog_xg_cap(
    home_xg: float,
    away_xg: float,
    *,
    home_power: float,
    away_power: float,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    power_gap: float | None = None,
    home_gf_ga_fallback: bool = False,
    away_gf_ga_fallback: bool = False,
) -> WeakUnderdogCapResult:
    """Cap the served underdog xG for a weak-attack side in a large mismatch."""
    if not config.ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED:
        return WeakUnderdogCapResult(
            home_xg=home_xg, away_xg=away_xg, applied=False, reason="disabled"
        )

    gap = abs(power_gap if power_gap is not None else (home_power - away_power))

    if home_power >= away_power:
        underdog_side = "away"
        underdog_xg = away_xg
        underdog_attack = away_attack
        favorite_defense = home_defense
        underdog_fallback = away_gf_ga_fallback
    else:
        underdog_side = "home"
        underdog_xg = home_xg
        underdog_attack = home_attack
        favorite_defense = away_defense
        underdog_fallback = home_gf_ga_fallback

    common = dict(
        underdog_side=underdog_side,
        underdog_attack=underdog_attack,
        favorite_defense=favorite_defense,
        power_gap=round(gap, 2),
        original_underdog_xg=round(float(underdog_xg), 2),
    )

    if underdog_attack is None:
        return WeakUnderdogCapResult(
            home_xg=home_xg, away_xg=away_xg, applied=False,
            reason="no_attack_signal", **common
        )
    if underdog_attack > config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD:
        return WeakUnderdogCapResult(
            home_xg=home_xg, away_xg=away_xg, applied=False,
            reason="strong_attack_preserved", **common
        )
    if gap <= config.ACTIVE_MODEL_WEAK_UNDERDOG_POWER_GAP_THRESHOLD:
        return WeakUnderdogCapResult(
            home_xg=home_xg, away_xg=away_xg, applied=False,
            reason="gap_below_threshold", **common
        )

    cap = compute_weak_underdog_cap(
        float(underdog_attack),
        favorite_defense=favorite_defense,
        gf_ga_fallback=underdog_fallback,
    )
    if underdog_xg <= cap + 1e-9:
        return WeakUnderdogCapResult(
            home_xg=home_xg, away_xg=away_xg, applied=False,
            reason="underdog_xg_at_or_below_cap", cap_value=cap, **common
        )

    capped = round(cap, 2)
    if underdog_side == "away":
        new_home, new_away = home_xg, capped
    else:
        new_home, new_away = capped, away_xg

    return WeakUnderdogCapResult(
        home_xg=new_home,
        away_xg=new_away,
        applied=True,
        reason="weak_underdog_cap_applied",
        cap_value=cap,
        capped_underdog_xg=capped,
        **common,
    )
