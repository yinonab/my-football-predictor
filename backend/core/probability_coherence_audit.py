"""Phase 4H — Helpers for probability coherence audit reports."""

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
    favorite_from_top_scores,
    favorite_from_xg,
)
from core.probability_coherence_gate import CoherenceGateResult, evaluate_coherence_gate
from core.probability_result import ProbabilityResult, build_probability_result

DEFAULT_AUDIT_MATCHUPS: tuple[tuple[str, str], ...] = (
    ("Qatar", "Canada"),
    ("Brazil", "Morocco"),
    ("Germany", "Haiti"),
    ("Argentina", "France"),
    ("Portugal", "DR Congo"),
    ("Spain", "Cape Verde"),
    ("Canada", "Qatar"),
    ("Morocco", "Brazil"),
    ("Netherlands", "Japan"),
    ("England", "Ghana"),
    ("Colombia", "Portugal"),
    ("Belgium", "Iran"),
)

ROOT_CAUSE_COHERENT = "coherent"
ROOT_CAUSE_ODDS_BLEND = "odds_blend_mismatch"
ROOT_CAUSE_MATRIX_XG = "matrix_xg_mismatch_without_odds"
ROOT_CAUSE_NEAR_BALANCED = "near_balanced_advisory"
ROOT_CAUSE_INVALID_SUM = "invalid_probability_sum"
ROOT_CAUSE_UNKNOWN = "unknown"


@dataclass
class CoherenceAuditRow:
    home_team: str
    away_team: str
    scenario: str
    neutral_ground: bool = True
    probabilities_1x2: dict[str, float] = field(default_factory=dict)
    home_xg: float = 0.0
    away_xg: float = 0.0
    top_scores: list[dict[str, Any]] = field(default_factory=list)
    score_coverage: float | None = None
    home_power: float | None = None
    away_power: float | None = None
    odds_available: bool = False
    odds_affect_prediction: bool = False
    odds_blend_applied: bool = False
    raw_probabilities_1x2: dict[str, float] = field(default_factory=dict)
    final_probabilities_1x2: dict[str, float] = field(default_factory=dict)
    favorite_from_final_1x2: str | None = None
    favorite_from_xg: str | None = None
    favorite_from_top_score: str | None = None
    top_score_direction: str | None = None
    coherence_warnings: list[str] = field(default_factory=list)
    gate_passed: bool = True
    gate_blocking: list[str] = field(default_factory=list)
    gate_advisory: list[str] = field(default_factory=list)
    likely_root_cause: str = ROOT_CAUSE_COHERENT
    match_summary: str = ""
    outcome_explanations: dict[str, str] = field(default_factory=dict)
    probability_diagnostics: dict[str, Any] | None = None
    model_diagnostics: dict[str, Any] | None = None
    global_rating_diagnostics: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "scenario": self.scenario,
            "neutral_ground": self.neutral_ground,
            "probabilities_1x2": self.probabilities_1x2,
            "home_xg": self.home_xg,
            "away_xg": self.away_xg,
            "top_scores": self.top_scores,
            "score_coverage": self.score_coverage,
            "home_power": self.home_power,
            "away_power": self.away_power,
            "odds_available": self.odds_available,
            "odds_affect_prediction": self.odds_affect_prediction,
            "odds_blend_applied": self.odds_blend_applied,
            "raw_probabilities_1x2": self.raw_probabilities_1x2,
            "final_probabilities_1x2": self.final_probabilities_1x2,
            "favorite_from_final_1x2": self.favorite_from_final_1x2,
            "favorite_from_xg": self.favorite_from_xg,
            "favorite_from_top_score": self.favorite_from_top_score,
            "top_score_direction": self.top_score_direction,
            "coherence_warnings": self.coherence_warnings,
            "gate_passed": self.gate_passed,
            "gate_blocking": self.gate_blocking,
            "gate_advisory": self.gate_advisory,
            "likely_root_cause": self.likely_root_cause,
            "match_summary": self.match_summary,
            "outcome_explanations": self.outcome_explanations,
            "probability_diagnostics": self.probability_diagnostics,
            "model_diagnostics": self.model_diagnostics,
            "global_rating_diagnostics": self.global_rating_diagnostics,
            "error": self.error,
        }


def infer_likely_root_cause(
    *,
    odds_blend_applied: bool,
    coherence_warnings: list[str],
    gate: CoherenceGateResult,
) -> str:
    if not gate.passed:
        if PROBABILITY_SUM_INVALID in gate.blocking_reasons:
            return ROOT_CAUSE_INVALID_SUM
        if (
            ODDS_BLEND_1X2_SCORELINE_MISMATCH in coherence_warnings
            or (odds_blend_applied and gate.blocking_reasons)
        ):
            return ROOT_CAUSE_ODDS_BLEND
        if (
            FAVORITE_PROBABILITY_XG_MISMATCH in coherence_warnings
            or TOP_SCORE_DIRECTION_MISMATCH in coherence_warnings
        ):
            if odds_blend_applied:
                return ROOT_CAUSE_ODDS_BLEND
            return ROOT_CAUSE_MATRIX_XG
    if gate.advisory_reasons and not gate.blocking_reasons:
        return ROOT_CAUSE_NEAR_BALANCED
    return ROOT_CAUSE_COHERENT


