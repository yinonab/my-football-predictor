"""Phase 4H — Coherence gate for probability outputs (conservative thresholds)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.probability_coherence import (
    FAVORITE_PROBABILITY_XG_MISMATCH,
    ODDS_BLEND_1X2_SCORELINE_MISMATCH,
    ODDS_BLEND_APPLIED,
    PROBABILITY_SUM_INVALID,
    TOP_SCORE_DIRECTION_MISMATCH,
    favorite_from_1x2,
    favorite_from_xg,
)
from core.probability_result import ProbabilityResult

BLOCKING_WARNING_CODES: frozenset[str] = frozenset(
    {
        PROBABILITY_SUM_INVALID,
        ODDS_BLEND_1X2_SCORELINE_MISMATCH,
        FAVORITE_PROBABILITY_XG_MISMATCH,
        TOP_SCORE_DIRECTION_MISMATCH,
    }
)

ADVISORY_NEAR_BALANCED = "NEAR_BALANCED_MATCH"
ADVISORY_DRAW_TOP_SCORE_CLOSE_1X2 = "DRAW_TOP_SCORE_CLOSE_1X2"
ADVISORY_SMALL_XG_GAP = "SMALL_XG_GAP"
ADVISORY_LOW_SCORE_COVERAGE = "LOW_SCORE_COVERAGE"
ADVISORY_ODDS_BLEND_APPLIED = "ODDS_BLEND_APPLIED"

CLOSE_1X2_SPREAD_PP = 8.0
LOW_SCORE_COVERAGE_THRESHOLD = 45.0
SMALL_XG_GAP_MAX = 0.12


@dataclass
class CoherenceGateResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    advisory_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "warnings": list(self.warnings),
            "blocking_reasons": list(self.blocking_reasons),
            "advisory_reasons": list(self.advisory_reasons),
        }


def _close_1x2_spread(probabilities: dict[str, float]) -> float:
    values = [
        float(probabilities.get("home_win", 0)),
        float(probabilities.get("draw", 0)),
        float(probabilities.get("away_win", 0)),
    ]
    return max(values) - min(values)


def evaluate_coherence_gate(result: ProbabilityResult) -> CoherenceGateResult:
    """Evaluate whether final 1X2, xG, and top scores are acceptably coherent."""
    warnings = list(result.coherence_warnings)
    blocking = [code for code in warnings if code in BLOCKING_WARNING_CODES]
    advisory: list[str] = []

    final = result.final_probabilities_1x2
    if favorite_from_1x2(final) is None:
        advisory.append(ADVISORY_NEAR_BALANCED)

    if (
        result.favorite_from_top_score == "draw"
        and _close_1x2_spread(final) <= CLOSE_1X2_SPREAD_PP
    ):
        advisory.append(ADVISORY_DRAW_TOP_SCORE_CLOSE_1X2)

    if favorite_from_xg(result.home_xg, result.away_xg) is None:
        advisory.append(ADVISORY_SMALL_XG_GAP)

    if result.score_coverage is not None and result.score_coverage < LOW_SCORE_COVERAGE_THRESHOLD:
        advisory.append(ADVISORY_LOW_SCORE_COVERAGE)

    if result.odds_blend_applied or ODDS_BLEND_APPLIED in warnings:
        advisory.append(ADVISORY_ODDS_BLEND_APPLIED)

    return CoherenceGateResult(
        passed=len(blocking) == 0,
        warnings=warnings,
        blocking_reasons=blocking,
        advisory_reasons=advisory,
    )
