"""Live production NR3+FCC shadow/served runner — diagnostics and served integration."""

from __future__ import annotations

from typing import Any

from core.nr3_fcc_served_integration import Nr3FccIntegratedSettings, run_nr3_fcc_integrated_prediction

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
    integrated_settings: Nr3FccIntegratedSettings | None = None,
    home_attack: float | None = None,
    home_defense: float | None = None,
    away_attack: float | None = None,
    away_defense: float | None = None,
    home_form: float | None = None,
    away_form: float | None = None,
    population_powers: list[float] | None = None,
    match_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute NR3+FCC diagnostics with optional request settings integration."""
    settings = integrated_settings or Nr3FccIntegratedSettings()
    return run_nr3_fcc_integrated_prediction(
        home_team=home_team,
        away_team=away_team,
        neutral_ground=neutral_ground,
        home_power=home_power,
        away_power=away_power,
        home_elo=home_elo,
        away_elo=away_elo,
        baseline_home_xg=baseline_home_xg,
        baseline_away_xg=baseline_away_xg,
        baseline_probabilities_1x2=baseline_probabilities_1x2,
        baseline_top_scores=baseline_top_scores,
        home_advantage=home_advantage,
        settings=settings,
        home_attack=home_attack,
        home_defense=home_defense,
        away_attack=away_attack,
        away_defense=away_defense,
        home_form=home_form,
        away_form=away_form,
        population_powers=population_powers,
        match_context=match_context,
    )
