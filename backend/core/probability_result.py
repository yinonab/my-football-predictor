"""Phase 4D — Structured probability layer and diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.probability_coherence import (
    build_coherence_warnings,
    detect_odds_blend_applied,
    favorite_from_1x2,
    favorite_from_top_scores,
    favorite_from_xg,
    probability_sum,
    probability_sum_valid,
)


@dataclass
class ProbabilityResult:
    """Raw matrix vs final displayed probabilities with coherence metadata."""

    home_team: str
    away_team: str

    home_xg: float
    away_xg: float
    raw_probabilities_1x2: dict[str, float]
    final_probabilities_1x2: dict[str, float]
    top_scores: list[Any]
    score_coverage: float | None

    odds_blend_applied: bool = False
    odds_available: bool = False
    odds_affect_prediction: bool = False
    market_probabilities_1x2: dict[str, float] | None = None
    odds_source: str | None = None
    odds_blend_weight_model: float | None = None
    odds_blend_weight_market: float | None = None

    probability_sum: float = 0.0
    probability_sum_valid: bool = True
    favorite_from_final_1x2: str | None = None
    favorite_from_xg: str | None = None
    favorite_from_top_score: str | None = None
    coherence_warnings: list[str] = field(default_factory=list)

    @property
    def final_home_win(self) -> float:
        return float(self.final_probabilities_1x2.get("home_win", 0))

    @property
    def final_draw(self) -> float:
        return float(self.final_probabilities_1x2.get("draw", 0))

    @property
    def final_away_win(self) -> float:
        return float(self.final_probabilities_1x2.get("away_win", 0))

    def to_probability_diagnostics_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "probability_sum": self.probability_sum,
            "probability_sum_valid": self.probability_sum_valid,
            "odds_available": self.odds_available,
            "odds_affect_prediction": self.odds_affect_prediction,
            "odds_blend_applied": self.odds_blend_applied,
            "raw_probabilities_1x2": dict(self.raw_probabilities_1x2),
            "final_probabilities_1x2": dict(self.final_probabilities_1x2),
            "favorite_from_final_1x2": self.favorite_from_final_1x2,
            "favorite_from_xg": self.favorite_from_xg,
            "favorite_from_top_score": self.favorite_from_top_score,
            "coherence_warnings": list(self.coherence_warnings),
        }
        if self.market_probabilities_1x2 is not None:
            payload["market_probabilities_1x2"] = dict(self.market_probabilities_1x2)
        if self.odds_source is not None:
            payload["odds_source"] = self.odds_source
        if self.odds_blend_weight_model is not None:
            payload["odds_blend_weight_model"] = self.odds_blend_weight_model
        if self.odds_blend_weight_market is not None:
            payload["odds_blend_weight_market"] = self.odds_blend_weight_market
        return payload

    def to_debug_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_probability_result(
    *,
    home_team: str,
    away_team: str,
    home_xg: float,
    away_xg: float,
    raw_probabilities_1x2: dict[str, float],
    final_probabilities_1x2: dict[str, float],
    top_scores: list[Any],
    score_coverage: float | dict[str, Any] | None = None,
    market_probabilities_1x2: dict[str, float] | None = None,
    odds_source: str | None = None,
    odds_blend_weight_model: float | None = None,
    odds_blend_weight_market: float | None = None,
    odds_available: bool = False,
    odds_affect_prediction: bool = False,
) -> ProbabilityResult:
    """Wrap matrix and final probabilities without changing values."""
    raw = {k: float(v) for k, v in raw_probabilities_1x2.items()}
    final = {k: float(v) for k, v in final_probabilities_1x2.items()}

    coverage_value: float | None
    if isinstance(score_coverage, dict):
        coverage_value = float(score_coverage.get("achieved_percent", 0))
    elif score_coverage is None:
        coverage_value = None
    else:
        coverage_value = float(score_coverage)

    odds_applied = (
        odds_affect_prediction
        and detect_odds_blend_applied(raw, final, market_probabilities_1x2)
    )
    warnings = build_coherence_warnings(
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        home_xg=home_xg,
        away_xg=away_xg,
        top_scores=top_scores,
        odds_blend_applied=odds_applied,
    )

    return ProbabilityResult(
        home_team=home_team,
        away_team=away_team,
        home_xg=float(home_xg),
        away_xg=float(away_xg),
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        top_scores=list(top_scores),
        score_coverage=coverage_value,
        odds_blend_applied=odds_applied,
        odds_available=odds_available,
        odds_affect_prediction=odds_affect_prediction,
        market_probabilities_1x2=(
            dict(market_probabilities_1x2) if market_probabilities_1x2 else None
        ),
        odds_source=odds_source,
        odds_blend_weight_model=odds_blend_weight_model,
        odds_blend_weight_market=odds_blend_weight_market,
        probability_sum=probability_sum(final),
        probability_sum_valid=probability_sum_valid(final),
        favorite_from_final_1x2=favorite_from_1x2(final),
        favorite_from_xg=favorite_from_xg(home_xg, away_xg),
        favorite_from_top_score=favorite_from_top_scores(top_scores),
        coherence_warnings=warnings,
    )
