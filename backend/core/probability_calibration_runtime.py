"""Phase 4H/4I — Optional live probability calibration (default off)."""

from __future__ import annotations

from typing import Any

import config
from core.probability_calibration import TemperatureCalibrator
from core.probability_coherence_gate import CoherenceGateResult
from core.probability_quality import normalize_1x2_probabilities

API_TO_INTERNAL = {"home_win": "home", "draw": "draw", "away_win": "away"}


def _to_api_percentages(probs: dict[str, float]) -> dict[str, float]:
    internal = normalize_1x2_probabilities(probs)
    return {
        api_key: round(internal[internal_key] * 100.0, 1)
        for api_key, internal_key in API_TO_INTERNAL.items()
    }


def apply_probability_calibration(
    probabilities_1x2: dict[str, float],
    *,
    coherence_gate: CoherenceGateResult,
) -> tuple[dict[str, float], bool, str | None]:
    """
    Apply shadow-validated temperature calibration.

    Returns (probabilities, applied, blocked_reason).
    """
    if not config.PROBABILITY_CALIBRATION_ENABLED:
        return probabilities_1x2, False, "calibration_disabled"
    if not coherence_gate.passed:
        return (
            probabilities_1x2,
            False,
            "coherence_gate_failed:"
            + ";".join(coherence_gate.blocking_reasons or ["unknown"]),
        )
    if config.PROBABILITY_CALIBRATION_METHOD != "temperature":
        return probabilities_1x2, False, "unsupported_calibration_method"

    calibrator = TemperatureCalibrator(temperature=config.PROBABILITY_CALIBRATION_TEMPERATURE)
    internal = normalize_1x2_probabilities(probabilities_1x2)
    calibrated = calibrator.apply(internal)
    return _to_api_percentages(calibrated), True, None


def maybe_apply_probability_calibration(
    probabilities_1x2: dict[str, float],
    *,
    coherence_gate: CoherenceGateResult,
) -> tuple[dict[str, float], bool]:
    """Backward-compatible wrapper."""
    probs, applied, _ = apply_probability_calibration(
        probabilities_1x2,
        coherence_gate=coherence_gate,
    )
    return probs, applied


def calibration_config_snapshot() -> dict[str, Any]:
    return {
        "enabled": config.PROBABILITY_CALIBRATION_ENABLED,
        "method": config.PROBABILITY_CALIBRATION_METHOD,
        "temperature": config.PROBABILITY_CALIBRATION_TEMPERATURE,
    }
