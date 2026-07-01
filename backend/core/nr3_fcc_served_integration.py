"""NR3+FCC served prediction with request settings integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import config
from core.blowout import BlowoutAdjustment, apply_blowout_adjustment
from core.context_adjustments import apply_xg_context_delta
from core.favorite_confidence_curve_prototype import (
    apply_favorite_confidence_curve,
    build_fcc_stack,
    fcc_fixed_params,
)
from core.fusion_blowout import apply_fusion_blowout, compute_fusion_blowout_signal
from core.hybrid_balance_tuning import apply_hybrid_balance_correction
from core.strength_stage_recovery import apply_stage_recovery

logger = logging.getLogger(__name__)

SHADOW_SCORELINE_WARNING = "shadow_scoreline_systems_not_applied"


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


from core.maher import mismatch_gap, scale_rho_for_gap
from core.math_engine import AdvancedDixonColesEngine
from core.nr3_finalist_spec import nr3_finalist_spec
from core.odds_ensemble import MARKET_WEIGHT, MODEL_WEIGHT, blend_1x2
from core.nr3_xg_decomposition import Nr3XgDecompositionBuilder
from core.strength_based_xg_generator import StrengthSignals, generate_strength_based_xg

NR3_SERVED_MODEL_VERSION = "v2.3.0-nr3-fcc-served"


@dataclass(frozen=True)
class Nr3FccIntegratedSettings:
    rho: float = config.DEFAULT_RHO
    avg_goals: float = config.GLOBAL_XG_AVG
    alpha: float = config.OVERDISPERSION_ALPHA
    top_n: int = 3
    fusion_blowout_enabled: bool = False
    odds_affect_prediction: bool = False
    use_match_context: bool = True
    context_xg_delta: float = 0.0
    market_odds: dict[str, float] | None = None
    power_gap: float = 0.0
    auto_stadium_altitude: bool = True
    altitude: int = 0


def _scale_xg_for_avg_goals(
    home_xg: float, away_xg: float, avg_goals: float
) -> tuple[float, float]:
    ref = float(config.GLOBAL_XG_AVG)
    if abs(avg_goals - ref) < 1e-9:
        return home_xg, away_xg
    scale = avg_goals / ref
    return home_xg * scale, away_xg * scale


def _apply_altitude_xg_penalty(
    home_xg: float, away_xg: float, altitude: int
) -> tuple[float, float]:
    if altitude <= config.ALTITUDE_THRESHOLD_M:
        return home_xg, away_xg
    factor = max(config.MIN_MODIFIER, 1.0 - config.ALTITUDE_PENALTY)
    return home_xg * factor, away_xg * factor


def _generate_matrix(
    *,
    home_power: float,
    away_power: float,
    advantage: float,
    home_xg: float,
    away_xg: float,
    settings: Nr3FccIntegratedSettings,
    blowout: BlowoutAdjustment,
    home_elo: float,
    away_elo: float,
) -> dict[str, Any]:
    gap_for_rho = mismatch_gap(
        home_power, away_power, advantage, home_elo=home_elo, away_elo=away_elo
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(settings.rho, gap_for_rho),
        global_avg=settings.avg_goals,
        alpha=blowout.alpha,
    )
    return engine.generate_match_prediction(
        home_power,
        away_power,
        advantage,
        top_n=settings.top_n,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
        include_all_scores=True,
    )


def run_nr3_fcc_integrated_prediction(
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
    settings: Nr3FccIntegratedSettings,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    home_form: float | None = None,
    away_form: float | None = None,
    population_powers: list[float] | None = None,
    match_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """NR3+FCC stack with request settings (matrix, fusion, odds, context)."""
    ctx = match_context or {}
    stage = ctx.get("stage") if settings.use_match_context else None
    he = float(home_elo if home_elo is not None else 1500.0)
    ae = float(away_elo if away_elo is not None else 1500.0)
    advantage = 0.0 if neutral_ground else float(home_advantage)

    context_available = bool(settings.use_match_context)
    altitude_active = settings.altitude > config.ALTITUDE_THRESHOLD_M
    applied_to_power = altitude_active or settings.auto_stadium_altitude
    applied_to_xg = (
        (settings.use_match_context and abs(settings.context_xg_delta) > 1e-6)
        or altitude_active
    )

    logger.warning(
        "nr3_fcc_context_applied use_match_context=%s auto_stadium_altitude=%s "
        "altitude=%s context_available=%s applied_to_power=%s applied_to_xg=%s",
        settings.use_match_context,
        settings.auto_stadium_altitude,
        settings.altitude,
        context_available,
        applied_to_power,
        applied_to_xg,
    )
    print(
        "nr3_fcc_context_applied "
        f"use_match_context={settings.use_match_context} "
        f"auto_stadium_altitude={settings.auto_stadium_altitude} "
        f"altitude={settings.altitude} context_available={context_available} "
        f"applied_to_power={applied_to_power} applied_to_xg={applied_to_xg}",
        flush=True,
    )

    logger.warning(
        "nr3_fcc_served_settings_applied avg_goals=%s rho=%s alpha=%s top_n=%s "
        "fusion_blowout_enabled=%s odds_affect_prediction=%s use_match_context=%s "
        "auto_stadium_altitude=%s altitude=%s applied_to_nr3=true",
        settings.avg_goals,
        settings.rho,
        settings.alpha,
        settings.top_n,
        settings.fusion_blowout_enabled,
        settings.odds_affect_prediction,
        settings.use_match_context,
        settings.auto_stadium_altitude,
        settings.altitude,
    )
    print(
        "nr3_fcc_served_settings_applied "
        f"avg_goals={settings.avg_goals} rho={settings.rho} alpha={settings.alpha} "
        f"top_n={settings.top_n} fusion_blowout_enabled={settings.fusion_blowout_enabled} "
        f"odds_affect_prediction={settings.odds_affect_prediction} "
        f"use_match_context={settings.use_match_context} "
        f"auto_stadium_altitude={settings.auto_stadium_altitude} altitude={settings.altitude} "
        "applied_to_nr3=true",
        flush=True,
    )

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

    decomp = Nr3XgDecompositionBuilder(
        home_team=home_team,
        away_team=away_team,
        active_model=NR3_SERVED_MODEL_VERSION,
        legacy_home_xg=baseline_home_xg,
        legacy_away_xg=baseline_away_xg,
    )
    decomp.set_nr3_base(home_xg, away_xg)

    before_h, before_a = home_xg, away_xg
    if p1.favorite_confidence_curve_params is not None:
        home_xg, away_xg, fcc_diag = apply_favorite_confidence_curve(
            home_xg,
            away_xg,
            match=match,
            params=p1.favorite_confidence_curve_params,
            dataset="wc2026_current",
        )
        decomp.record(
            name="fcc_calibration",
            display_name="כיול FCC",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation="עקומת אמון מועדף NR3",
        )
    else:
        fcc_diag = {}
        decomp.record_unchanged(
            name="fcc_calibration",
            display_name="כיול FCC",
            status="skipped",
            explanation="פרמטרי FCC לא זמינים",
            home_xg=home_xg,
            away_xg=away_xg,
        )

    p1c2_home, p1c2_away = home_xg, away_xg
    ref_home, ref_away = float(baseline_home_xg), float(baseline_away_xg)

    if settings.use_match_context and p1.stage_recovery_params is not None:
        before_h, before_a = home_xg, away_xg
        home_xg, away_xg, _recovery_diag = apply_stage_recovery(
            home_xg,
            away_xg,
            ref_home,
            ref_away,
            stage,
            p1.stage_recovery_params,
        )
        decomp.record(
            name="stage_recovery",
            display_name="התאמת שלב",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation="שחזור שלב טורניר לפי הקשר משחק",
        )
    else:
        decomp.record_unchanged(
            name="stage_recovery",
            display_name="התאמת שלב",
            status="disabled" if not settings.use_match_context else "skipped",
            explanation=(
                "הקשר משחק כבוי"
                if not settings.use_match_context
                else "ללא פרמטרי stage recovery"
            ),
            home_xg=home_xg,
            away_xg=away_xg,
        )

    if p1.hybrid_balance_params is not None:
        before_h, before_a = home_xg, away_xg
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
        decomp.record(
            name="hybrid_balance",
            display_name="איזון היברידי",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation="כיוונון איזון בין NR3 לבסיס",
        )
    else:
        decomp.record_unchanged(
            name="hybrid_balance",
            display_name="איזון היברידי",
            status="skipped",
            explanation="פרמטרי איזון היברידי לא זמינים",
            home_xg=home_xg,
            away_xg=away_xg,
        )

    if settings.use_match_context and abs(settings.context_xg_delta) > 1e-6:
        before_h, before_a = home_xg, away_xg
        home_xg, away_xg = apply_xg_context_delta(
            home_xg, away_xg, settings.context_xg_delta
        )
        decomp.record(
            name="match_context",
            display_name="הקשר / מזג / נסיעה",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation=f"דלתא xG הקשרית {settings.context_xg_delta:+.2f}",
        )
    else:
        decomp.record_unchanged(
            name="match_context",
            display_name="הקשר / מזג / נסיעה",
            status="disabled" if not settings.use_match_context else "skipped",
            explanation=(
                "הקשר משחק כבוי"
                if not settings.use_match_context
                else "אין דלתא הקשר זמינה"
            ),
            home_xg=home_xg,
            away_xg=away_xg,
        )

    before_h, before_a = home_xg, away_xg
    home_xg, away_xg = _scale_xg_for_avg_goals(
        home_xg, away_xg, settings.avg_goals
    )
    if abs(home_xg - before_h) > 1e-6 or abs(away_xg - before_a) > 1e-6:
        decomp.record(
            name="avg_goals",
            display_name="ממוצע שערים",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation=f"scale לפי avg_goals={settings.avg_goals}",
        )
    else:
        decomp.record_unchanged(
            name="avg_goals",
            display_name="ממוצע שערים",
            status="skipped",
            explanation="avg_goals ברירת מחדל — ללא שינוי",
            home_xg=home_xg,
            away_xg=away_xg,
        )

    before_h, before_a = home_xg, away_xg
    home_xg, away_xg = _apply_altitude_xg_penalty(
        home_xg, away_xg, settings.altitude
    )
    if abs(home_xg - before_h) > 1e-6 or abs(away_xg - before_a) > 1e-6:
        decomp.record(
            name="altitude",
            display_name="גובה",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied",
            explanation=f"עונש גובה {settings.altitude}m",
        )
    else:
        decomp.record_unchanged(
            name="altitude",
            display_name="גובה",
            status="skipped",
            explanation="ללא עונש גובה פעיל",
            home_xg=home_xg,
            away_xg=away_xg,
        )

    fusion_applied = False
    odds_blend_applied = False
    fusion_note = ""

    if settings.fusion_blowout_enabled:
        pre_blowout = BlowoutAdjustment(
            home_xg=home_xg,
            away_xg=away_xg,
            alpha=settings.alpha,
            max_goals=6,
            active=False,
        )
        pre_matrix = _generate_matrix(
            home_power=home_power,
            away_power=away_power,
            advantage=advantage,
            home_xg=home_xg,
            away_xg=away_xg,
            settings=settings,
            blowout=pre_blowout,
            home_elo=he,
            away_elo=ae,
        )
        pre_probs = _normalize_probs_pct(pre_matrix.get("probabilities_1x2", {}))
        weather_delta = settings.context_xg_delta if settings.use_match_context else 0.0
        fusion_signal = compute_fusion_blowout_signal(
            pre_probs,
            settings.market_odds,
            power_gap=settings.power_gap,
            weather_xg_delta=weather_delta,
        )
        before_home, before_away = home_xg, away_xg
        blowout = apply_fusion_blowout(
            home_xg,
            away_xg,
            fusion_signal,
            base_alpha=settings.alpha,
        )
        home_xg, away_xg = blowout.home_xg, blowout.away_xg
        fusion_applied = blowout.active
        fusion_note = blowout.note
        decomp.record(
            name="fusion_blowout",
            display_name="Goliath / Fusion",
            before_home_xg=before_home,
            before_away_xg=before_away,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status="applied" if fusion_applied else "skipped",
            explanation=fusion_note or "אות גולנט משולב",
        )
        decomp.record_unchanged(
            name="standard_blowout",
            display_name="Blowout סטנדרטי",
            status="disabled",
            explanation="מבוטל כי Goliath / Fusion פעיל",
            home_xg=home_xg,
            away_xg=away_xg,
        )
        fav = fusion_signal.favorite_outcome.replace("_win", "")
        logger.warning(
            "nr3_fcc_fusion_applied home_team=%s away_team=%s favorite=%s "
            "before_home_xg=%s before_away_xg=%s after_home_xg=%s after_away_xg=%s "
            "fusion_blowout_enabled=%s",
            home_team,
            away_team,
            fav,
            before_home,
            before_away,
            home_xg,
            away_xg,
            settings.fusion_blowout_enabled,
        )
        print(
            "nr3_fcc_fusion_applied "
            f"home_team={home_team} away_team={away_team} favorite={fav} "
            f"before_home_xg={before_home} before_away_xg={before_away} "
            f"after_home_xg={home_xg} after_away_xg={away_xg} "
            f"fusion_blowout_enabled={settings.fusion_blowout_enabled}",
            flush=True,
        )
    else:
        before_h, before_a = home_xg, away_xg
        blowout = apply_blowout_adjustment(
            home_xg,
            away_xg,
            float(home_power),
            float(away_power),
            advantage,
            base_alpha=settings.alpha,
            home_elo=he,
            away_elo=ae,
        )
        home_xg, away_xg = blowout.home_xg, blowout.away_xg
        std_status = (
            "applied"
            if blowout.active
            or abs(home_xg - before_h) > 1e-6
            or abs(away_xg - before_a) > 1e-6
            else "skipped"
        )
        decomp.record(
            name="standard_blowout",
            display_name="Blowout סטנדרטי",
            before_home_xg=before_h,
            before_away_xg=before_a,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status=std_status,
            explanation=blowout.note or "התאמת blowout סטנדרטית",
        )
        decomp.record_unchanged(
            name="fusion_blowout",
            display_name="Goliath / Fusion",
            status="disabled",
            explanation="כבוי בהגדרות המשתמש",
            home_xg=home_xg,
            away_xg=away_xg,
        )

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

    if settings.odds_affect_prediction and settings.market_odds:
        before_probs = dict(raw_probs)
        final_probs = blend_1x2(raw_probs, settings.market_odds)
        odds_blend_applied = True
        decomp.record_unchanged(
            name="odds_blend",
            display_name="שוק הימורים",
            status="applied",
            explanation="משפיע על הסתברויות 1X2 בלבד, לא על xG",
            home_xg=home_xg,
            away_xg=away_xg,
        )
        logger.warning(
            "nr3_fcc_odds_blend_applied home_team=%s away_team=%s model_weight=%s "
            "market_weight=%s before_probs=%s after_probs=%s",
            home_team,
            away_team,
            MODEL_WEIGHT,
            MARKET_WEIGHT,
            before_probs,
            final_probs,
        )
        print(
            "nr3_fcc_odds_blend_applied "
            f"home_team={home_team} away_team={away_team} "
            f"model_weight={MODEL_WEIGHT} market_weight={MARKET_WEIGHT} "
            f"before_probs={before_probs} after_probs={final_probs}",
            flush=True,
        )
    elif settings.odds_affect_prediction:
        decomp.record_unchanged(
            name="odds_blend",
            display_name="שוק הימורים",
            status="skipped",
            explanation="אין נתוני שוק זמינים",
            home_xg=home_xg,
            away_xg=away_xg,
        )
        logger.warning(
            "nr3_fcc_odds_blend_skipped home_team=%s away_team=%s reason=no_market_data",
            home_team,
            away_team,
        )
        print(
            f"nr3_fcc_odds_blend_skipped home_team={home_team} away_team={away_team} "
            "reason=no_market_data",
            flush=True,
        )
    else:
        decomp.record_unchanged(
            name="odds_blend",
            display_name="שוק הימורים",
            status="disabled",
            explanation="כבוי בהגדרות המשתמש",
            home_xg=home_xg,
            away_xg=away_xg,
        )

    if fusion_applied:
        regen = _generate_matrix(
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
        matrix_result = regen

    matrix_result["probabilities_1x2"] = final_probs
    final_home = float(matrix_result.get("home_xg", home_xg))
    final_away = float(matrix_result.get("away_xg", away_xg))
    decomp.set_final(final_home, final_away)
    nr3_xg_decomposition = decomp.build()

    baseline_probs = _normalize_probs_pct(baseline_probabilities_1x2)
    shadow_probs = _normalize_probs_pct(matrix_result.get("probabilities_1x2", {}))

    warnings = [
        SHADOW_SCORELINE_WARNING,
        "production_representative_v3_not_applied",
        "production_elite_favorite_logic_not_applied",
        "production_underdog_gate_not_applied",
    ]

    return {
        "shadow_executed": True,
        "activation_allowed": False,
        "model": "nr3_fcc_served_integrated",
        "served_model_path": "nr3_fcc_integrated",
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
        "shadow_home_xg": float(matrix_result.get("home_xg", home_xg)),
        "shadow_away_xg": float(matrix_result.get("away_xg", away_xg)),
        "shadow_probabilities_1x2": shadow_probs,
        "shadow_top_scores": list(matrix_result.get("top_scores") or []),
        "shadow_score_coverage": matrix_result.get("score_coverage"),
        "shadow_all_scores": matrix_result.get("all_scores"),
        "shadow_raw_probabilities_1x2": raw_probs,
        "fusion_applied": fusion_applied,
        "fusion_note": fusion_note,
        "blowout_active": blowout.active,
        "odds_blend_applied": odds_blend_applied,
        "settings_applied": {
            "rho": settings.rho,
            "avg_goals": settings.avg_goals,
            "alpha": settings.alpha,
            "top_n": settings.top_n,
            "fusion_blowout_enabled": settings.fusion_blowout_enabled,
            "odds_affect_prediction": settings.odds_affect_prediction,
            "use_match_context": settings.use_match_context,
            "auto_stadium_altitude": settings.auto_stadium_altitude,
            "altitude": settings.altitude,
        },
        "delta_vs_baseline": {
            **_pct_delta(shadow_probs, baseline_probs),
            "home_xg_delta": round(
                float(matrix_result.get("home_xg", home_xg)) - float(baseline_home_xg), 2
            ),
            "away_xg_delta": round(
                float(matrix_result.get("away_xg", away_xg)) - float(baseline_away_xg), 2
            ),
        },
        "warnings": warnings,
        "fcc_diagnostics": fcc_diag,
        "strength_diagnostics": strength_diag,
        "nr3_xg_decomposition": nr3_xg_decomposition,
    }
