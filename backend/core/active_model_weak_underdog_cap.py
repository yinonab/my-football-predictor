"""Hybrid tier + continuous cap on served (NR3-FCC) weak-underdog xG.

The NR3 strength generator ignores attack/defense and structurally over-credits
weak underdogs via ``max_favorite_share``. This module applies a post-fusion
**maximum** cap (never raises underdog xG) with tier-specific bands:

* **ultra_weak** — attack <= ultra threshold, large gap
* **medium_weak** — attack between ultra and weak thresholds, larger gap
* **strong** — no cap
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import config

TierName = Literal["ultra_weak", "medium_weak", "strong", "unclear"]


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
    cap_delta: float | None = None
    underdog_attack: float | None = None
    favorite_defense: float | None = None
    power_gap: float | None = None
    tier: TierName = "unclear"
    tier_gap_floor: float | None = None
    cap_band_min: float | None = None
    cap_band_max: float | None = None
    attack_used: float | None = None
    attack_source: str | None = None
    raw_attack: float | None = None
    history_attack: float | None = None
    favorite_defense_used: float | None = None
    gf_ga_fallback_used: bool = False
    ultra_attack_threshold: float | None = None
    weak_attack_threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_model_weak_underdog_cap_applied": self.applied,
            "active_model_weak_underdog_cap_reason": self.reason,
            "active_model_weak_underdog_side": self.underdog_side,
            "active_model_weak_underdog_cap_original_xg": self.original_underdog_xg,
            "active_model_weak_underdog_cap_xg": self.capped_underdog_xg,
            "active_model_weak_underdog_cap_value": self.cap_value,
            "active_model_weak_underdog_cap_delta": self.cap_delta,
            "active_model_weak_underdog_attack": self.underdog_attack,
            "active_model_favorite_defense": self.favorite_defense,
            "active_model_power_gap": self.power_gap,
            "active_model_weak_underdog_tier": self.tier,
            "active_model_weak_underdog_tier_gap_floor": self.tier_gap_floor,
            "active_model_weak_underdog_cap_band_min": self.cap_band_min,
            "active_model_weak_underdog_cap_band_max": self.cap_band_max,
            "active_model_weak_underdog_attack_used": self.attack_used,
            "active_model_weak_underdog_attack_source": self.attack_source,
            "active_model_weak_underdog_raw_attack": self.raw_attack,
            "active_model_weak_underdog_history_attack": self.history_attack,
            "active_model_favorite_defense_used": self.favorite_defense_used,
            "active_model_weak_underdog_gf_ga_fallback_used": self.gf_ga_fallback_used,
            "active_model_weak_underdog_ultra_attack_threshold": self.ultra_attack_threshold,
            "active_model_weak_underdog_weak_attack_threshold": self.weak_attack_threshold,
        }


def classify_underdog_tier(attack: float) -> TierName:
    ultra = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_ATTACK_THRESHOLD
    weak = config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD
    if attack <= ultra:
        return "ultra_weak"
    if attack <= weak:
        return "medium_weak"
    return "strong"


def tier_gap_floor(tier: TierName) -> float | None:
    if tier == "ultra_weak":
        return config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    if tier == "medium_weak":
        return config.ACTIVE_MODEL_WEAK_UNDERDOG_MEDIUM_POWER_GAP_THRESHOLD
    return None


def resolve_cap_attack(
    *,
    pipeline_attack: float | None,
    raw_attack: float | None,
    gf_ga_fallback: bool,
) -> tuple[float | None, str, float | None, float | None]:
    """Pick attack for tier/cap; conservative min when GF/GA is fallback."""
    history = pipeline_attack
    raw = raw_attack

    if pipeline_attack is None and raw_attack is None:
        return None, "none", raw, history

    if raw is not None and history is not None:
        delta = abs(float(raw) - float(history))
        if delta >= config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_SOURCE_CONFLICT_DELTA:
            return (
                min(float(raw), float(history)),
                "min_source_conflict",
                raw,
                history,
            )

    if (
        gf_ga_fallback
        and raw is not None
        and history is not None
        and abs(float(raw) - float(history)) > 1e-6
    ):
        return min(float(raw), float(history)), "min_fallback_conservative", raw, history

    if pipeline_attack is not None:
        return float(pipeline_attack), "pipeline_get_team_data", raw, history

    return float(raw_attack), "database_only", raw, history


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _defense_penalty(favorite_defense: float | None) -> float:
    if favorite_defense is None:
        return 0.0
    baseline = config.ACTIVE_MODEL_WEAK_UNDERDOG_FAVORITE_DEFENSE_BASELINE
    if favorite_defense <= baseline:
        return 0.0
    span = max(config.ACTIVE_MODEL_WEAK_UNDERDOG_FAVORITE_DEFENSE_STRONG - baseline, 1e-9)
    frac = _clamp01((favorite_defense - baseline) / span)
    return config.ACTIVE_MODEL_WEAK_UNDERDOG_FAVORITE_DEFENSE_PENALTY * frac


def _gap_penalty(tier: TierName, power_gap: float, tier_floor: float) -> float:
    if tier != "ultra_weak" or power_gap <= tier_floor:
        return 0.0
    excess = power_gap - tier_floor
    span = max(config.ACTIVE_MODEL_WEAK_UNDERDOG_GAP_TIGHTEN_SPAN, 1e-9)
    frac = _clamp01(excess / span)
    return config.ACTIVE_MODEL_WEAK_UNDERDOG_GAP_TIGHTEN_MAX * frac


def compute_weak_underdog_cap(
    tier: TierName,
    underdog_attack: float,
    *,
    favorite_defense: float | None,
    gf_ga_fallback: bool,
    power_gap: float,
    tier_gap_floor_value: float,
) -> tuple[float, float, float]:
    """Return (cap_value, band_min, band_max) for a tier."""
    ultra_thr = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_ATTACK_THRESHOLD
    weak_thr = config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD

    if tier == "ultra_weak":
        band_min = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_CAP_MIN
        band_max = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_CAP_MAX
        weakness = 1.0 - _clamp01(underdog_attack / ultra_thr) if ultra_thr > 0 else 1.0
        cap = band_max - weakness * (band_max - band_min)
    elif tier == "medium_weak":
        band_min = config.ACTIVE_MODEL_WEAK_UNDERDOG_MEDIUM_CAP_MIN
        band_max = config.ACTIVE_MODEL_WEAK_UNDERDOG_MEDIUM_CAP_MAX
        span = max(weak_thr - ultra_thr, 1e-9)
        frac = _clamp01((underdog_attack - ultra_thr) / span)
        cap = band_min + frac * (band_max - band_min)
    else:
        raise ValueError(f"no cap for tier {tier}")

    cap -= _defense_penalty(favorite_defense)
    if gf_ga_fallback:
        cap -= config.ACTIVE_MODEL_WEAK_UNDERDOG_FALLBACK_PENALTY
    cap -= _gap_penalty(tier, power_gap, tier_gap_floor_value)

    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG
    cap = max(floor, round(cap, 4))
    return cap, band_min, band_max


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
    home_attack_raw: float | None = None,
    away_attack_raw: float | None = None,
    power_gap: float | None = None,
    home_gf_ga_fallback: bool = False,
    away_gf_ga_fallback: bool = False,
) -> WeakUnderdogCapResult:
    """Cap served underdog xG using hybrid tier + continuous bands."""
    ultra_thr = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_ATTACK_THRESHOLD
    weak_thr = config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD

    if not config.ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED:
        return WeakUnderdogCapResult(
            home_xg=home_xg,
            away_xg=away_xg,
            applied=False,
            reason="disabled",
            ultra_attack_threshold=ultra_thr,
            weak_attack_threshold=weak_thr,
        )

    gap = abs(power_gap if power_gap is not None else (home_power - away_power))

    if home_power >= away_power:
        underdog_side = "away"
        underdog_xg = away_xg
        pipeline_attack = away_attack
        raw_attack = away_attack_raw if away_attack_raw is not None else away_attack
        favorite_defense = home_defense
        underdog_fallback = away_gf_ga_fallback
    else:
        underdog_side = "home"
        underdog_xg = home_xg
        pipeline_attack = home_attack
        raw_attack = home_attack_raw if home_attack_raw is not None else home_attack
        favorite_defense = away_defense
        underdog_fallback = home_gf_ga_fallback

    attack_used, attack_source, raw_val, hist_val = resolve_cap_attack(
        pipeline_attack=pipeline_attack,
        raw_attack=raw_attack,
        gf_ga_fallback=underdog_fallback,
    )

    diag_base = dict(
        underdog_side=underdog_side,
        underdog_attack=attack_used,
        favorite_defense=favorite_defense,
        favorite_defense_used=favorite_defense,
        power_gap=round(gap, 2),
        original_underdog_xg=round(float(underdog_xg), 2),
        attack_used=attack_used,
        attack_source=attack_source,
        raw_attack=raw_val,
        history_attack=hist_val,
        gf_ga_fallback_used=underdog_fallback,
        ultra_attack_threshold=ultra_thr,
        weak_attack_threshold=weak_thr,
    )

    if attack_used is None:
        return WeakUnderdogCapResult(
            home_xg=home_xg,
            away_xg=away_xg,
            applied=False,
            reason="no_attack_signal",
            tier="unclear",
            **diag_base,
        )

    tier = classify_underdog_tier(attack_used)
    gap_floor = tier_gap_floor(tier)

    if tier == "strong":
        return WeakUnderdogCapResult(
            home_xg=home_xg,
            away_xg=away_xg,
            applied=False,
            reason="strong_attack_preserved",
            tier=tier,
            tier_gap_floor=gap_floor,
            **diag_base,
        )

    if gap_floor is None or gap <= gap_floor:
        return WeakUnderdogCapResult(
            home_xg=home_xg,
            away_xg=away_xg,
            applied=False,
            reason="gap_below_threshold",
            tier=tier,
            tier_gap_floor=gap_floor,
            **diag_base,
        )

    cap, band_min, band_max = compute_weak_underdog_cap(
        tier,
        attack_used,
        favorite_defense=favorite_defense,
        gf_ga_fallback=underdog_fallback,
        power_gap=gap,
        tier_gap_floor_value=gap_floor,
    )

    band_diag = dict(
        tier=tier,
        tier_gap_floor=gap_floor,
        cap_band_min=band_min,
        cap_band_max=band_max,
        cap_value=cap,
    )

    if underdog_xg <= cap + 1e-9:
        return WeakUnderdogCapResult(
            home_xg=home_xg,
            away_xg=away_xg,
            applied=False,
            reason="underdog_xg_at_or_below_cap",
            **diag_base,
            **band_diag,
        )

    capped = round(cap, 2)
    cap_delta = round(capped - float(underdog_xg), 2)
    if underdog_side == "away":
        new_home, new_away = home_xg, capped
    else:
        new_home, new_away = capped, away_xg

    return WeakUnderdogCapResult(
        home_xg=new_home,
        away_xg=new_away,
        applied=True,
        reason="weak_underdog_cap_applied",
        capped_underdog_xg=capped,
        cap_delta=cap_delta,
        **diag_base,
        **band_diag,
    )
