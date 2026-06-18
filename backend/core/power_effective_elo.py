"""Phase 2B — Effective Elo anchor + full-pipeline shadow (extends Phase 2A)."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import config
from core.blowout import apply_blowout_adjustment
from core.global_ratings import (
    compute_opponent_adjusted_form,
    english_name,
    lookup_external_record,
)
from core.maher import (
    blend_maher_with_power,
    floor_underdog_xg,
    mismatch_gap,
    scale_rho_for_gap,
)
from core.math_engine import AdvancedDixonColesEngine
from core.opponent_maher import estimate_xg_opponent_aware
from core.power_shadow_calibration import (
    CandidatePowerResult,
    _defense_sign_for_variant,
    _form_value_for_variant,
    calculate_candidate_power,
    gap_alignment_score,
    write_csv,
)
from data.database import LiveDataManager

WARNING_INTERNAL_WORLD_DIVERGENCE = "INTERNAL_WORLD_ELO_DIVERGENCE"
WARNING_WORLD_ELO_MISSING = "WORLD_ELO_MISSING_FALLBACK_USED"
WARNING_EFFECTIVE_WORLD_ANCHOR = "EFFECTIVE_ELO_WORLD_ANCHOR_STRONG"
WARNING_EFFECTIVE_LOW_CONF_WORLD = "EFFECTIVE_ELO_LOW_CONFIDENCE_WORLD_WEIGHTED"

EFFECTIVE_VARIANT_BASE: dict[str, str] = {
    "effective_elo_current_formula": "current",
    "effective_elo_adjusted_form": "adjusted_form",
    "effective_elo_defense_flipped": "defense_flipped",
    "effective_elo_defense_flipped_adjusted_form": "defense_flipped_adjusted_form",
}

EFFECTIVE_EXTERNAL_VARIANT_BASE: dict[str, str] = {
    "effective_external_current_formula": "current",
    "effective_external_adjusted_form": "adjusted_form",
}

EFFECTIVE_ANCHOR_SAMPLE_PAIRS: list[tuple[str, str]] = [
    ("Brazil (ברזיל)", "Morocco (מרוקו)"),
    ("Portugal (פורטוגל)", "DR Congo (קונגו)"),
    ("Germany (גרמניה)", "Haiti (האיטי)"),
    ("Spain (ספרד)", "Cape Verde (כף ורד)"),
    ("England (אנגליה)", "USA (ארצות הברית)"),
    ("Argentina (ארגנטינה)", "France (צרפת)"),
]


def _world_elo_for_team(team_key: str, internal_elo: float) -> tuple[float, bool]:
    external = lookup_external_record(team_key)
    if external.world_elo is not None:
        return float(external.world_elo), True
    return internal_elo, False


def blend_weights_for_strategy(
    strategy: str,
    *,
    internal_elo: float,
    world_elo: float,
    rating_confidence: float,
    world_available: bool,
) -> tuple[float, float]:
    if strategy == "internal_only":
        return 1.0, 0.0
    if strategy == "world_only":
        return (0.0, 1.0) if world_available else (1.0, 0.0)
    if strategy == "blended_static":
        return (
            config.EFFECTIVE_ELO_INTERNAL_WEIGHT_STATIC,
            config.EFFECTIVE_ELO_WORLD_WEIGHT_STATIC,
        )
    if strategy == "blended_confidence_weighted":
        if rating_confidence >= config.EFFECTIVE_ELO_CONF_HIGH_THRESHOLD:
            return config.EFFECTIVE_ELO_CONF_HIGH_INTERNAL, config.EFFECTIVE_ELO_CONF_HIGH_WORLD
        if rating_confidence >= config.EFFECTIVE_ELO_CONF_LOW_THRESHOLD:
            return config.EFFECTIVE_ELO_CONF_MID_INTERNAL, config.EFFECTIVE_ELO_CONF_MID_WORLD
        return config.EFFECTIVE_ELO_CONF_LOW_INTERNAL, config.EFFECTIVE_ELO_CONF_LOW_WORLD
    if strategy == "blended_disagreement_weighted":
        delta = abs(internal_elo - world_elo)
        if delta < config.EFFECTIVE_ELO_DISAGREE_SMALL_DELTA:
            return (
                config.EFFECTIVE_ELO_DISAGREE_SMALL_INTERNAL,
                config.EFFECTIVE_ELO_DISAGREE_SMALL_WORLD,
            )
        if delta < config.EFFECTIVE_ELO_DISAGREE_MID_DELTA:
            return (
                config.EFFECTIVE_ELO_DISAGREE_MID_INTERNAL,
                config.EFFECTIVE_ELO_DISAGREE_MID_WORLD,
            )
        return (
            config.EFFECTIVE_ELO_DISAGREE_LARGE_INTERNAL,
            config.EFFECTIVE_ELO_DISAGREE_LARGE_WORLD,
        )
    if strategy == "fifa_points_snapshot_static":
        return (
            config.EFFECTIVE_ELO_INTERNAL_WEIGHT_STATIC,
            config.EFFECTIVE_ELO_WORLD_WEIGHT_STATIC,
        )
    if strategy == "fifa_points_confidence_weighted":
        if rating_confidence >= config.EFFECTIVE_ELO_CONF_HIGH_THRESHOLD:
            return config.EFFECTIVE_ELO_CONF_HIGH_INTERNAL, config.EFFECTIVE_ELO_CONF_HIGH_WORLD
        if rating_confidence >= config.EFFECTIVE_ELO_CONF_LOW_THRESHOLD:
            return config.EFFECTIVE_ELO_CONF_MID_INTERNAL, config.EFFECTIVE_ELO_CONF_MID_WORLD
        return config.EFFECTIVE_ELO_CONF_LOW_INTERNAL, config.EFFECTIVE_ELO_CONF_LOW_WORLD
    if strategy == "fifa_points_disagreement_weighted":
        delta = abs(internal_elo - world_elo)
        if delta < config.EFFECTIVE_ELO_DISAGREE_SMALL_DELTA:
            return (
                config.EFFECTIVE_ELO_DISAGREE_SMALL_INTERNAL,
                config.EFFECTIVE_ELO_DISAGREE_SMALL_WORLD,
            )
        if delta < config.EFFECTIVE_ELO_DISAGREE_MID_DELTA:
            return (
                config.EFFECTIVE_ELO_DISAGREE_MID_INTERNAL,
                config.EFFECTIVE_ELO_DISAGREE_MID_WORLD,
            )
        return (
            config.EFFECTIVE_ELO_DISAGREE_LARGE_INTERNAL,
            config.EFFECTIVE_ELO_DISAGREE_LARGE_WORLD,
        )
    raise ValueError(f"Unknown effective Elo strategy: {strategy}")


def compute_effective_elo(
    team_key: str,
    strategy: str,
    *,
    data_manager: LiveDataManager | None = None,
) -> tuple[float, dict[str, Any]]:
    dm = data_manager or LiveDataManager()
    raw = dm.get_team_data(team_key)
    internal = float(raw.get("elo", 1500.0))
    world, world_available = _world_elo_for_team(team_key, internal)
    external = lookup_external_record(team_key)
    confidence = external.rating_confidence

    wi, ww = blend_weights_for_strategy(
        strategy,
        internal_elo=internal,
        world_elo=world,
        rating_confidence=confidence,
        world_available=world_available,
    )
    if not world_available:
        wi, ww = 1.0, 0.0
    effective = wi * internal + ww * world
    return round(effective, 1), {
        "strategy": strategy,
        "internal_elo": round(internal, 1),
        "world_elo": round(world, 1),
        "world_available": world_available,
        "internal_weight": round(wi, 3),
        "world_weight": round(ww, 3),
        "rating_confidence": confidence,
        "elo_delta": round(internal - world, 1),
    }


def compute_all_effective_elos(
    team_key: str,
    *,
    data_manager: LiveDataManager | None = None,
) -> dict[str, float]:
    return {
        strategy: compute_effective_elo(team_key, strategy, data_manager=data_manager)[0]
        for strategy in config.EFFECTIVE_ELO_STRATEGIES
    }


def build_team_effective_elo_diagnostics(
    team_key: str,
    *,
    data_manager: LiveDataManager | None = None,
) -> dict[str, Any]:
    dm = data_manager or LiveDataManager()
    raw = dm.get_team_data(team_key)
    internal = float(raw.get("elo", 1500.0))
    world, world_available = _world_elo_for_team(team_key, internal)
    external = lookup_external_record(team_key)
    confidence = external.rating_confidence
    elo_delta = round(internal - world, 1)

    warnings: list[str] = []
    if abs(elo_delta) >= config.EFFECTIVE_ELO_DIVERGENCE_THRESHOLD:
        warnings.append(WARNING_INTERNAL_WORLD_DIVERGENCE)
    if not world_available:
        warnings.append(WARNING_WORLD_ELO_MISSING)

    by_strategy = compute_all_effective_elos(team_key, data_manager=dm)
    _, meta_disagree = compute_effective_elo(
        team_key, "blended_disagreement_weighted", data_manager=dm
    )
    if meta_disagree["world_weight"] >= config.EFFECTIVE_ELO_WORLD_ANCHOR_THRESHOLD:
        warnings.append(WARNING_EFFECTIVE_WORLD_ANCHOR)
    if confidence < config.EFFECTIVE_ELO_CONF_LOW_THRESHOLD:
        warnings.append(WARNING_EFFECTIVE_LOW_CONF_WORLD)

    return {
        "team": english_name(team_key),
        "internal_elo": round(internal, 1),
        "world_elo": round(world, 1) if world_available else None,
        "elo_delta": elo_delta,
        "rating_confidence": confidence,
        "effective_elo_by_strategy": by_strategy,
        "warnings": list(dict.fromkeys(warnings)),
    }


def calculate_effective_candidate_power(
    team_key: str,
    power_variant: str,
    effective_elo_strategy: str,
    *,
    data_manager: LiveDataManager | None = None,
    use_live: bool = False,
    h2h_component: float | None = None,
    context_component: float | None = None,
    modifier_component: float | None = None,
) -> CandidatePowerResult:
    if power_variant not in EFFECTIVE_VARIANT_BASE:
        raise ValueError(f"Not an effective-elo power variant: {power_variant}")
    base = EFFECTIVE_VARIANT_BASE[power_variant]

    dm = data_manager or LiveDataManager()
    raw = dm.get_team_data(team_key, use_live=use_live)
    internal_elo = float(raw.get("elo", 1500.0))
    raw_form = float(raw.get("form", 0.5))
    attack = float(raw.get("attack", 0.5))
    defense = float(raw.get("defense", 0.5))

    effective_elo, _ = compute_effective_elo(
        team_key, effective_elo_strategy, data_manager=dm
    )
    world, _ = _world_elo_for_team(team_key, internal_elo)
    adj_form, _, _, used_opp = compute_opponent_adjusted_form(team_key, raw_form)
    form_used = _form_value_for_variant(base, raw_form, adj_form)
    defense_sign = _defense_sign_for_variant(base)

    elo_c = config.POWER_WEIGHT_ELO * effective_elo
    form_c = config.POWER_WEIGHT_FORM * form_used * 1000.0
    attack_c = config.POWER_WEIGHT_ATTACK * attack * 1000.0
    defense_c = defense_sign * config.POWER_WEIGHT_DEFENSE * defense * 1000.0
    extras = [
        x
        for x in (h2h_component, context_component, modifier_component)
        if x is not None
    ]
    total = elo_c + form_c + attack_c + defense_c + sum(extras)

    notes = [
        f"effective_elo_strategy={effective_elo_strategy}",
        f"base_formula={base}",
    ]
    if not used_opp and base in ("adjusted_form", "defense_flipped_adjusted_form"):
        notes.append("opponent-adjusted form unavailable; using raw form")

    return CandidatePowerResult(
        team=team_key,
        variant=power_variant,
        total_power=round(total, 2),
        internal_elo=round(internal_elo, 1),
        world_elo=round(world, 1),
        raw_form=round(raw_form, 3),
        opponent_adjusted_form=adj_form,
        attack=round(attack, 3),
        defense=round(defense, 3),
        components={
            "elo_component": round(elo_c, 2),
            "form_component": round(form_c, 2),
            "attack_component": round(attack_c, 2),
            "defense_component": round(defense_c, 2),
            "h2h_component": round(h2h_component, 2) if h2h_component is not None else None,
            "context_component": (
                round(context_component, 2) if context_component is not None else None
            ),
            "modifier_component": (
                round(modifier_component, 2) if modifier_component is not None else None
            ),
            "effective_elo": effective_elo,
        },
        notes=notes,
        warnings=[],
    )


_BASELINE_SENTINEL = object()


@dataclass
class ShadowPredictionResult:
    variant: str
    effective_elo_strategy: str | None
    home_power: float
    away_power: float
    home_xg: float
    away_xg: float
    probabilities_1x2: dict[str, float]
    top_scores: list[str]
    power_gap: float
    delta_vs_current: dict[str, float]
    gap_alignment_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_powers_and_blend_elos(
    home_key: str,
    away_key: str,
    *,
    power_variant: str,
    effective_elo_strategy: str | None,
    data_manager: LiveDataManager,
) -> tuple[float, float, float, float, str, str | None]:
    home_data = data_manager.get_team_data(home_key)
    away_data = data_manager.get_team_data(away_key)
    internal_home = float(home_data["elo"])
    internal_away = float(away_data["elo"])

    if power_variant in EFFECTIVE_VARIANT_BASE:
        strategy = effective_elo_strategy or "blended_disagreement_weighted"
        home_c = calculate_effective_candidate_power(
            home_key, power_variant, strategy, data_manager=data_manager
        )
        away_c = calculate_effective_candidate_power(
            away_key, power_variant, strategy, data_manager=data_manager
        )
        home_blend = float(home_c.components["effective_elo"])
        away_blend = float(away_c.components["effective_elo"])
        label = f"{power_variant}|{strategy}"
        return home_c.total_power, away_c.total_power, home_blend, away_blend, label, strategy

    home_c = calculate_candidate_power(home_key, power_variant, data_manager=data_manager)
    away_c = calculate_candidate_power(away_key, power_variant, data_manager=data_manager)
    return (
        home_c.total_power,
        away_c.total_power,
        internal_home,
        internal_away,
        power_variant,
        None,
    )


def run_full_shadow_pipeline(
    home_key: str,
    away_key: str,
    *,
    power_variant: str = "current",
    effective_elo_strategy: str | None = None,
    data_manager: LiveDataManager,
    opponent_index: dict,
    current_baseline: ShadowPredictionResult | None = None,
    advantage: float = 0.0,
    top_n: int = 3,
) -> ShadowPredictionResult:
    """Full Maher/xG/blowout/Dixon-Coles shadow path."""
    home_power, away_power, home_blend_elo, away_blend_elo, variant_label, eff_strategy = (
        _resolve_powers_and_blend_elos(
            home_key,
            away_key,
            power_variant=power_variant,
            effective_elo_strategy=effective_elo_strategy,
            data_manager=data_manager,
        )
    )
    home_data = data_manager.get_team_data(home_key)
    away_data = data_manager.get_team_data(away_key)
    internal_home = float(home_data["elo"])
    internal_away = float(away_data["elo"])
    power_gap = round(home_power - away_power, 2)
    internal_elo_gap = internal_home - internal_away
    home_world, _ = _world_elo_for_team(home_key, internal_home)
    away_world, _ = _world_elo_for_team(away_key, internal_away)
    world_elo_gap = home_world - away_world

    home_xg, away_xg, _ = estimate_xg_opponent_aware(
        home_key,
        away_key,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        opponent_index,
        global_avg=config.GLOBAL_XG_AVG,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        global_avg=config.GLOBAL_XG_AVG,
        home_elo=home_blend_elo,
        away_elo=away_blend_elo,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        home_elo=home_blend_elo,
        away_elo=away_blend_elo,
    )
    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        base_alpha=config.OVERDISPERSION_ALPHA,
        home_elo=home_blend_elo,
        away_elo=away_blend_elo,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    gap_for_rho = mismatch_gap(
        home_power,
        away_power,
        advantage,
        home_elo=home_blend_elo,
        away_elo=away_blend_elo,
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(config.DEFAULT_RHO, gap_for_rho),
        global_avg=config.GLOBAL_XG_AVG,
        alpha=blowout.alpha,
    )
    result = engine.generate_match_prediction(
        home_power,
        away_power,
        advantage,
        top_n=top_n,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    probs = result["probabilities_1x2"]

    if current_baseline is None and power_variant != "current":
        current_baseline = run_full_shadow_pipeline(
            home_key,
            away_key,
            power_variant="current",
            data_manager=data_manager,
            opponent_index=opponent_index,
            advantage=advantage,
            top_n=top_n,
            current_baseline=_BASELINE_SENTINEL,
        )

    if current_baseline is _BASELINE_SENTINEL:
        delta = {
            "home_win_pp": 0.0,
            "draw_pp": 0.0,
            "away_win_pp": 0.0,
            "home_xg_delta": 0.0,
            "away_xg_delta": 0.0,
        }
    else:
        delta = {
            "home_win_pp": round(
                probs["home_win"] - current_baseline.probabilities_1x2["home_win"], 2
            ),
            "draw_pp": round(
                probs["draw"] - current_baseline.probabilities_1x2["draw"], 2
            ),
            "away_win_pp": round(
                probs["away_win"] - current_baseline.probabilities_1x2["away_win"], 2
            ),
            "home_xg_delta": round(result["home_xg"] - current_baseline.home_xg, 3),
            "away_xg_delta": round(result["away_xg"] - current_baseline.away_xg, 3),
        }

    return ShadowPredictionResult(
        variant=variant_label,
        effective_elo_strategy=eff_strategy,
        home_power=home_power,
        away_power=away_power,
        home_xg=result["home_xg"],
        away_xg=result["away_xg"],
        probabilities_1x2=probs,
        top_scores=[s["score"] for s in result["top_scores"]],
        power_gap=power_gap,
        delta_vs_current=delta,
        gap_alignment_score=gap_alignment_score(
            power_gap, internal_elo_gap, world_elo_gap
        ),
    )


def effective_elo_gap_for_strategy(
    home_key: str,
    away_key: str,
    strategy: str,
    *,
    data_manager: LiveDataManager,
) -> float:
    home_eff, _ = compute_effective_elo(home_key, strategy, data_manager=data_manager)
    away_eff, _ = compute_effective_elo(away_key, strategy, data_manager=data_manager)
    return round(home_eff - away_eff, 1)


def power_gap_for_effective_combo(
    home_key: str,
    away_key: str,
    power_variant: str,
    elo_strategy: str,
    *,
    data_manager: LiveDataManager,
) -> float:
    home_c = calculate_effective_candidate_power(
        home_key, power_variant, elo_strategy, data_manager=data_manager
    )
    away_c = calculate_effective_candidate_power(
        away_key, power_variant, elo_strategy, data_manager=data_manager
    )
    return round(home_c.total_power - away_c.total_power, 2)


def build_effective_elo_anchor_matchup(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
    include_top_scores: bool = False,
    api_mode: bool = False,
) -> dict[str, Any]:
    dm = data_manager or LiveDataManager()
    home_key, home_data = dm.resolve_team(home_input)
    away_key, away_data = dm.resolve_team(away_input)

    home_diag = build_team_effective_elo_diagnostics(home_key, data_manager=dm)
    away_diag = build_team_effective_elo_diagnostics(away_key, data_manager=dm)

    internal_gap = round(float(home_data["elo"]) - float(away_data["elo"]), 1)
    world_home = home_diag["world_elo"] or float(home_data["elo"])
    world_away = away_diag["world_elo"] or float(away_data["elo"])
    world_gap = round(world_home - world_away, 1)

    from core.team_power import TeamPowerEvaluator

    pe = TeamPowerEvaluator(dm)
    gap_comparison: dict[str, Any] = {
        "internal_elo_gap": internal_gap,
        "world_elo_gap": world_gap,
        "effective_elo_gaps": {
            s: effective_elo_gap_for_strategy(home_key, away_key, s, data_manager=dm)
            for s in config.EFFECTIVE_ELO_STRATEGIES
        },
        "production_power_gap": round(
            pe.calculate_composite_power(home_key) - pe.calculate_composite_power(away_key),
            2,
        ),
    }
    gap_comparison["current_power_gap"] = gap_comparison["production_power_gap"]

    opp_idx = opponent_index
    if opp_idx is None:
        from core.opponent_maher import build_opponent_index
        from core.team_ratings import build_all_matches
        from data.database import FIFA_ELO_2026

        opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    shadow_predictions: list[dict[str, Any]] = []
    combos: list[tuple[str, str]] = []
    for pv in config.POWER_SHADOW_EFFECTIVE_VARIANTS:
        for es in config.EFFECTIVE_ELO_STRATEGIES:
            combos.append((pv, es))

    current_full = run_full_shadow_pipeline(
        home_key,
        away_key,
        power_variant="current",
        data_manager=dm,
        opponent_index=opp_idx,
        current_baseline=_BASELINE_SENTINEL,
        top_n=3 if include_top_scores or api_mode else 1,
    )

    for pv, es in combos:
        pred = run_full_shadow_pipeline(
            home_key,
            away_key,
            power_variant=pv,
            effective_elo_strategy=es,
            data_manager=dm,
            opponent_index=opp_idx,
            current_baseline=current_full,
            top_n=3 if include_top_scores or api_mode else 1,
        )
        entry = pred.to_dict()
        if not include_top_scores and not api_mode:
            entry.pop("top_scores", None)
        shadow_predictions.append(entry)

    shadow_predictions.sort(
        key=lambda x: x.get("gap_alignment_score", 0), reverse=True
    )
    if api_mode:
        shadow_predictions = shadow_predictions[: config.POWER_SHADOW_API_TOP_VARIANTS]

    best = shadow_predictions[0] if shadow_predictions else {}
    warnings = list(dict.fromkeys(home_diag["warnings"] + away_diag["warnings"]))

    return {
        "home": home_diag,
        "away": away_diag,
        "gap_comparison": gap_comparison,
        "shadow_predictions": shadow_predictions,
        "best_shadow_variant": best.get("variant", ""),
        "current_1x2": current_full.probabilities_1x2,
        "warnings": warnings,
    }


@dataclass
class EffectiveEloAuditRow:
    home: str
    away: str
    int_gap: float
    world_gap: float
    eff_static_gap: float
    eff_conf_gap: float
    eff_disagree_gap: float
    current_power_gap: float
    best_shadow_variant: str
    current_1x2_home: float
    shadow_1x2_home: float
    warnings: str
    elo_divergence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_effective_elo_audit_row(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
    include_top_scores: bool = False,
) -> EffectiveEloAuditRow:
    dm = data_manager or LiveDataManager()
    anchor = build_effective_elo_anchor_matchup(
        home_input,
        away_input,
        data_manager=dm,
        opponent_index=opponent_index,
        include_top_scores=include_top_scores,
    )
    gc = anchor["gap_comparison"]
    eg = gc["effective_elo_gaps"]
    best_pred = anchor["shadow_predictions"][0] if anchor["shadow_predictions"] else {}
    current = anchor["current_1x2"]
    shadow_hw = best_pred.get("probabilities_1x2", {}).get("home_win", 0.0)
    return EffectiveEloAuditRow(
        home=anchor["home"]["team"],
        away=anchor["away"]["team"],
        int_gap=gc["internal_elo_gap"],
        world_gap=gc["world_elo_gap"],
        eff_static_gap=eg["blended_static"],
        eff_conf_gap=eg["blended_confidence_weighted"],
        eff_disagree_gap=eg["blended_disagreement_weighted"],
        current_power_gap=gc["production_power_gap"],
        best_shadow_variant=anchor["best_shadow_variant"],
        current_1x2_home=current.get("home_win", 0.0),
        shadow_1x2_home=shadow_hw,
        warnings=",".join(anchor["warnings"]) if anchor["warnings"] else "",
        elo_divergence=abs(gc["world_elo_gap"] - gc["internal_elo_gap"]),
    )


def audit_sample_effective_elo(
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
    include_top_scores: bool = False,
) -> list[EffectiveEloAuditRow]:
    dm = data_manager or LiveDataManager()
    return [
        build_effective_elo_audit_row(
            h,
            a,
            data_manager=dm,
            opponent_index=opponent_index,
            include_top_scores=include_top_scores,
        )
        for h, a in EFFECTIVE_ANCHOR_SAMPLE_PAIRS
    ]


def audit_all_effective_elo(
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
) -> list[EffectiveEloAuditRow]:
    dm = data_manager or LiveDataManager()
    teams = dm.list_teams()
    rows: list[EffectiveEloAuditRow] = []
    for home in teams:
        for away in teams:
            if home == away:
                continue
            rows.append(build_effective_elo_audit_row(home, away, data_manager=dm))
    return rows


def format_effective_elo_table(rows: list[EffectiveEloAuditRow]) -> str:
    header = (
        f"{'home':10} | {'away':10} | {'int':>6} | {'world':>6} | {'st_gap':>6} | "
        f"{'cf_gap':>6} | {'dg_gap':>6} | {'pwr':>6} | {'best':>28} | "
        f"{'c_hw':>5} | {'s_hw':>5} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.home:10} | {row.away:10} | {row.int_gap:6.1f} | {row.world_gap:6.1f} | "
            f"{row.eff_static_gap:6.1f} | {row.eff_conf_gap:6.1f} | {row.eff_disagree_gap:6.1f} | "
            f"{row.current_power_gap:6.1f} | {row.best_shadow_variant:>28} | "
            f"{row.current_1x2_home:5.1f} | {row.shadow_1x2_home:5.1f} | {row.warnings or '-'}"
        )
    return "\n".join(lines)


@dataclass
class FullPipelineBacktestRow:
    variant: str
    elo_strategy: str
    outcome_accuracy: float
    exact_score_accuracy: float
    top3_score_hit_rate: float
    mean_log_loss: float
    mean_brier: float
    fav_calib_error: float
    mean_xg_delta: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _favorite_bucket(prob: float) -> str | None:
    if prob >= 80:
        return "80+"
    if prob >= 70:
        return "70-80"
    if prob >= 60:
        return "60-70"
    if prob >= 50:
        return "50-60"
    return None


def run_full_pipeline_backtest(
    power_variant: str,
    elo_strategy: str,
    *,
    data_manager: Any | None = None,
) -> FullPipelineBacktestRow:
    from core.backtest import _brier_score, _log_loss_score, _outcome, _predicted_outcome
    from core.opponent_maher import build_opponent_index
    from core.team_ratings import build_all_matches
    from data.database import FIFA_ELO_2026
    from data.wc2022 import WC2022_MATCHES, Wc2022DataManager

    dm = data_manager or Wc2022DataManager()
    opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    results: list[dict[str, Any]] = []
    bucket_errors: dict[str, list[float]] = {
        "50-60": [],
        "60-70": [],
        "70-80": [],
        "80+": [],
    }

    for match in WC2022_MATCHES:
        home_key = match.home
        away_key = match.away
        try:
            if power_variant == "current" and elo_strategy == "internal_only":
                pred = run_full_shadow_pipeline(
                    home_key,
                    away_key,
                    power_variant="current",
                    data_manager=dm,  # type: ignore[arg-type]
                    opponent_index=opp_idx,
                    current_baseline=_BASELINE_SENTINEL,
                )
            else:
                pv = power_variant
                if pv == "current":
                    pv = "effective_elo_current_formula"
                pred = run_full_shadow_pipeline(
                    home_key,
                    away_key,
                    power_variant=pv,
                    effective_elo_strategy=elo_strategy,
                    data_manager=dm,  # type: ignore[arg-type]
                    opponent_index=opp_idx,
                    current_baseline=_BASELINE_SENTINEL,
                )
        except Exception:
            continue

        probs = pred.probabilities_1x2
        actual = _outcome(match.home_goals, match.away_goals)
        predicted = _predicted_outcome(probs)
        actual_score = f"{match.home_goals}-{match.away_goals}"

        fav_prob = max(probs["home_win"], probs["draw"], probs["away_win"])
        bucket = _favorite_bucket(fav_prob)
        if bucket:
            hit = 1.0 if (
                (predicted == "home" and actual == "home")
                or (predicted == "draw" and actual == "draw")
                or (predicted == "away" and actual == "away")
            ) else 0.0
            bucket_errors[bucket].append(abs(fav_prob / 100.0 - hit))

        prob_map = {"home": probs["home_win"], "draw": probs["draw"], "away": probs["away_win"]}
        results.append(
            {
                "outcome_correct": actual == predicted,
                "exact_hit": actual_score == pred.top_scores[0] if pred.top_scores else False,
                "top3_hit": actual_score in pred.top_scores[:3],
                "brier": _brier_score(probs, actual),
                "log_loss": _log_loss_score(prob_map[actual]),
                "xg_delta": abs(pred.delta_vs_current.get("home_xg_delta", 0))
                + abs(pred.delta_vs_current.get("away_xg_delta", 0)),
            }
        )

    n = len(results)
    if n == 0:
        return FullPipelineBacktestRow(
            variant=power_variant,
            elo_strategy=elo_strategy,
            outcome_accuracy=0.0,
            exact_score_accuracy=0.0,
            top3_score_hit_rate=0.0,
            mean_log_loss=0.0,
            mean_brier=0.0,
            fav_calib_error=0.0,
            mean_xg_delta=0.0,
            notes="no evaluable matches",
        )

    fav_errs = [v for vals in bucket_errors.values() for v in vals]
    fav_calib = round(sum(fav_errs) / len(fav_errs), 4) if fav_errs else 0.0

    return FullPipelineBacktestRow(
        variant=power_variant,
        elo_strategy=elo_strategy,
        outcome_accuracy=round(sum(r["outcome_correct"] for r in results) / n * 100, 1),
        exact_score_accuracy=round(sum(r["exact_hit"] for r in results) / n * 100, 1),
        top3_score_hit_rate=round(sum(r["top3_hit"] for r in results) / n * 100, 1),
        mean_log_loss=round(sum(r["log_loss"] for r in results) / n, 4),
        mean_brier=round(sum(r["brier"] for r in results) / n, 4),
        fav_calib_error=fav_calib,
        mean_xg_delta=round(sum(r["xg_delta"] for r in results) / n, 4),
        notes="full Maher/xG/blowout pipeline",
    )


def run_all_full_pipeline_backtests() -> list[FullPipelineBacktestRow]:
    rows: list[FullPipelineBacktestRow] = []
    rows.append(run_full_pipeline_backtest("current", "internal_only"))
    for pv in config.POWER_SHADOW_EFFECTIVE_VARIANTS:
        for es in config.EFFECTIVE_ELO_STRATEGIES:
            rows.append(run_full_pipeline_backtest(pv, es))
    return rows


def format_full_backtest_table(rows: list[FullPipelineBacktestRow]) -> str:
    header = (
        f"{'variant':32} | {'elo_strat':24} | {'1x2':>5} | {'exact':>5} | "
        f"{'top3':>5} | {'log_loss':>8} | {'brier':>6} | {'fav_err':>7} | notes"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.variant:32} | {row.elo_strategy:24} | {row.outcome_accuracy:5.1f} | "
            f"{row.exact_score_accuracy:5.1f} | {row.top3_score_hit_rate:5.1f} | "
            f"{row.mean_log_loss:8.4f} | {row.mean_brier:6.4f} | "
            f"{row.fav_calib_error:7.4f} | {row.notes}"
        )
    return "\n".join(lines)
