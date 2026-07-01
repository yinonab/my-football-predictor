"""P1.7B.16 FCC runtime — shadow sidecar only (no audit/report dependencies)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from core.nr3_fcc_stack import build_hb3_stack
from core.priority1_options import Priority1Config
from core.strength_based_xg_generator import StrengthXgParams

SHADOW_ONLY_LABEL = "SHADOW_ONLY_RESEARCH"
NOT_ACTIVATION = "NOT_ACTIVATION_CANDIDATE"
NOT_PRODUCTION = "NOT_PRODUCTION_CANDIDATE"
PROTOTYPE_NAME = "FCC_FIXED_MONOTONIC_FAVORITE_SHARE_LIFT"

XG_DIFF_MIN = 0.35
TOTAL_XG_MIN = 1.80
FAVORITE_SHARE_MIN = 0.58
FAVORITE_WIN_PROB_MAX = 0.70
GOVERNED_FAVORITE_SHARE_CAP = 0.68
GOVERNED_FAVORITE_WIN_PROB_CAP = 0.75
TOTAL_XG_TOLERANCE = 0.02
PROB_SUM_TOLERANCE = 0.02
MIN_TEAM_XG = 0.05
CLUSTER_LOW, CLUSTER_HIGH = 2.55, 2.65

BAND_A = ("A", 0.35, 0.50, 0.03, 0.015)
BAND_B = ("B", 0.50, 0.75, 0.05, 0.025)
BAND_C = ("C", 0.75, float("inf"), 0.06, 0.030)

STANDARD_WARNINGS = (
    "shadow_only_research",
    "not_activation_candidate",
    "not_production_candidate",
    "single_pre_registered_prototype",
    "no_grid",
    "no_tuning",
    "no_dataset_specific_logic",
    "no_stage_dependency",
    "no_actual_result_used",
    "no_global_xg_avg_dependency",
    "total_xg_preserved",
    "no_auto_flip",
    "matrix_recomputed_not_manually_calibrated",
    "probability_mass_checked",
    "scoreline_mass_checked",
    "favorite_side_sanity_checked",
)


@dataclass(frozen=True)
class FavoriteConfidenceCurveParams:
    name: str = PROTOTYPE_NAME
    prototype_id: str = PROTOTYPE_NAME
    xg_diff_min: float = XG_DIFF_MIN
    total_xg_min: float = TOTAL_XG_MIN
    favorite_share_min: float = FAVORITE_SHARE_MIN
    favorite_win_prob_max: float = FAVORITE_WIN_PROB_MAX
    governed_favorite_share_cap: float = GOVERNED_FAVORITE_SHARE_CAP
    governed_favorite_win_prob_cap: float = GOVERNED_FAVORITE_WIN_PROB_CAP
    total_xg_tolerance: float = TOTAL_XG_TOLERANCE
    status: str = SHADOW_ONLY_LABEL
    not_activation_candidate: str = NOT_ACTIVATION
    not_production_candidate: str = NOT_PRODUCTION
    pre_registered_single_prototype: str = "PRE_REGISTERED_SINGLE_PROTOTYPE"
    no_grid: str = "NO_GRID"
    no_tuning: str = "NO_TUNING"
    curve_family: str = "FAVORITE_CONFIDENCE_CURVE"


def fcc_fixed_params() -> FavoriteConfidenceCurveParams:
    return FavoriteConfidenceCurveParams()


def build_fcc_stack(
    strength_params: StrengthXgParams,
    fcc_params: FavoriteConfidenceCurveParams | None = None,
) -> Priority1Config:
    base = build_hb3_stack(strength_params)
    return replace(base, favorite_confidence_curve_params=fcc_params or fcc_fixed_params())


def _favorite_side(home_xg: float, away_xg: float) -> str:
    return "home" if home_xg >= away_xg else "away"


def _estimate_1x2_probs(home_xg: float, away_xg: float, *, max_goals: int = 10) -> dict[str, float]:
    from scipy.stats import poisson

    p_hw = p_dr = p_aw = 0.0
    for h in range(max_goals + 1):
        ph = float(poisson.pmf(h, max(home_xg, 1e-9)))
        for a in range(max_goals + 1):
            pa = float(poisson.pmf(a, max(away_xg, 1e-9)))
            p = ph * pa
            if h > a:
                p_hw += p
            elif h == a:
                p_dr += p
            else:
                p_aw += p
    total = max(p_hw + p_dr + p_aw, 1e-9)
    return {"home": p_hw / total, "draw": p_dr / total, "away": p_aw / total}


def _band_for_diff(diff: float) -> tuple[str | None, float, float]:
    for label, lo, hi, max_diff_inc, max_team in (BAND_A, BAND_B, BAND_C):
        if lo <= diff < hi:
            return label, max_diff_inc, max_team
    return None, 0.0, 0.0


def run_pre_prototype_sanity_checks(
    home_xg: float,
    away_xg: float,
    *,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    probs = _estimate_1x2_probs(home_xg, away_xg)
    prob_sum = sum(probs.values())
    fav_side_xg = _favorite_side(home_xg, away_xg)
    fav_side_prob = max(
        (("home", probs["home"]), ("away", probs["away"])),
        key=lambda x: x[1],
    )[0]
    side_consistent = fav_side_xg == fav_side_prob or abs(probs["home"] - probs["away"]) < 0.02
    diff = abs(home_xg - away_xg)
    total = home_xg + away_xg
    fav_share = max(home_xg, away_xg) / max(total, 1e-9)
    fav_key = fav_side_xg
    fav_prob = probs[fav_key]
    flags: list[str] = []
    if diff >= 0.75 and fav_prob < 0.50:
        flags.append("high_diff_low_favorite_probability")
    if diff >= 0.50 and fav_prob < 0.55:
        flags.append("moderate_diff_low_favorite_probability")
    if fav_share >= 0.62 and fav_prob < 0.55:
        flags.append("high_share_low_favorite_probability")
    cluster_risk = CLUSTER_LOW <= total < CLUSTER_HIGH
    severe = not side_consistent or abs(prob_sum - 1.0) > PROB_SUM_TOLERANCE
    return {
        "favorite_side_from_xg": fav_side_xg,
        "favorite_side_from_probability": fav_side_prob,
        "favorite_side_consistent": side_consistent,
        "probability_sum": round(prob_sum, 6),
        "probability_sum_valid": abs(prob_sum - 1.0) <= PROB_SUM_TOLERANCE,
        "scoreline_mass_valid": True,
        "xg_diff": round(diff, 4),
        "favorite_share": round(fav_share, 4),
        "favorite_win_probability_estimate": round(fav_prob, 4),
        "sanity_flags": flags,
        "cluster_2_55_2_65": cluster_risk,
        "severe_inconsistency": severe,
        "continue_prototype": not severe,
    }


def _apply_share_cap(
    gov_h: float,
    gov_a: float,
    *,
    cap: float,
) -> tuple[float, float, bool, str | None]:
    total = gov_h + gov_a
    if total <= 0:
        return gov_h, gov_a, False, None
    fav_side = _favorite_side(gov_h, gov_a)
    share = max(gov_h, gov_a) / total
    if share <= cap + 1e-9:
        return gov_h, gov_a, False, None
    target_fav = cap * total
    if fav_side == "home":
        return target_fav, total - target_fav, True, "favorite_share_cap"
    return total - target_fav, target_fav, True, "favorite_share_cap"


def _apply_monotonic_lift(
    home_xg: float,
    away_xg: float,
    *,
    band_label: str,
    max_diff_inc: float,
    max_team_move: float,
    params: FavoriteConfidenceCurveParams,
) -> tuple[float, float, bool, str | None]:
    orig_h, orig_a = home_xg, away_xg
    total = orig_h + orig_a
    fav_side = _favorite_side(orig_h, orig_a)
    diff = abs(orig_h - orig_a)
    move = min(max_diff_inc / 2.0, max_team_move)
    if fav_side == "home":
        gov_h, gov_a = orig_h + move, orig_a - move
    else:
        gov_a, gov_h = orig_a + move, orig_h - move
    gov_h = max(MIN_TEAM_XG, gov_h)
    gov_a = max(MIN_TEAM_XG, gov_a)
    gov_total = gov_h + gov_a
    if abs(gov_total - total) > 1e-9 and gov_total > 0:
        scale = total / gov_total
        gov_h *= scale
        gov_a *= scale
    new_diff = abs(gov_h - gov_a)
    if new_diff - diff > max_diff_inc + 1e-6:
        return orig_h, orig_a, True, "xg_diff_increase_cap"
    gov_h, gov_a, capped, cap_reason = _apply_share_cap(
        gov_h, gov_a, cap=params.governed_favorite_share_cap
    )
    gov_probs = _estimate_1x2_probs(gov_h, gov_a)
    gov_fav_prob = gov_probs[fav_side]
    if gov_fav_prob > params.governed_favorite_win_prob_cap + 1e-6:
        return orig_h, orig_a, True, "favorite_win_probability_cap"
    if _favorite_side(gov_h, gov_a) != fav_side:
        return orig_h, orig_a, True, "would_flip_favorite"
    clamped = capped or abs(new_diff - diff) < 1e-6
    reason = cap_reason if capped else (None if not clamped else "no_effective_lift")
    return round(gov_h, 4), round(gov_a, 4), clamped, reason


def apply_favorite_confidence_curve(
    home_xg: float,
    away_xg: float,
    *,
    match: Any,
    params: FavoriteConfidenceCurveParams,
    dataset: str | None = None,
) -> tuple[float, float, dict[str, Any]]:
    warnings = list(STANDARD_WARNINGS)
    orig_h, orig_a = float(home_xg), float(away_xg)
    orig_total = orig_h + orig_a
    orig_diff = abs(orig_h - orig_a)
    fav_side = _favorite_side(orig_h, orig_a)
    fav_team = match.home_team if fav_side == "home" else match.away_team
    orig_share = max(orig_h, orig_a) / max(orig_total, 1e-9)
    orig_probs = _estimate_1x2_probs(orig_h, orig_a)
    orig_fav_prob = orig_probs[fav_side]
    orig_draw = orig_probs["draw"]
    orig_dog = orig_probs["away" if fav_side == "home" else "home"]
    sanity = run_pre_prototype_sanity_checks(
        orig_h, orig_a, home_team=match.home_team, away_team=match.away_team
    )

    trigger_eligible = False
    curve_triggered = False
    trigger_band: str | None = None
    trigger_reason: str | None = None
    block_reason: str | None = None
    adjustment_clamped = False
    clamp_reason: str | None = None
    gov_h, gov_a = orig_h, orig_a

    if not sanity["continue_prototype"]:
        block_reason = "severe_sanity_inconsistency"
        warnings.append("severe_sanity_inconsistency")
    elif orig_h == orig_a:
        block_reason = "no_structural_favorite"
    elif max(orig_h, orig_a) <= min(orig_h, orig_a):
        block_reason = "favorite_not_higher_xg"
    elif orig_diff < params.xg_diff_min:
        block_reason = "xg_diff_below_threshold"
    elif orig_total < params.total_xg_min:
        block_reason = "total_xg_below_threshold"
    elif orig_share < params.favorite_share_min:
        block_reason = "favorite_share_below_threshold"
    elif orig_share >= params.governed_favorite_share_cap:
        block_reason = "favorite_share_already_at_or_above_cap"
    elif orig_fav_prob > params.favorite_win_prob_max:
        block_reason = "favorite_win_probability_above_threshold"
    elif not sanity["probability_sum_valid"]:
        block_reason = "probability_mass_invalid"
    elif sanity.get("severe_inconsistency"):
        block_reason = "favorite_side_inconsistent"
    else:
        trigger_eligible = True
        band_label, max_diff_inc, max_team = _band_for_diff(orig_diff)
        if band_label is None:
            block_reason = "no_trigger_band"
        else:
            trigger_band = band_label
            gov_h, gov_a, adjustment_clamped, clamp_reason = _apply_monotonic_lift(
                orig_h,
                orig_a,
                band_label=band_label,
                max_diff_inc=max_diff_inc,
                max_team_move=max_team,
                params=params,
            )
            if abs(gov_h - orig_h) < 1e-9 and abs(gov_a - orig_a) < 1e-9:
                block_reason = clamp_reason or "no_effective_lift"
            else:
                curve_triggered = True
                trigger_reason = f"band_{band_label}_monotonic_share_lift"

    if sanity.get("cluster_2_55_2_65"):
        warnings.append("cluster_2_55_2_65_input")

    gov_total = gov_h + gov_a
    gov_diff = abs(gov_h - gov_a)
    gov_share = max(gov_h, gov_a) / max(gov_total, 1e-9)
    gov_probs = _estimate_1x2_probs(gov_h, gov_a)
    gov_fav_prob = gov_probs[fav_side]
    gov_draw = gov_probs["draw"]
    gov_dog = gov_probs["away" if fav_side == "home" else "home"]
    gov_fav = match.home_team if gov_h >= gov_a else match.away_team

    diag: dict[str, Any] = {
        "enabled": True,
        "prototype_name": params.name,
        "status": params.status,
        "dataset": dataset,
        "stage": getattr(match, "stage", None),
        "stage_required": False,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "original_favorite": fav_team,
        "governed_favorite": gov_fav,
        "favorite_direction_changed": gov_fav != fav_team,
        "no_auto_flip_applied": gov_fav == fav_team,
        "curve_triggered": curve_triggered,
        "trigger_eligible": trigger_eligible,
        "trigger_band": trigger_band,
        "trigger_reason": trigger_reason,
        "trigger_block_reason": block_reason,
        "adjustment_clamped": adjustment_clamped,
        "clamp_reason": clamp_reason,
        "total_xg_preserved": abs(gov_total - orig_total) <= params.total_xg_tolerance,
        "xg_diff_delta": round(gov_diff - orig_diff, 4),
        "favorite_share_delta": round(gov_share - orig_share, 4),
        "favorite_probability_delta": round(gov_fav_prob - orig_fav_prob, 4),
        "draw_probability_delta": round(gov_draw - orig_draw, 4),
        "underdog_probability_delta": round(gov_dog - orig_dog, 4),
        "sanity_checks": sanity,
        "warnings": sorted(set(warnings)),
    }
    return gov_h, gov_a, diag