def build_audit_row_from_predict_response(
    payload: dict[str, Any],
    *,
    scenario: str,
) -> CoherenceAuditRow:
    pd = payload.get("probability_diagnostics") or {}
    raw = dict(pd.get("raw_probabilities_1x2") or payload.get("probabilities_1x2") or {})
    final = dict(pd.get("final_probabilities_1x2") or payload.get("probabilities_1x2") or {})
    top_scores = list(payload.get("top_scores") or [])
    home_xg = float(payload.get("home_xg", 0))
    away_xg = float(payload.get("away_xg", 0))
    coverage_raw = payload.get("score_coverage") or {}
    coverage = (
        float(coverage_raw.get("achieved_percent", 0))
        if isinstance(coverage_raw, dict)
        else None
    )

    probability_result = build_probability_result(
        home_team=str(payload.get("home_team", "")),
        away_team=str(payload.get("away_team", "")),
        home_xg=home_xg,
        away_xg=away_xg,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        top_scores=top_scores,
        score_coverage=coverage,
        market_probabilities_1x2=pd.get("market_probabilities_1x2"),
        odds_source=pd.get("odds_source"),
        odds_blend_weight_model=pd.get("odds_blend_weight_model"),
        odds_blend_weight_market=pd.get("odds_blend_weight_market"),
        odds_available=bool(pd.get("odds_available", False)),
        odds_affect_prediction=bool(pd.get("odds_affect_prediction", False)),
    )
    pc = payload.get("probability_coherence") or {}
    if pc:
        gate = CoherenceGateResult(
            passed=bool(pc.get("passed", True)),
            warnings=list(pc.get("warnings") or probability_result.coherence_warnings),
            blocking_reasons=list(pc.get("blocking_reasons") or []),
            advisory_reasons=list(pc.get("advisory_reasons") or []),
        )
    else:
        gate = evaluate_coherence_gate(probability_result)
    odds_blend_applied = bool(pd.get("odds_blend_applied", probability_result.odds_blend_applied))
    root = infer_likely_root_cause(
        odds_blend_applied=odds_blend_applied,
        coherence_warnings=list(probability_result.coherence_warnings),
        gate=gate,
    )

    explanations = payload.get("outcome_explanations") or {}
    return CoherenceAuditRow(
        home_team=str(payload.get("home_team", "")),
        away_team=str(payload.get("away_team", "")),
        scenario=scenario,
        neutral_ground=True,
        probabilities_1x2=dict(payload.get("probabilities_1x2") or {}),
        home_xg=home_xg,
        away_xg=away_xg,
        top_scores=top_scores,
        score_coverage=coverage,
        home_power=payload.get("home_power"),
        away_power=payload.get("away_power"),
        odds_available=bool(pd.get("odds_available", False)),
        odds_affect_prediction=bool(pd.get("odds_affect_prediction", False)),
        odds_blend_applied=odds_blend_applied,
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        favorite_from_final_1x2=probability_result.favorite_from_final_1x2,
        favorite_from_xg=probability_result.favorite_from_xg,
        favorite_from_top_score=probability_result.favorite_from_top_score,
        top_score_direction=favorite_from_top_scores(top_scores),
        coherence_warnings=list(probability_result.coherence_warnings),
        gate_passed=gate.passed,
        gate_blocking=list(gate.blocking_reasons),
        gate_advisory=list(gate.advisory_reasons),
        likely_root_cause=root,
        match_summary=str(payload.get("match_summary") or ""),
        outcome_explanations={
            "home_win": str(explanations.get("home_win", "")),
            "draw": str(explanations.get("draw", "")),
            "away_win": str(explanations.get("away_win", "")),
        },
        probability_diagnostics=pd or None,
        model_diagnostics=payload.get("model_diagnostics"),
        global_rating_diagnostics=payload.get("global_rating_diagnostics"),
    )


def summarize_audit_rows(rows: list[CoherenceAuditRow]) -> dict[str, Any]:
    coherent = sum(1 for row in rows if row.likely_root_cause == ROOT_CAUSE_COHERENT)
    advisory = sum(1 for row in rows if row.gate_advisory and row.gate_passed)
    blocking = sum(1 for row in rows if not row.gate_passed)
    root_counts: dict[str, int] = {}
    for row in rows:
        root_counts[row.likely_root_cause] = root_counts.get(row.likely_root_cause, 0) + 1
    top_root = max(root_counts, key=root_counts.get) if root_counts else ROOT_CAUSE_UNKNOWN
    return {
        "total": len(rows),
        "coherent": coherent,
        "advisory": advisory,
        "blocking": blocking,
        "root_cause_counts": root_counts,
        "top_root_cause": top_root,
    }
