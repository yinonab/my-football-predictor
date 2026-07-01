"""Live production NR3+FCC shadow sidecar — diagnostics only; served output unchanged."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import config
from core.blowout import apply_blowout_adjustment
from core.favorite_confidence_curve_prototype import apply_favorite_confidence_curve, build_fcc_stack, fcc_fixed_params
from core.hybrid_balance_tuning import apply_hybrid_balance_correction
from core.maher import mismatch_gap, scale_rho_for_gap
from core.math_engine import AdvancedDixonColesEngine
from core.nr3_finalist_spec import nr3_finalist_spec
from core.strength_based_xg_generator import StrengthSignals, generate_strength_based_xg
from core.strength_stage_recovery import apply_stage_recovery

SHADOW_SCORELINE_WARNING = "shadow_scoreline_systems_not_applied"
NR3_FCC_SERVED_MODEL_VERSION = "v2.3.0-nr3-fcc-served"


def _normalize_probs_pct(probs: dict[str, Any]) -> dict[str, float]:
    return {
        "home_win": float(probs.get("home_win", probs.get("home", 0.0))),
        "draw": float(probs.get("draw", 0.0)),
        "away_win": float(probs.get("away_win", probs.get("away", 0.0))),
    }


def _pct_delta(shadow: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    return {
        "home_win_pp": round(shadow["home_win"] - baseline["home_win"], 1),
        "draw_pp": round(shadow["draw"] - baseline["draw"], 1),
        "away_win_pp": round(shadow["away_win"] - baseline["away_win"], 1),
    }


def extract_served_prediction_from_sidecar(sidecar: dict[str, Any]) -> dict[str, Any] | None:
    """Compact served-ready fields from sidecar diagnostics."""
    if not sidecar.get("shadow_executed"):
        return None
    return {
        "home_xg": float(sidecar["shadow_home_xg"]),
        "away_xg": float(sidecar["shadow_away_xg"]),
        "probabilities_1x2": dict(sidecar["shadow_probabilities_1x2"]),
        "top_scores": list(sidecar.get("shadow_top_scores") or []),
        "score_coverage": sidecar.get("shadow_score_coverage"),
        "all_scores": sidecar.get("shadow_all_scores"),
    }


def apply_nr3_fcc_served_overlay(
    result: dict[str, Any],
    probs: dict[str, float],
    sidecar: dict[str, Any],
) -> dict[str, float]:
    """Apply NR3+FCC sidecar output to the live prediction result dict."""
    served = extract_served_prediction_from_sidecar(sidecar)
    if served is None:
        raise ValueError("nr3_fcc_served_not_executable")
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


def run_live_nr3_fcc_shadow_sidecar(
    *,
    home_team: str,
    away_team: str,
    neutral_ground: bool,
    home_power: float,
    away_power: float,
    home_elo: float | None,
    away_elo: float | None,
    baseline_home_xg: float,
    baseline_away_xg: float,
    baseline_probabilities_1x2: dict[str, Any],
    baseline_top_scores: list | None,
    home_advantage: float,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    home_form: float | None = None,
    away_form: float | None = None,
    population_powers: list[float] | None = None,
    match_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute NR3+FCC shadow diagnostics without mutating production served fields."""
    ctx = match_context or {}
    stage = ctx.get("stage")
    he = float(home_elo if home_elo is not None else 1500.0)
    ae = float(away_elo if away_elo is not None else 1500.0)
    advantage = 0.0 if neutral_ground else float(home_advantage)

    p1 = build_fcc_stack(nr3_finalist_spec().params, fcc_fixed_params())
    match = SimpleNamespace(home_team=home_team, away_team=away_team, stage=stage)

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
        population_powers=population_powers or [float(home_power), float(away_power)],
    )

    home_xg, away_xg, strength_diag = generate_strength_based_xg(
        sig,
        p1.strength_xg_params,
        match_stage=stage,
    )

    if p1.favorite_confidence_curve_params is not None:
        home_xg, away_xg, fcc_diag = apply_favorite_confidence_curve(
            home_xg,
            away_xg,
            match=match,
            params=p1.favorite_confidence_curve_params,
            dataset="wc2026_current",
        )
    else:
        fcc_diag = {}

    p1c2_home, p1c2_away = home_xg, away_xg
    ref_home, ref_away = float(baseline_home_xg), float(baseline_away_xg)

    if p1.stage_recovery_params is not None:
        home_xg, away_xg, _recovery_diag = apply_stage_recovery(
            home_xg,
            away_xg,
            ref_home,
            ref_away,
            stage,
            p1.stage_recovery_params,
        )

    if p1.hybrid_balance_params is not None:
        home_xg, away_xg, _balance_diag = apply_hybrid_balance_correction(
            home_xg,
            away_xg,
            p1c2_home=p1c2_home,
            p1c2_away=p1c2_away,
            baseline_home=ref_home,
            baseline_away=ref_away,
            stage=stage,
            params=p1.hybrid_balance_params,
            home_power=float(home_power),
            away_power=float(away_power),
        )

    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        float(home_power),
        float(away_power),
        advantage,
        base_alpha=config.OVERDISPERSION_ALPHA,
        home_elo=he,
        away_elo=ae,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg

    gap_for_rho = mismatch_gap(
        float(home_power), float(away_power), advantage, home_elo=he, away_elo=ae
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(config.DEFAULT_RHO, gap_for_rho),
        global_avg=config.GLOBAL_XG_AVG,
        alpha=blowout.alpha,
    )
    shadow_result = engine.generate_match_prediction(
        float(home_power),
        float(away_power),
        advantage,
        top_n=5,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
        include_all_scores=True,
    )

    baseline_probs = _normalize_probs_pct(baseline_probabilities_1x2)
    shadow_probs = _normalize_probs_pct(shadow_result.get("probabilities_1x2", {}))

    warnings = [
        SHADOW_SCORELINE_WARNING,
        "production_representative_v3_not_applied",
        "production_elite_favorite_logic_not_applied",
        "production_underdog_gate_not_applied",
    ]

    return {
        "shadow_executed": True,
        "activation_allowed": False,
        "model": "nr3_fcc_shadow",
        "home_team": home_team,
        "away_team": away_team,
        "neutral_ground": neutral_ground,
        "home_advantage_applied": round(advantage, 4),
        "baseline": {
            "home_xg": round(float(baseline_home_xg), 2),
            "away_xg": round(float(baseline_away_xg), 2),
            "probabilities_1x2": baseline_probs,
            "top_scores": list(baseline_top_scores or []),
        },
        "shadow_home_xg": float(shadow_result.get("home_xg", home_xg)),
        "shadow_away_xg": float(shadow_result.get("away_xg", away_xg)),
        "shadow_probabilities_1x2": shadow_probs,
        "shadow_top_scores": list(shadow_result.get("top_scores") or []),
        "shadow_score_coverage": shadow_result.get("score_coverage"),
        "shadow_all_scores": shadow_result.get("all_scores"),
        "delta_vs_baseline": {
            **_pct_delta(shadow_probs, baseline_probs),
            "home_xg_delta": round(float(shadow_result.get("home_xg", home_xg)) - float(baseline_home_xg), 2),
            "away_xg_delta": round(float(shadow_result.get("away_xg", away_xg)) - float(baseline_away_xg), 2),
        },
        "warnings": warnings,
        "fcc_diagnostics": fcc_diag,
        "strength_diagnostics": strength_diag,
    }
