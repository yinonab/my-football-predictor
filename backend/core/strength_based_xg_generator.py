"""Priority 1.7B — Strength-based side xG generator (experimental baseline).

Computes home_xG and away_xG directly from strength signals.
Total xG is always home_xG + away_xG — never anchored to GLOBAL_XG_AVG / 2.6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from core.maher import signed_mismatch_gap

GENERATOR_VERSION = "strength_v1"
SIGNAL_CLIP = 2.0
POWER_REF_FLOOR = 80.0


@dataclass(frozen=True)
class StrengthXgParams:
    """Offline-tuned parameters for strength_v1 (scale is internal, not GLOBAL_XG_AVG)."""

    name: str
    scale: float
    attack_weight: float = 0.0
    defense_weight: float = 0.0
    overall_weight: float = 0.10
    opponent_overall_weight: float = 0.10
    gap_weight: float = 0.10
    use_attack_defense: bool = True
    use_overall_power: bool = True
    use_gap: bool = True
    min_side: float = 0.20
    max_side: float = 3.00
    min_total: float = 1.20
    max_total: float = 4.20
    skip_blowout: bool = False
    signal_mode: str = "overall_plus_attack_defense"
    favorite_share_boost: float = 0.0
    favorite_share_boost_start: float = 0.55
    max_favorite_share: float = 0.72
    # P1.7B.3 micro-probe fields (default 1.0 = no effect; never production defaults)
    knockout_gap_damping: float = 1.0
    knockout_favorite_boost_damping: float = 1.0
    r16_gap_damping: float = 1.0
    r16_favorite_boost_damping: float = 1.0
    power_gap_multiplier: float = 1.0  # P1.7B.9 SW3 — scales gap signal (1.0 = unchanged)


@dataclass
class StrengthSignals:
    home_team: str
    away_team: str
    home_power: float
    away_power: float
    home_elo: float
    away_elo: float
    home_attack: float | None = None
    home_defense: float | None = None
    away_attack: float | None = None
    away_defense: float | None = None
    home_form: float | None = None
    away_form: float | None = None
    population_powers: list[float] | None = None


def _clip_signal(value: float) -> float:
    return max(-SIGNAL_CLIP, min(SIGNAL_CLIP, value))


def _attack_defense_signal(value: float | None) -> tuple[float | None, bool]:
    if value is None or not math.isfinite(value):
        return None, True
    return _clip_signal((value - 0.5) * 2.0), False


def _power_signal(
    power: float,
    elo: float,
    *,
    ref_power: float,
    ref_elo: float,
    population: list[float] | None,
) -> float:
    if population and len(population) >= 5:
        mean = sum(population) / len(population)
        var = sum((x - mean) ** 2 for x in population) / len(population)
        std = max(math.sqrt(var), POWER_REF_FLOOR)
        return _clip_signal((power - mean) / std)
    denom = max(abs(ref_power) * 0.15, POWER_REF_FLOOR)
    p_norm = (power - ref_power) / denom
    e_norm = (elo - ref_elo) / 400.0
    return _clip_signal(0.65 * p_norm + 0.35 * e_norm)


def _side_log_xg(
    *,
    attack_sig: float | None,
    defense_opp_sig: float | None,
    overall_sig: float,
    opponent_overall_sig: float,
    gap_sig: float,
    params: StrengthXgParams,
    warnings: list[str],
) -> float:
    log_xg = params.scale
    if params.use_attack_defense and params.attack_weight > 0:
        if attack_sig is not None:
            log_xg += params.attack_weight * attack_sig
        else:
            warnings.append("missing_attack_signal")
    if params.use_attack_defense and params.defense_weight > 0:
        if defense_opp_sig is not None:
            # Higher opponent defense (better) reduces this side's xG.
            log_xg -= params.defense_weight * defense_opp_sig
        else:
            warnings.append("missing_defense_signal")
    if params.use_overall_power and params.overall_weight > 0:
        log_xg += params.overall_weight * overall_sig
    if params.use_overall_power and params.opponent_overall_weight > 0:
        log_xg -= params.opponent_overall_weight * opponent_overall_sig
    if params.use_gap and params.gap_weight > 0:
        log_xg += params.gap_weight * gap_sig
    return log_xg


def _is_knockout_stage(stage: str | None) -> bool:
    return stage is not None and stage != "group"


def _is_r16_stage(stage: str | None) -> bool:
    return stage == "r16"


def _stage_gap_damping_factor(stage: str | None, params: StrengthXgParams) -> float:
    factor = 1.0
    if _is_knockout_stage(stage) and params.knockout_gap_damping < 1.0:
        factor = min(factor, params.knockout_gap_damping)
    if _is_r16_stage(stage) and params.r16_gap_damping < 1.0:
        factor = min(factor, params.r16_gap_damping)
    return factor


def _stage_favorite_boost_damping_factor(stage: str | None, params: StrengthXgParams) -> float:
    factor = 1.0
    if _is_knockout_stage(stage) and params.knockout_favorite_boost_damping < 1.0:
        factor = min(factor, params.knockout_favorite_boost_damping)
    if _is_r16_stage(stage) and params.r16_favorite_boost_damping < 1.0:
        factor = min(factor, params.r16_favorite_boost_damping)
    return factor


def _apply_gap_damping_to_sides(
    home_xg: float, away_xg: float, damping: float
) -> tuple[float, float]:
    """Move favorite share toward 0.5 by damping factor (probe-only semantics)."""
    if damping >= 1.0:
        return home_xg, away_xg
    total = home_xg + away_xg
    if total <= 0:
        return home_xg, away_xg
    share = home_xg / total
    new_share = 0.5 + (share - 0.5) * damping
    return total * new_share, total * (1.0 - new_share)


def _apply_favorite_share_boost(
    home_xg: float,
    away_xg: float,
    params: StrengthXgParams,
    *,
    boost_scale: float = 1.0,
) -> tuple[float, float, bool]:
    """Redistribute xG toward favorite while keeping total approximately stable."""
    boost = params.favorite_share_boost * boost_scale
    if boost <= 0:
        return home_xg, away_xg, False
    total = home_xg + away_xg
    if total <= 0:
        return home_xg, away_xg, False
    if home_xg >= away_xg:
        fav_xg, dog_xg, home_is_fav = home_xg, away_xg, True
    else:
        fav_xg, dog_xg, home_is_fav = away_xg, home_xg, False
    fav_share = fav_xg / total
    if fav_share < params.favorite_share_boost_start:
        return home_xg, away_xg, False
    new_share = min(fav_share + boost, params.max_favorite_share)
    new_fav = round(total * new_share, 4)
    new_dog = round(total * (1.0 - new_share), 4)
    if home_is_fav:
        return new_fav, new_dog, True
    return new_dog, new_fav, True


def _clamp_side(value: float, params: StrengthXgParams, warnings: list[str]) -> float:
    if value < params.min_side:
        warnings.append("side_cap_applied")
        return params.min_side
    if value > params.max_side:
        warnings.append("side_cap_applied")
        return params.max_side
    return value


def _apply_total_bounds(
    home_xg: float,
    away_xg: float,
    params: StrengthXgParams,
) -> tuple[float, float, bool, float | None]:
    total = home_xg + away_xg
    if total > params.max_total and total > 0:
        factor = params.max_total / total
        return round(home_xg * factor, 2), round(away_xg * factor, 2), True, factor
    if total < params.min_total and total > 0:
        factor = params.min_total / total
        return round(home_xg * factor, 2), round(away_xg * factor, 2), True, factor
    return round(home_xg, 2), round(away_xg, 2), False, None


def generate_strength_based_xg(
    signals: StrengthSignals,
    params: StrengthXgParams,
    *,
    baseline_home_xg: float | None = None,
    baseline_away_xg: float | None = None,
    match_stage: str | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """Return (home_xg, away_xg, diagnostics). Sides computed first; total is their sum."""
    warnings: list[str] = []
    fallback_used = False
    fallback_reason: str | None = None

    ref_power = (signals.home_power + signals.away_power) / 2.0
    ref_elo = (signals.home_elo + signals.away_elo) / 2.0
    pop = signals.population_powers

    home_overall = _power_signal(
        signals.home_power, signals.home_elo, ref_power=ref_power, ref_elo=ref_elo, population=pop
    )
    away_overall = _power_signal(
        signals.away_power, signals.away_elo, ref_power=ref_power, ref_elo=ref_elo, population=pop
    )

    home_attack, miss_ha = _attack_defense_signal(signals.home_attack)
    away_attack, miss_aa = _attack_defense_signal(signals.away_attack)
    home_defense, miss_hd = _attack_defense_signal(signals.home_defense)
    away_defense, miss_ad = _attack_defense_signal(signals.away_defense)

    if params.use_attack_defense and (miss_ha or miss_aa or miss_hd or miss_ad):
        if not params.use_overall_power:
            fallback_used = True
            fallback_reason = "fallback_to_overall_power_only"
            warnings.append("fallback_to_overall_power_only")

    gap = signed_mismatch_gap(
        signals.home_power,
        signals.away_power,
        0.0,
        home_elo=signals.home_elo,
        away_elo=signals.away_elo,
    )
    gap_home = _clip_signal(gap / 400.0) * params.power_gap_multiplier
    gap_away = -gap_home

    home_log = _side_log_xg(
        attack_sig=home_attack,
        defense_opp_sig=away_defense,
        overall_sig=home_overall,
        opponent_overall_sig=away_overall,
        gap_sig=gap_home,
        params=params,
        warnings=warnings,
    )
    away_log = _side_log_xg(
        attack_sig=away_attack,
        defense_opp_sig=home_defense,
        overall_sig=away_overall,
        opponent_overall_sig=home_overall,
        gap_sig=gap_away,
        params=params,
        warnings=warnings,
    )

    home_raw = math.exp(home_log)
    away_raw = math.exp(away_log)
    home_clamped = _clamp_side(home_raw, params, warnings)
    away_clamped = _clamp_side(away_raw, params, warnings)
    gap_damp = _stage_gap_damping_factor(match_stage, params)
    if gap_damp < 1.0:
        home_clamped, away_clamped = _apply_gap_damping_to_sides(home_clamped, away_clamped, gap_damp)
        warnings.append("stage_gap_damping_applied")
    fav_damp = _stage_favorite_boost_damping_factor(match_stage, params)
    home_clamped, away_clamped, boost_applied = _apply_favorite_share_boost(
        home_clamped, away_clamped, params, boost_scale=fav_damp
    )
    if boost_applied:
        warnings.append("favorite_share_boost_applied")
    home_final, away_final, total_cap, scale_factor = _apply_total_bounds(
        home_clamped, away_clamped, params
    )
    if total_cap:
        warnings.append("total_cap_applied")

    data_signals: list[str] = []
    if params.use_overall_power:
        data_signals.append("overall_power")
    if params.use_attack_defense:
        data_signals.extend(["attack", "defense"])
    if params.use_gap:
        data_signals.append("power_gap")

    diag: dict[str, Any] = {
        "enabled": True,
        "generator_version": GENERATOR_VERSION,
        "uses_global_xg_avg": False,
        "uses_fixed_2_6": False,
        "data_signals_used": data_signals,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "home_team": signals.home_team,
        "away_team": signals.away_team,
        "home_side": {
            "raw_attack_signal": signals.home_attack,
            "raw_defense_signal": signals.home_defense,
            "raw_overall_power": signals.home_power,
            "normalized_attack_signal": home_attack,
            "normalized_defense_signal": home_defense,
            "normalized_overall_signal": home_overall,
            "opponent_defense_signal": away_defense,
            "opponent_overall_signal": away_overall,
            "side_xg_raw": round(home_raw, 4),
            "side_xg_clamped": round(home_clamped, 4),
            "side_xg_final": home_final,
        },
        "away_side": {
            "raw_attack_signal": signals.away_attack,
            "raw_defense_signal": signals.away_defense,
            "raw_overall_power": signals.away_power,
            "normalized_attack_signal": away_attack,
            "normalized_defense_signal": away_defense,
            "normalized_overall_signal": away_overall,
            "opponent_defense_signal": home_defense,
            "opponent_overall_signal": home_overall,
            "side_xg_raw": round(away_raw, 4),
            "side_xg_clamped": round(away_clamped, 4),
            "side_xg_final": away_final,
        },
        "parameters": {
            "scale": params.scale,
            "attack_weight": params.attack_weight,
            "defense_weight": params.defense_weight,
            "overall_weight": params.overall_weight,
            "opponent_overall_weight": params.opponent_overall_weight,
            "gap_weight": params.gap_weight,
            "min_side": params.min_side,
            "max_side": params.max_side,
            "min_total": params.min_total,
            "max_total": params.max_total,
            "signal_mode": params.signal_mode,
            "skip_blowout": params.skip_blowout,
        },
        "total": {
            "home_xg": home_final,
            "away_xg": away_final,
            "total_xg": round(home_final + away_final, 3),
            "total_cap_applied": total_cap,
            "total_scale_factor_if_capped": scale_factor,
        },
        "comparison_to_current_baseline": None,
        "warnings": sorted(set(warnings + ["no_global_xg_avg_used"])),
    }

    if baseline_home_xg is not None and baseline_away_xg is not None:
        diag["comparison_to_current_baseline"] = {
            "current_baseline_home_xg": baseline_home_xg,
            "current_baseline_away_xg": baseline_away_xg,
            "current_baseline_total_xg": round(baseline_home_xg + baseline_away_xg, 3),
            "delta_home_xg": round(home_final - baseline_home_xg, 3),
            "delta_away_xg": round(away_final - baseline_away_xg, 3),
            "delta_total_xg": round(home_final + away_final - baseline_home_xg - baseline_away_xg, 3),
        }

    return home_final, away_final, diag


def build_strength_xg_grid() -> list[tuple[str, StrengthXgParams]]:
    """Conservative offline grid (families A–F). Scale is internal to strength_v1."""
    out: list[tuple[str, StrengthXgParams]] = []

    # A — overall_power_only_conservative
    for scale, ow, gw, mx in product(
        (-0.7, -0.5, -0.3),
        (0.05, 0.10, 0.15),
        (0.05, 0.10),
        (2.60,),
    ):
        name = f"A_s{scale}_ow{ow}_gw{gw}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=ow,
                    opponent_overall_weight=ow * 0.8,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_side=mx,
                    max_total=3.60,
                    signal_mode="overall_power_only",
                ),
            )
        )

    # B — overall_power_only_medium
    for scale, ow, gw in product((-0.5, -0.3, -0.1), (0.10, 0.20, 0.30), (0.10, 0.20)):
        name = f"B_s{scale}_ow{ow}_gw{gw}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=ow,
                    opponent_overall_weight=ow * 0.75,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_side=3.00,
                    max_total=4.00,
                    signal_mode="overall_power_only",
                ),
            )
        )

    # C — attack_defense_balanced
    for aw, dw, ow in product((0.10, 0.20, 0.30), (0.10, 0.20, 0.30), (0.0, 0.10)):
        name = f"C_aw{aw}_dw{dw}_ow{ow}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=-0.4,
                    attack_weight=aw,
                    defense_weight=dw,
                    overall_weight=ow,
                    opponent_overall_weight=ow,
                    gap_weight=0.10 if ow == 0 else 0.0,
                    use_attack_defense=True,
                    max_total=3.80,
                    signal_mode="attack_defense_balanced",
                ),
            )
        )

    # D — attack_defense_conservative
    for aw, dw, mt in product((0.05, 0.10, 0.15), (0.05, 0.10, 0.15), (3.20, 3.50, 3.80)):
        name = f"D_aw{aw}_dw{dw}_mt{mt}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=-0.5,
                    attack_weight=aw,
                    defense_weight=dw,
                    overall_weight=0.08,
                    opponent_overall_weight=0.08,
                    gap_weight=0.05,
                    max_total=mt,
                    signal_mode="attack_defense_conservative",
                ),
            )
        )

    # E — no_blowout_total_inflation
    for scale, ow in product((-0.6, -0.4, -0.2), (0.10, 0.15, 0.20)):
        name = f"E_nb_s{scale}_ow{ow}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=ow,
                    opponent_overall_weight=ow * 0.8,
                    gap_weight=0.08,
                    use_attack_defense=False,
                    skip_blowout=True,
                    max_total=3.40,
                    signal_mode="no_blowout",
                ),
            )
        )

    # F — side_distribution_only (gap shapes sides, low overall weight)
    for scale, gw in product((-0.5, -0.3), (0.15, 0.25, 0.35)):
        name = f"F_s{scale}_gw{gw}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=0.05,
                    opponent_overall_weight=0.05,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_total=3.50,
                    signal_mode="side_distribution_only",
                ),
            )
        )

    return out


def build_refinement_scale_grid() -> list[tuple[str, StrengthXgParams]]:
    """P1.7B.1 — targeted scale sweep around B_s-0.1_ow0.1_gw0.2 weights."""
    base_ow, base_gw = 0.10, 0.20
    scales = (-0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
    out: list[tuple[str, StrengthXgParams]] = []
    for scale in scales:
        name = f"R1_scale{scale:+.2f}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=base_ow,
                    opponent_overall_weight=base_ow * 0.75,
                    gap_weight=base_gw,
                    use_attack_defense=False,
                    max_side=3.00,
                    max_total=4.00,
                    signal_mode="scale_recovery",
                ),
            )
        )
    return out


def build_refinement_favorite_grid() -> list[tuple[str, StrengthXgParams]]:
    """P1.7B.1 — favorite separation without blind total inflation."""
    scales = (0.00, 0.05, 0.10, 0.15)
    gap_weights = (0.20, 0.30, 0.40, 0.50, 0.60)
    overall_weights = (0.10, 0.20, 0.30, 0.40)
    opp_weights = (0.05, 0.10, 0.20, 0.30)
    attack_weights = (0.00, 0.10, 0.20)
    defense_weights = (0.00, 0.10, 0.20)
    out: list[tuple[str, StrengthXgParams]] = []
    # gap + overall combos at moderate scale
    for scale, gw, ow in product(scales, gap_weights, overall_weights):
        name = f"R2_s{scale}_gw{gw}_ow{ow}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=ow,
                    opponent_overall_weight=ow * 0.75,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_side=3.00,
                    max_total=3.80,
                    signal_mode="scale_plus_gap",
                ),
            )
        )
    # limited attack/defense at scale 0.05
    for aw, dw, oow in product(attack_weights, defense_weights, opp_weights):
        if aw == 0 and dw == 0:
            continue
        name = f"R2_ad_aw{aw}_dw{dw}_oow{oow}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=0.05,
                    attack_weight=aw,
                    defense_weight=dw,
                    overall_weight=0.10,
                    opponent_overall_weight=oow,
                    gap_weight=0.30,
                    use_attack_defense=True,
                    max_side=2.80,
                    max_total=3.50,
                    signal_mode="attack_defense_limited",
                ),
            )
        )
    return out


def build_refinement_families_grid() -> list[tuple[str, StrengthXgParams]]:
    """P1.7B.1 candidate families A–E."""
    out: list[tuple[str, StrengthXgParams]] = []

    # A — scale_only_recovery
    for scale in (-0.05, 0.00, 0.05, 0.10, 0.15, 0.20):
        name = f"P1A_scale{scale:+.2f}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=0.10,
                    opponent_overall_weight=0.075,
                    gap_weight=0.20,
                    use_attack_defense=False,
                    max_side=3.00,
                    max_total=4.00,
                    signal_mode="scale_only_recovery",
                ),
            )
        )

    # B — scale_plus_gap
    for scale, gw, ow in product((0.00, 0.05, 0.10, 0.15), (0.20, 0.35, 0.50), (0.10, 0.20, 0.30)):
        name = f"P1B_s{scale}_gw{gw}_ow{ow}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=ow,
                    opponent_overall_weight=ow * 0.7,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_side=3.00,
                    max_total=3.80,
                    signal_mode="scale_plus_gap",
                ),
            )
        )

    # C — share_stronger_total_safe
    for scale, gw in product((0.05, 0.10), (0.35, 0.50, 0.60)):
        name = f"P1C_s{scale}_gw{gw}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=0.08,
                    opponent_overall_weight=0.12,
                    gap_weight=gw,
                    use_attack_defense=False,
                    max_side=2.80,
                    max_total=3.40,
                    signal_mode="share_stronger_total_safe",
                ),
            )
        )

    # D — conservative_total_window
    for scale, mn, mx, ms in product(
        (0.00, 0.05, 0.10),
        (1.60, 1.80),
        (3.20, 3.60),
        (2.60, 3.00),
    ):
        name = f"P1D_s{scale}_mn{mn}_mx{mx}_ms{ms}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    overall_weight=0.12,
                    opponent_overall_weight=0.09,
                    gap_weight=0.25,
                    use_attack_defense=False,
                    min_total=mn,
                    max_total=mx,
                    max_side=ms,
                    signal_mode="conservative_total_window",
                ),
            )
        )

    # E — attack_defense_limited
    for scale, aw, dw in product((0.00, 0.05, 0.10), (0.05, 0.10, 0.20), (0.05, 0.10, 0.20)):
        name = f"P1E_s{scale}_aw{aw}_dw{dw}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=scale,
                    attack_weight=aw,
                    defense_weight=dw,
                    overall_weight=0.08,
                    opponent_overall_weight=0.08,
                    gap_weight=0.20,
                    use_attack_defense=True,
                    max_side=2.80,
                    max_total=3.50,
                    signal_mode="attack_defense_limited",
                ),
            )
        )

    return out


def _params_key(p: StrengthXgParams) -> tuple:
    return (
        round(p.scale, 4),
        round(p.attack_weight, 4),
        round(p.defense_weight, 4),
        round(p.overall_weight, 4),
        round(p.opponent_overall_weight, 4),
        round(p.gap_weight, 4),
        p.use_attack_defense,
        round(p.min_side, 2),
        round(p.max_side, 2),
        round(p.min_total, 2),
        round(p.max_total, 2),
        p.skip_blowout,
        round(p.favorite_share_boost, 4),
        round(p.favorite_share_boost_start, 4),
        round(p.max_favorite_share, 4),
        round(p.knockout_gap_damping, 4),
        round(p.knockout_favorite_boost_damping, 4),
        round(p.r16_gap_damping, 4),
        round(p.r16_favorite_boost_damping, 4),
        round(p.power_gap_multiplier, 4),
    )


def merge_unique_grids(*grids: list[tuple[str, StrengthXgParams]]) -> list[tuple[str, StrengthXgParams]]:
    """Deduplicate candidates by parameter tuple; keep first name."""
    seen: set[tuple] = set()
    out: list[tuple[str, StrengthXgParams]] = []
    for grid in grids:
        for name, params in grid:
            key = _params_key(params)
            if key in seen:
                continue
            seen.add(key)
            out.append((name, params))
    return out


def build_p17b1_full_grid() -> list[tuple[str, StrengthXgParams]]:
    """Original 96-grid plus P1.7B.1 refinement grids (deduplicated)."""
    return merge_unique_grids(
        build_strength_xg_grid(),
        build_refinement_scale_grid(),
        build_refinement_favorite_grid(),
        build_refinement_families_grid(),
    )


def p1c_reference_params() -> StrengthXgParams:
    """P1.7B.1 best composite candidate."""
    return StrengthXgParams(
        name="P1C_s0.05_gw0.6",
        scale=0.05,
        overall_weight=0.08,
        opponent_overall_weight=0.12,
        gap_weight=0.60,
        use_attack_defense=False,
        max_side=2.80,
        max_total=3.40,
        signal_mode="share_stronger_total_safe",
    )


P1C2_SHADOW_NAME = "P1C2_fav_b0.06_st0.58_mx0.68"


def p1c2_shadow_params() -> StrengthXgParams:
    """P1.7B.2 best shadow candidate — preserved for P1.7B.3 diagnostics."""
    base = p1c_reference_params()
    return StrengthXgParams(
        name=P1C2_SHADOW_NAME,
        scale=base.scale,
        overall_weight=base.overall_weight,
        opponent_overall_weight=base.opponent_overall_weight,
        gap_weight=base.gap_weight,
        use_attack_defense=base.use_attack_defense,
        max_side=base.max_side,
        max_total=base.max_total,
        signal_mode=base.signal_mode,
        favorite_share_boost=0.06,
        favorite_share_boost_start=0.58,
        max_favorite_share=0.68,
    )


def _p1c_base_kwargs(
    *,
    scale: float,
    gap_weight: float,
    overall_weight: float,
    opponent_overall_weight: float,
    favorite_share_boost: float = 0.0,
    favorite_share_boost_start: float = 0.55,
    max_favorite_share: float = 0.72,
) -> dict[str, Any]:
    return dict(
        scale=scale,
        overall_weight=overall_weight,
        opponent_overall_weight=opponent_overall_weight,
        gap_weight=gap_weight,
        use_attack_defense=False,
        max_side=2.80,
        max_total=3.40,
        signal_mode="share_stronger_total_safe",
        favorite_share_boost=favorite_share_boost,
        favorite_share_boost_start=favorite_share_boost_start,
        max_favorite_share=max_favorite_share,
    )


def build_p1c_narrow_grid() -> list[tuple[str, StrengthXgParams]]:
    """P1.7B.2 narrow grid around P1C reference."""
    scales = (0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12)
    gap_weights = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
    overall_weights = (0.04, 0.06, 0.08, 0.10, 0.12)
    opp_weights = (0.05, 0.10, 0.12, 0.14)
    out: list[tuple[str, StrengthXgParams]] = []
    for scale, gw, ow, oow in product(scales, gap_weights, overall_weights, opp_weights):
        name = f"P1C2_s{scale}_gw{gw}_ow{ow}_oow{oow}"
        out.append(
            (
                name,
                StrengthXgParams(name=name, **_p1c_base_kwargs(
                    scale=scale, gap_weight=gw, overall_weight=ow, opponent_overall_weight=oow
                )),
            )
        )
    return out


def build_p1c_favorite_calibration_variants(
    base: StrengthXgParams | None = None,
) -> list[tuple[str, StrengthXgParams]]:
    """Favorite-share boost variants on a P1C base configuration."""
    base = base or p1c_reference_params()
    boosts = (0.00, 0.02, 0.04, 0.06)
    starts = (0.52, 0.55, 0.58)
    max_shares = (0.68, 0.70, 0.72)
    out: list[tuple[str, StrengthXgParams]] = []
    for boost, start, mx in product(boosts, starts, max_shares):
        if boost == 0.0 and (start != 0.55 or mx != 0.72):
            continue
        name = f"P1C2_fav_b{boost}_st{start}_mx{mx}"
        out.append(
            (
                name,
                StrengthXgParams(
                    name=name,
                    scale=base.scale,
                    overall_weight=base.overall_weight,
                    opponent_overall_weight=base.opponent_overall_weight,
                    gap_weight=base.gap_weight,
                    use_attack_defense=base.use_attack_defense,
                    max_side=base.max_side,
                    max_total=base.max_total,
                    signal_mode=base.signal_mode,
                    favorite_share_boost=boost,
                    favorite_share_boost_start=start,
                    max_favorite_share=mx,
                ),
            )
        )
    return out


def measure_scale_semantics_on_matches(
    matches: list[Any],
    *,
    scales: tuple[float, ...] = (-0.30, -0.10, 0.00, 0.05, 0.15, 0.30),
) -> dict[str, Any]:
    """Quick empirical check: does increasing scale raise avg total xG?"""
    from core.temporal_backtest import _resolve_snapshot_for_match, load_historical_matches, matches_before_target

    if not matches:
        return {"error": "no matches"}
    full = load_historical_matches("all")
    base_ow, base_gw = 0.10, 0.20
    by_scale: dict[str, list[float]] = {str(s): [] for s in scales}

    for match in matches[: min(20, len(matches))]:
        prior = matches_before_target(full, match)
        snap = _resolve_snapshot_for_match(
            match, full, dataset_key="copa2024", prior_mode="tournament_prior_file"
        )
        pop = [snap.get_team(t).internal_elo for t in snap.teams]
        sig = StrengthSignals(
            home_team=match.home_team,
            away_team=match.away_team,
            home_power=800.0,
            away_power=800.0,
            home_elo=snap.get_team(match.home_team).internal_elo,
            away_elo=snap.get_team(match.away_team).internal_elo,
            home_attack=snap.get_team(match.home_team).attack,
            home_defense=snap.get_team(match.home_team).defense,
            away_attack=snap.get_team(match.away_team).attack,
            away_defense=snap.get_team(match.away_team).defense,
            population_powers=pop,
        )
        for scale in scales:
            p = StrengthXgParams(
                name=f"probe_{scale}",
                scale=scale,
                overall_weight=base_ow,
                opponent_overall_weight=base_ow * 0.75,
                gap_weight=base_gw,
                use_attack_defense=False,
            )
            h, a, _ = generate_strength_based_xg(sig, p)
            by_scale[str(scale)].append(h + a)

    avgs = {k: round(sum(v) / len(v), 3) for k, v in by_scale.items() if v}
    ordered = [avgs[str(s)] for s in scales if str(s) in avgs]
    monotonic_increasing = all(ordered[i] <= ordered[i + 1] for i in range(len(ordered) - 1))
    return {
        "formula": "side_xg = exp(scale + weighted_signals)",
        "scale_increases_xg": monotonic_increasing,
        "avg_total_by_scale": avgs,
        "interpretation": (
            "Increasing scale raises average total xG (multiplicative in exp domain)."
            if monotonic_increasing
            else "Scale semantics non-monotonic on sample — inspect caps/clipping."
        ),
        "sample_matches": len(matches[: min(20, len(matches))]),
    }


def default_strength_xg_params() -> StrengthXgParams:
    """Production-shadow default (not grid-selected; offline validation picks best)."""
    import config as app_config

    return StrengthXgParams(
        name="default_env",
        scale=app_config.STRENGTH_XG_DEFAULT_SCALE,
        overall_weight=app_config.STRENGTH_XG_DEFAULT_OVERALL_WEIGHT,
        opponent_overall_weight=app_config.STRENGTH_XG_DEFAULT_OVERALL_WEIGHT * 0.8,
        gap_weight=app_config.STRENGTH_XG_DEFAULT_GAP_WEIGHT,
        use_attack_defense=app_config.STRENGTH_XG_USE_ATTACK_DEFENSE,
        use_overall_power=app_config.STRENGTH_XG_USE_OVERALL_POWER,
        min_side=app_config.STRENGTH_XG_MIN_SIDE,
        max_side=app_config.STRENGTH_XG_MAX_SIDE,
        min_total=app_config.STRENGTH_XG_MIN_TOTAL,
        max_total=app_config.STRENGTH_XG_MAX_TOTAL,
        signal_mode="default_env",
    )


def source_uses_global_xg_avg() -> bool:
    """Static audit — module must not import or read config.GLOBAL_XG_AVG."""
    import inspect

    module_src = inspect.getsource(__import__(__name__))
    return "GLOBAL_XG_AVG" in module_src or "config.GLOBAL_XG_AVG" in module_src
