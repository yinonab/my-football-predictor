"""Experimental matchup-relative xG candidate — user-selectable via xg_model_variant."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from core.blowout import BlowoutAdjustment
from core.matchup_feature_vector import MatchupFeatureVector, build_matchup_feature_vector
from core.nr3_finalist_spec import nr3_finalist_spec
from core.strength_based_xg_generator import StrengthSignals, generate_strength_based_xg

MATCHUP_RELATIVE_V1_MODEL_VERSION = "matchup_relative_xg_v1"
MATCHUP_RELATIVE_V1_ACTIVE_SOURCE = "matchup_relative_v1"

FUSION_IGNORE_REASON = "Goliath/Fusion is not calibrated for Matchup Relative v1 yet"
LARGE_DELTA_PP_THRESHOLD = 10.0
GAP_STRONG_FAVORITE = 250.0
ATTACK_WEAK = 0.20
DEF_STRONG = 0.70
SUSPICIOUS_HIGH_UD_XG = 0.75
MAHER_CONFIDENCE_TAU = 0.50

FAVORITE_WEIGHTS = {
    "strength": 0.35,
    "attack_vs_defense": 0.30,
    "opponent_defense": 0.15,
    "maher": 0.15,
    "context": 0.05,
}
UNDERDOG_WEIGHTS = {
    "strength": 0.25,
    "attack_vs_defense": 0.40,
    "opponent_defense": 0.20,
    "maher": 0.10,
    "context": 0.05,
}

ABSOLUTE_MIN_XG = 0.12
ABSOLUTE_MAX_XG = 3.50
MIN_TOTAL_GOALS = 1.80
MAX_TOTAL_GOALS = 4.50


def normalize_xg_model_variant(value: str | None) -> str:
    raw = (value or "nr3_fcc").strip().lower()
    if raw == MATCHUP_RELATIVE_V1_ACTIVE_SOURCE:
        return MATCHUP_RELATIVE_V1_ACTIVE_SOURCE
    return "nr3_fcc"


def _favorite_from_probs(probs: dict[str, float]) -> str:
    key = max(probs, key=probs.get)
    return {"home_win": "home", "draw": "draw", "away_win": "away"}.get(key, "home")


def build_matchup_shift_reason_codes(
    *,
    mr_home_xg: float,
    mr_away_xg: float,
    mr_probs: dict[str, float],
    feature_vector_summary: dict[str, Any],
    nr3_home_xg: float | None = None,
    nr3_away_xg: float | None = None,
    nr3_probs: dict[str, float] | None = None,
) -> list[str]:
    codes = ["model_variant_experimental"]
    edges = feature_vector_summary.get("attack_vs_defense_edges", {})
    fav_edge = edges.get("favorite")
    ud_edge = edges.get("underdog")
    if fav_edge is not None and float(fav_edge) < 0.35:
        codes.append("favorite_attack_edge_low")
    if ud_edge is not None and float(ud_edge) >= 0.45:
        codes.append("underdog_attack_edge_high")
    if edges:
        codes.append("attack_defense_edge_driver")

    if nr3_probs is not None and nr3_home_xg is not None and nr3_away_xg is not None:
        if _favorite_from_probs(mr_probs) != _favorite_from_probs(nr3_probs):
            codes.extend(
                ["MATCHUP_RELATIVE_LARGE_DELTA_FROM_NR3", "large_delta_from_nr3"]
            )
        else:
            for key in ("home_win", "draw", "away_win"):
                if abs(float(mr_probs[key]) - float(nr3_probs[key])) >= LARGE_DELTA_PP_THRESHOLD:
                    codes.extend(
                        ["MATCHUP_RELATIVE_LARGE_DELTA_FROM_NR3", "large_delta_from_nr3"]
                    )
                    break

    return sorted(set(codes))


def build_matchup_relative_xg_breakdown(
    *,
    final_home_xg: float,
    final_away_xg: float,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    components = diagnostics.get("components") or {}
    adaptive = diagnostics.get("adaptive_floor_details") or {}
    feature_summary = diagnostics.get("feature_vector_summary") or {}
    home_floor = adaptive.get("home") or {}
    away_floor = adaptive.get("away") or {}
    suppression = diagnostics.get("suppression_applied") or []
    return {
        "base_home_xg": round(float(components.get("home_raw", home_floor.get("raw_xg", 0.0))), 2),
        "base_away_xg": round(float(components.get("away_raw", away_floor.get("raw_xg", 0.0))), 2),
        "final_home_xg": round(float(final_home_xg), 2),
        "final_away_xg": round(float(final_away_xg), 2),
        "attack_defense_edges": diagnostics.get("attack_vs_defense_edges")
        or components.get("attack_vs_defense_edges"),
        "adaptive_floor": adaptive,
        "weak_underdog_suppression": suppression,
        "weak_underdog_suppression_applied": "WEAK_UNDERDOG_SUPPRESSION" in suppression,
        "total_goals_guard": diagnostics.get("total_goals_guard"),
        "total_goals_guard_applied": bool(
            (diagnostics.get("total_goals_guard") or {}).get("action") not in (None, "none")
        ),
        "reason_codes": diagnostics.get("reason_codes") or [],
        "favorite_side": feature_summary.get("favorite_side"),
        "underdog_side": feature_summary.get("underdog_side"),
        "confidence": diagnostics.get("confidence"),
    }


@dataclass
class MatchupRelativeXgV1Result:
    home_xg: float
    away_xg: float
    components: dict[str, Any]
    suppression_applied: list[str] = field(default_factory=list)
    confidence: float = 0.0
    candidate_version: str = MATCHUP_RELATIVE_V1_MODEL_VERSION
    feature_vector_summary: dict[str, Any] = field(default_factory=dict)
    adaptive_floor_details: dict[str, Any] = field(default_factory=dict)
    total_goals_guard: dict[str, Any] = field(default_factory=dict)

    def diagnostics_payload(self) -> dict[str, Any]:
        return {
            "active_xg_source": MATCHUP_RELATIVE_V1_ACTIVE_SOURCE,
            "model_variant": MATCHUP_RELATIVE_V1_ACTIVE_SOURCE,
            "home_xg_source": MATCHUP_RELATIVE_V1_ACTIVE_SOURCE,
            "away_xg_source": MATCHUP_RELATIVE_V1_ACTIVE_SOURCE,
            "candidate_version": self.candidate_version,
            "confidence": round(self.confidence, 4),
            "feature_vector_summary": self.feature_vector_summary,
            "components": self.components,
            "attack_vs_defense_edges": self.components.get("attack_vs_defense_edges", {}),
            "suppression_applied": list(self.suppression_applied),
            "adaptive_floor_details": self.adaptive_floor_details,
            "total_goals_guard": self.total_goals_guard,
        }


def _edge_to_xg_component(edge: float, *, base: float) -> float:
    return base * (0.55 + 0.90 * max(0.0, min(1.0, edge)))


def _opponent_defense_component(opponent_defense: float, *, base: float) -> float:
    return base * (1.05 - 0.40 * max(0.0, min(1.0, opponent_defense)))


def _adaptive_floor(
    raw_xg: float,
    *,
    attack_rating: float,
    opponent_defense: float,
    attack_edge: float,
    data_confidence: float,
    is_underdog: bool,
) -> tuple[float, dict[str, Any]]:
    base_min = 0.15
    attack_floor_scale = 0.35 if is_underdog else 0.25
    edge_bonus = max(0.0, attack_edge - 0.25) * 0.40
    elite_penalty = max(0.0, opponent_defense - 0.65) * 0.25
    confidence_factor = 0.65 + 0.35 * data_confidence

    adaptive = (
        base_min
        + attack_rating * attack_floor_scale
        + edge_bonus
        - elite_penalty
    ) * confidence_factor

    if is_underdog and attack_rating <= 0.15:
        adaptive = min(adaptive, 0.55)
    elif is_underdog and attack_rating <= ATTACK_WEAK:
        adaptive = min(adaptive, 0.65)

    floor = max(ABSOLUTE_MIN_XG, adaptive)
    applied = max(raw_xg, floor)
    return applied, {
        "raw_xg": round(raw_xg, 4),
        "adaptive_floor": round(floor, 4),
        "applied_xg": round(applied, 4),
        "attack_rating": round(attack_rating, 4),
        "opponent_defense": round(opponent_defense, 4),
        "attack_edge": round(attack_edge, 4),
        "is_underdog": is_underdog,
    }


def _weak_underdog_suppression_factor(
    *,
    power_gap_abs: float,
    underdog_attack: float,
    favorite_defense: float,
) -> float:
    gap_term = min(1.0, max(0.0, (power_gap_abs - GAP_STRONG_FAVORITE) / 200.0))
    attack_term = min(1.0, max(0.0, (ATTACK_WEAK - underdog_attack) / ATTACK_WEAK))
    defense_term = min(1.0, max(0.0, (favorite_defense - DEF_STRONG) / 0.30))
    severity = gap_term * attack_term * defense_term
    return 1.0 - 0.30 * severity


def _total_goals_guard(home_xg: float, away_xg: float) -> tuple[float, float, dict[str, Any]]:
    total = home_xg + away_xg
    before = {"home": round(home_xg, 4), "away": round(away_xg, 4), "total": round(total, 4)}
    if total < MIN_TOTAL_GOALS:
        scale = MIN_TOTAL_GOALS / max(total, 1e-6)
        home_xg *= scale
        away_xg *= scale
        action = "scale_up"
        target = MIN_TOTAL_GOALS
    elif total > MAX_TOTAL_GOALS:
        scale = MAX_TOTAL_GOALS / total
        home_xg *= scale
        away_xg *= scale
        action = "scale_down"
        target = MAX_TOTAL_GOALS
    else:
        action = "none"
        target = total
    return (
        round(home_xg, 2),
        round(away_xg, 2),
        {
            "before": before,
            "after": {
                "home": round(home_xg, 2),
                "away": round(away_xg, 2),
                "total": round(home_xg + away_xg, 2),
            },
            "action": action,
            "target_total": target,
        },
    )


def _compose_side_xg(
    *,
    strength_xg: float,
    attack_edge: float,
    opponent_defense: float,
    maher_xg: float,
    maher_confidence: float,
    context_delta_share: float,
    weights: dict[str, float],
    base: float,
) -> float:
    strength_component = strength_xg
    adv_def_component = _edge_to_xg_component(attack_edge, base=base)
    opp_def_component = _opponent_defense_component(opponent_defense, base=base)
    maher_component = maher_xg if maher_confidence >= MAHER_CONFIDENCE_TAU else 0.0
    maher_weight = weights["maher"] if maher_confidence >= MAHER_CONFIDENCE_TAU else 0.0
    redistributed = weights["strength"] + weights["attack_vs_defense"] + weights["opponent_defense"]
    active_weight = redistributed + maher_weight + weights["context"]
    if active_weight <= 0:
        active_weight = 1.0
    return (
        weights["strength"] * strength_component
        + weights["attack_vs_defense"] * adv_def_component
        + weights["opponent_defense"] * opp_def_component
        + maher_weight * maher_component
        + weights["context"] * context_delta_share
    ) / active_weight


def compute_matchup_relative_xg_v1(
    features: MatchupFeatureVector,
    *,
    avg_goals: float = 2.6,
    context_xg_delta: float = 0.0,
) -> MatchupRelativeXgV1Result:
    base = max(0.8, avg_goals / 2.0)
    context_share = context_xg_delta / 2.0

    home_is_favorite = features.favorite_side == "home"
    home_weights = FAVORITE_WEIGHTS if home_is_favorite else UNDERDOG_WEIGHTS
    away_weights = UNDERDOG_WEIGHTS if home_is_favorite else FAVORITE_WEIGHTS

    home_raw = _compose_side_xg(
        strength_xg=features.strength_home_xg,
        attack_edge=features.home_attack_vs_defense_edge,
        opponent_defense=features.away_defense_rating,
        maher_xg=features.maher_home_xg,
        maher_confidence=features.maher_confidence,
        context_delta_share=context_share,
        weights=home_weights,
        base=base,
    )
    away_raw = _compose_side_xg(
        strength_xg=features.strength_away_xg,
        attack_edge=features.away_attack_vs_defense_edge,
        opponent_defense=features.home_defense_rating,
        maher_xg=features.maher_away_xg,
        maher_confidence=features.maher_confidence,
        context_delta_share=context_share,
        weights=away_weights,
        base=base,
    )

    home_floor, home_floor_details = _adaptive_floor(
        home_raw,
        attack_rating=features.home_attack_rating,
        opponent_defense=features.away_defense_rating,
        attack_edge=features.home_attack_vs_defense_edge,
        data_confidence=features.data_confidence,
        is_underdog=not home_is_favorite,
    )
    away_floor, away_floor_details = _adaptive_floor(
        away_raw,
        attack_rating=features.away_attack_rating,
        opponent_defense=features.home_defense_rating,
        attack_edge=features.away_attack_vs_defense_edge,
        data_confidence=features.data_confidence,
        is_underdog=home_is_favorite,
    )

    suppression_applied: list[str] = []
    home_xg = max(ABSOLUTE_MIN_XG, min(ABSOLUTE_MAX_XG, home_floor))
    away_xg = max(ABSOLUTE_MIN_XG, min(ABSOLUTE_MAX_XG, away_floor))

    ud_xg = away_xg if features.underdog_side == "away" else home_xg
    ud_attack = features.underdog_attack_rating
    fav_defense = features.favorite_defense_rating
    maher_ud = features.maher_underdog_xg or ud_xg

    weak_gate = (
        features.power_gap_abs >= GAP_STRONG_FAVORITE
        and ud_attack <= ATTACK_WEAK
        and fav_defense >= DEF_STRONG
        and ud_xg >= SUSPICIOUS_HIGH_UD_XG
        and (
            features.maher_confidence < MAHER_CONFIDENCE_TAU
            or maher_ud < ud_xg - 0.15
        )
    )
    if weak_gate and features.underdog_attack_edge < 0.35:
        factor = _weak_underdog_suppression_factor(
            power_gap_abs=features.power_gap_abs,
            underdog_attack=ud_attack,
            favorite_defense=fav_defense,
        )
        factor = min(factor, 0.82 if ud_attack <= 0.12 else 0.90)
        if features.underdog_side == "away":
            away_xg = round(max(ABSOLUTE_MIN_XG, away_xg * factor), 2)
        else:
            home_xg = round(max(ABSOLUTE_MIN_XG, home_xg * factor), 2)
        suppression_applied.append("WEAK_UNDERDOG_SUPPRESSION")

    if features.power_gap_abs >= 50.0:
        if home_is_favorite and home_xg < away_xg:
            home_xg, away_xg = max(home_xg, away_xg * 1.05), min(away_xg, home_xg * 0.95)
        elif not home_is_favorite and away_xg < home_xg:
            away_xg, home_xg = max(away_xg, home_xg * 1.05), min(home_xg, away_xg * 0.95)

    home_xg, away_xg, guard_details = _total_goals_guard(home_xg, away_xg)

    components = {
        "home_raw": round(home_raw, 4),
        "away_raw": round(away_raw, 4),
        "attack_vs_defense_edges": {
            "home": round(features.home_attack_vs_defense_edge, 4),
            "away": round(features.away_attack_vs_defense_edge, 4),
        },
        "weights": {"home": home_weights, "away": away_weights},
    }

    return MatchupRelativeXgV1Result(
        home_xg=home_xg,
        away_xg=away_xg,
        components=components,
        suppression_applied=suppression_applied,
        confidence=features.data_confidence,
        feature_vector_summary=features.summary(),
        adaptive_floor_details={"home": home_floor_details, "away": away_floor_details},
        total_goals_guard=guard_details,
    )


def build_strength_xg_for_matchup(
    *,
    home_team: str,
    away_team: str,
    home_power: float,
    away_power: float,
    home_elo: float | None,
    away_elo: float | None,
    home_attack: float | None,
    home_defense: float | None,
    away_attack: float | None,
    away_defense: float | None,
    home_form: float | None,
    away_form: float | None,
    match_stage: str | None,
    population_powers: list[float] | None = None,
) -> tuple[float, float]:
    he = float(home_elo) if home_elo is not None else float(home_power)
    ae = float(away_elo) if away_elo is not None else float(away_power)
    sig = StrengthSignals(
        home_team=home_team,
        away_team=away_team,
        home_power=float(home_power),
        away_power=float(away_power),
        home_elo=he,
        away_elo=ae,
        home_attack=home_attack,
        home_defense=home_defense,
        away_attack=away_attack,
        away_defense=away_defense,
        home_form=home_form,
        away_form=away_form,
        population_powers=population_powers
        or [float(home_power), float(away_power)],
    )
    p1 = nr3_finalist_spec()
    home_xg, away_xg, _ = generate_strength_based_xg(
        sig,
        p1.params,
        match_stage=match_stage,
    )
    return float(home_xg), float(away_xg)


def apply_matchup_relative_blowout_adjustment(
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
) -> BlowoutAdjustment:
    """Blowout for experimental model — favorite expansion without legacy dog_floor."""
    from core.maher import signed_mismatch_gap

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
    else:
        fav_xg, dog_xg = away_xg, home_xg

    fav_target = 2.8 + t * 1.6
    fav_xg = fav_xg + t * max(0.0, fav_target - fav_xg)
    dog_xg = max(ABSOLUTE_MIN_XG, dog_xg * (1.0 - 0.12 * t))

    if gap >= 0:
        home_adj, away_adj = fav_xg, dog_xg
    else:
        home_adj, away_adj = dog_xg, fav_xg

    alpha = max(base_alpha, 0.08 + 0.22 * t)
    max_goals = 8 if t >= 0.35 else 7 if t > 0 else 6
    return BlowoutAdjustment(
        home_xg=round(home_adj, 2),
        away_xg=round(away_adj, 2),
        alpha=round(alpha, 3),
        max_goals=max_goals,
        active=True,
        note="matchup_relative_blowout",
    )


def run_matchup_relative_v1_prediction(
    *,
    home_team: str,
    away_team: str,
    home_power: float,
    away_power: float,
    home_elo: float | None,
    away_elo: float | None,
    home_attack: float | None,
    home_defense: float | None,
    away_attack: float | None,
    away_defense: float | None,
    home_gf_per_game: float | None,
    home_ga_per_game: float | None,
    away_gf_per_game: float | None,
    away_ga_per_game: float | None,
    home_form: float | None,
    away_form: float | None,
    baseline_home_xg: float,
    baseline_away_xg: float,
    advantage: float,
    avg_goals: float,
    rho: float,
    alpha: float,
    top_n: int,
    use_match_context: bool,
    context_xg_delta: float,
    fusion_blowout_enabled: bool,
    market_odds: dict[str, float] | None,
    odds_affect_prediction: bool,
    match_stage: str | None = None,
    population_powers: list[float] | None = None,
    nr3_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute full served prediction for matchup_relative_v1 variant."""
    from core.context_adjustments import apply_xg_context_delta
    from core.nr3_fcc_served_integration import (
        Nr3FccIntegratedSettings,
        _generate_matrix,
        _normalize_probs_pct,
    )
    from core.probability_pipeline import blend_1x2

    strength_home, strength_away = build_strength_xg_for_matchup(
        home_team=home_team,
        away_team=away_team,
        home_power=home_power,
        away_power=away_power,
        home_elo=home_elo,
        away_elo=away_elo,
        home_attack=home_attack,
        home_defense=home_defense,
        away_attack=away_attack,
        away_defense=away_defense,
        home_form=home_form,
        away_form=away_form,
        match_stage=match_stage,
        population_powers=population_powers,
    )

    features = build_matchup_feature_vector(
        home_team=home_team,
        away_team=away_team,
        home_power=home_power,
        away_power=away_power,
        home_attack=home_attack,
        home_defense=home_defense,
        away_attack=away_attack,
        away_defense=away_defense,
        home_gf_per_game=home_gf_per_game,
        home_ga_per_game=home_ga_per_game,
        away_gf_per_game=away_gf_per_game,
        away_ga_per_game=away_ga_per_game,
        strength_home_xg=strength_home,
        strength_away_xg=strength_away,
        baseline_home_xg=baseline_home_xg,
        baseline_away_xg=baseline_away_xg,
        global_avg=avg_goals,
    )

    candidate = compute_matchup_relative_xg_v1(
        features,
        avg_goals=avg_goals,
        context_xg_delta=context_xg_delta if use_match_context else 0.0,
    )
    home_xg, away_xg = candidate.home_xg, candidate.away_xg

    if use_match_context and abs(context_xg_delta) > 1e-6:
        home_xg, away_xg = apply_xg_context_delta(home_xg, away_xg, context_xg_delta)
        home_xg, away_xg = round(home_xg, 2), round(away_xg, 2)

    settings = Nr3FccIntegratedSettings(
        rho=rho,
        avg_goals=avg_goals,
        alpha=alpha,
        top_n=top_n,
        fusion_blowout_enabled=fusion_blowout_enabled,
        odds_affect_prediction=odds_affect_prediction,
        use_match_context=use_match_context,
        context_xg_delta=context_xg_delta if use_match_context else 0.0,
        market_odds=market_odds,
        power_gap=float(home_power) - float(away_power),
        auto_stadium_altitude=False,
        altitude=0,
    )

    he = float(home_elo) if home_elo is not None else float(home_power)
    ae = float(away_elo) if away_elo is not None else float(away_power)

    pre_blowout_xg = {"home": round(home_xg, 2), "away": round(away_xg, 2)}
    fusion_ignored = bool(fusion_blowout_enabled)

    blowout = apply_matchup_relative_blowout_adjustment(
        home_xg,
        away_xg,
        float(home_power),
        float(away_power),
        advantage,
        base_alpha=alpha,
        home_elo=he,
        away_elo=ae,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    post_blowout_xg = {"home": round(home_xg, 2), "away": round(away_xg, 2)}

    matrix_result = _generate_matrix(
        home_power=home_power,
        away_power=away_power,
        advantage=advantage,
        home_xg=home_xg,
        away_xg=away_xg,
        settings=settings,
        blowout=blowout,
        home_elo=he,
        away_elo=ae,
    )

    raw_probs = _normalize_probs_pct(matrix_result.get("probabilities_1x2", {}))
    final_probs = dict(raw_probs)
    odds_blend_applied = False
    if odds_affect_prediction and market_odds:
        final_probs = blend_1x2(raw_probs, market_odds)
        odds_blend_applied = True

    diagnostics = candidate.diagnostics_payload()
    diagnostics["fusion_blowout_enabled"] = bool(fusion_blowout_enabled)
    diagnostics["fusion_applied"] = False
    diagnostics["fusion_ignored_for_model_variant"] = fusion_ignored
    diagnostics["fusion_ignore_reason"] = (
        FUSION_IGNORE_REASON if fusion_ignored else None
    )
    diagnostics["pre_fusion_xg"] = pre_blowout_xg
    diagnostics["post_fusion_xg"] = post_blowout_xg
    diagnostics["odds_blend_applied"] = odds_blend_applied
    nr3_probs = (nr3_reference or {}).get("probabilities_1x2")
    diagnostics["reason_codes"] = build_matchup_shift_reason_codes(
        mr_home_xg=float(matrix_result["home_xg"]),
        mr_away_xg=float(matrix_result["away_xg"]),
        mr_probs=final_probs,
        feature_vector_summary=candidate.feature_vector_summary,
        nr3_home_xg=(nr3_reference or {}).get("home_xg"),
        nr3_away_xg=(nr3_reference or {}).get("away_xg"),
        nr3_probs=nr3_probs,
    )
    if nr3_reference:
        diagnostics["nr3_reference_xg"] = {
            "home": nr3_reference.get("home_xg"),
            "away": nr3_reference.get("away_xg"),
        }
        diagnostics["nr3_reference_probabilities_1x2"] = nr3_probs

    return {
        "home_xg": round(float(matrix_result["home_xg"]), 2),
        "away_xg": round(float(matrix_result["away_xg"]), 2),
        "probabilities_1x2": final_probs,
        "shadow_raw_probabilities_1x2": raw_probs,
        "top_scores": matrix_result.get("top_scores", []),
        "score_coverage": matrix_result.get("score_coverage"),
        "all_scores": matrix_result.get("all_scores"),
        "model_version": MATCHUP_RELATIVE_V1_MODEL_VERSION,
        "matchup_relative_diagnostics": diagnostics,
        "fusion_applied": False,
        "fusion_note": "",
        "odds_blend_applied": odds_blend_applied,
        "blowout_active": bool(getattr(blowout, "active", False)),
    }


def apply_matchup_relative_v1_overlay(
    result: dict[str, Any],
    probs: dict[str, float],
    served: dict[str, Any],
) -> dict[str, float]:
    """Apply matchup_relative_v1 served output to the live prediction result dict."""
    result["home_xg"] = served["home_xg"]
    result["away_xg"] = served["away_xg"]
    result["top_scores"] = served["top_scores"]
    result["probabilities_1x2"] = dict(served["probabilities_1x2"])
    if served.get("score_coverage"):
        result["score_coverage"] = served["score_coverage"]
    if served.get("all_scores") is not None:
        result["all_scores"] = served["all_scores"]
    probs.clear()
    probs.update(served["probabilities_1x2"])
    return probs
