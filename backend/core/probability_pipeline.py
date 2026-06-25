"""Phase 4I — Coherent probability pipeline (matrix → odds → gate → calibration)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from core.odds_ensemble import MARKET_WEIGHT, MODEL_WEIGHT, blend_1x2
from core.probability_calibration_runtime import apply_probability_calibration
from core.probability_coherence_gate import CoherenceGateResult, evaluate_coherence_gate
from core.probability_result import ProbabilityResult, build_probability_result


@dataclass
class FinalizedProbabilityPipeline:
    """Single source of truth for user-visible 1X2 probabilities and diagnostics."""

    final_probabilities_1x2: dict[str, float]
    raw_probabilities_1x2: dict[str, float]
    probability_result: ProbabilityResult
    coherence_gate: CoherenceGateResult
    calibration_enabled: bool = False
    calibration_method: str = "temperature"
    calibration_temperature: float = 1.35
    calibration_applied: bool = False
    calibration_blocked_reason: str | None = None
    odds_available: bool = False
    odds_affect_prediction: bool = False

    def to_probability_diagnostics_dict(self) -> dict[str, Any]:
        payload = self.probability_result.to_probability_diagnostics_dict()
        payload.update(
            {
                "calibration_enabled": self.calibration_enabled,
                "calibration_method": self.calibration_method,
                "calibration_temperature": self.calibration_temperature,
                "calibration_applied": self.calibration_applied,
                "calibration_blocked_reason": self.calibration_blocked_reason,
                "score_matrix_source": "dixon_coles",
            }
        )
        return payload

    def to_probability_coherence_dict(self) -> dict[str, Any]:
        return self.coherence_gate.to_dict()


def _build_result(
    *,
    home_team: str,
    away_team: str,
    home_xg: float,
    away_xg: float,
    raw_probabilities_1x2: dict[str, float],
    final_probabilities_1x2: dict[str, float],
    top_scores: list[Any],
    score_coverage: float | dict[str, Any] | None,
    market_odds: dict[str, float] | None,
    odds_available: bool,
    odds_affect_prediction: bool,
) -> ProbabilityResult:
    return build_probability_result(
        home_team=home_team,
        away_team=away_team,
        home_xg=home_xg,
        away_xg=away_xg,
        raw_probabilities_1x2=raw_probabilities_1x2,
        final_probabilities_1x2=final_probabilities_1x2,
        top_scores=top_scores,
        score_coverage=score_coverage,
        market_probabilities_1x2=market_odds,
        odds_source="the_odds_api" if market_odds else None,
        odds_blend_weight_model=MODEL_WEIGHT if market_odds and odds_affect_prediction else None,
        odds_blend_weight_market=MARKET_WEIGHT if market_odds and odds_affect_prediction else None,
        odds_available=odds_available,
        odds_affect_prediction=odds_affect_prediction,
    )


def finalize_probability_pipeline(
    *,
    home_team: str,
    away_team: str,
    home_xg: float,
    away_xg: float,
    raw_probabilities_1x2: dict[str, float],
    top_scores: list[Any],
    score_coverage: float | dict[str, Any] | None,
    market_odds: dict[str, float] | None = None,
    odds_available: bool | None = None,
    odds_affect_prediction: bool | None = None,
) -> FinalizedProbabilityPipeline:
    """
    MatchFeatures/Strength → score matrix → optional odds → coherence gate → optional calibration.

    Default: final 1X2 equals raw matrix probabilities; xG/top_scores stay matrix-derived.
    """
    raw = {k: float(v) for k, v in raw_probabilities_1x2.items()}
    odds_available = market_odds is not None if odds_available is None else odds_available
    odds_affect = (
        config.ODDS_AFFECT_PREDICTION
        if odds_affect_prediction is None
        else odds_affect_prediction
    )

    if odds_affect and market_odds:
        final_probs = blend_1x2(raw, market_odds)
    else:
        final_probs = dict(raw)

    probability_result = _build_result(
        home_team=home_team,
        away_team=away_team,
        home_xg=home_xg,
        away_xg=away_xg,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final_probs,
        top_scores=top_scores,
        score_coverage=score_coverage,
        market_odds=market_odds,
        odds_available=odds_available,
        odds_affect_prediction=odds_affect,
    )
    coherence_gate = evaluate_coherence_gate(probability_result)

    calibration_enabled = config.PROBABILITY_CALIBRATION_ENABLED
    calibration_method = config.PROBABILITY_CALIBRATION_METHOD
    calibration_temperature = config.PROBABILITY_CALIBRATION_TEMPERATURE
    calibration_applied = False
    calibration_blocked_reason: str | None = None

    if calibration_enabled:
        if not coherence_gate.passed:
            calibration_blocked_reason = (
                "coherence_gate_failed:"
                + ";".join(coherence_gate.blocking_reasons or ["unknown"])
            )
        else:
            calibrated_probs, applied, block_reason = apply_probability_calibration(
                final_probs,
                coherence_gate=coherence_gate,
            )
            if applied:
                post_result = _build_result(
                    home_team=home_team,
                    away_team=away_team,
                    home_xg=home_xg,
                    away_xg=away_xg,
                    raw_probabilities_1x2=raw,
                    final_probabilities_1x2=calibrated_probs,
                    top_scores=top_scores,
                    score_coverage=score_coverage,
                    market_odds=market_odds,
                    odds_available=odds_available,
                    odds_affect_prediction=odds_affect,
                )
                post_gate = evaluate_coherence_gate(post_result)
                if post_gate.passed:
                    final_probs = calibrated_probs
                    probability_result = post_result
                    coherence_gate = post_gate
                    calibration_applied = True
                else:
                    calibration_blocked_reason = (
                        "post_calibration_coherence_failed:"
                        + ";".join(post_gate.blocking_reasons or ["unknown"])
                    )
            elif block_reason:
                calibration_blocked_reason = block_reason

    return FinalizedProbabilityPipeline(
        final_probabilities_1x2=final_probs,
        raw_probabilities_1x2=raw,
        probability_result=probability_result,
        coherence_gate=coherence_gate,
        calibration_enabled=calibration_enabled,
        calibration_method=calibration_method,
        calibration_temperature=calibration_temperature,
        calibration_applied=calibration_applied,
        calibration_blocked_reason=calibration_blocked_reason,
        odds_available=odds_available,
        odds_affect_prediction=odds_affect,
    )
