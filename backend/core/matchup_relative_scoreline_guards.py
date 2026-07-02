"""Post-scoreline consistency guards for Matchup Relative v1 only."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.matchup_goal_capability import _poisson_scores_probability
from core.scoreline_decision import (
    OutcomeKey,
    ScorelineCandidate,
    ScorelineDecision,
    _candidates_from_matrix,
    _group_candidates,
    _rank_outcomes,
)

OPPONENT_SCORE_THRESHOLD = 0.55
CLOSE_PROBABILITY_PP = 3.0
SEVERE_OPPONENT_SCORE_THRESHOLD = 0.60


def _replace_primary(
    decision: ScorelineDecision,
    new_primary: ScorelineCandidate,
    *,
    reason: str,
) -> ScorelineDecision:
    top_exact_label = (
        decision.top_exact_score_overall.score_label
        if decision.top_exact_score_overall
        else ""
    )
    warnings = list(decision.warnings)
    if reason not in warnings:
        warnings.append(reason)
    primary_warnings = list(decision.primary_score_warnings)
    if reason not in primary_warnings:
        primary_warnings.append(reason)
    return replace(
        decision,
        primary_predicted_score=new_primary,
        primary_score_reason=f"{decision.primary_score_reason}; {reason}",
        top_exact_score_differs_from_primary=new_primary.score_label != top_exact_label,
        warnings=warnings,
        primary_score_warnings=primary_warnings,
    )


def _favorite_side(predicted_bucket: OutcomeKey) -> str | None:
    if predicted_bucket == "home_win":
        return "home"
    if predicted_bucket == "away_win":
        return "away"
    return None


def _is_favorite_clean_sheet(
    primary: ScorelineCandidate,
    predicted_bucket: OutcomeKey,
) -> bool:
    if predicted_bucket == "home_win":
        return primary.home_goals > primary.away_goals and primary.away_goals == 0
    if predicted_bucket == "away_win":
        return primary.away_goals > primary.home_goals and primary.home_goals == 0
    return False


def apply_matchup_relative_scoreline_guards(
    *,
    scoreline_decision: ScorelineDecision,
    probabilities_1x2: dict[str, float],
    top_scores: list[Any],
    all_scores: dict[str, float] | None,
    home_xg: float,
    away_xg: float,
) -> tuple[ScorelineDecision, dict[str, Any]]:
    """Align MR primary score with top 1X2 bucket; guard clean-sheet contradictions."""
    diagnostics: dict[str, Any] = {
        "primary_score_adjusted_to_match_1x2": False,
        "clean_sheet_primary_adjusted": False,
        "clean_sheet_primary_warning": False,
    }
    decision = scoreline_decision
    primary = decision.primary_predicted_score
    if primary is None:
        return decision, diagnostics

    predicted_bucket, _, _, _, _ = _rank_outcomes(probabilities_1x2)
    original_primary_label = primary.score_label

    if primary.outcome != predicted_bucket:
        candidates = _candidates_from_matrix(all_scores, top_scores)
        groups = _group_candidates(candidates)
        replacement = (groups.get(predicted_bucket) or [None])[0]
        if replacement is not None:
            decision = _replace_primary(
                decision,
                replacement,
                reason="PRIMARY_SCORE_BUCKET_MISMATCH",
            )
            primary = replacement
            diagnostics.update(
                {
                    "primary_score_adjusted_to_match_1x2": True,
                    "original_primary_score": original_primary_label,
                    "adjusted_primary_score": replacement.score_label,
                    "predicted_outcome_bucket": predicted_bucket,
                    "primary_score_adjustment_reason": "PRIMARY_SCORE_BUCKET_MISMATCH",
                }
            )

    favorite_side = _favorite_side(predicted_bucket)
    if favorite_side and primary is not None and _is_favorite_clean_sheet(
        primary, predicted_bucket
    ):
        opponent_xg = away_xg if favorite_side == "home" else home_xg
        opponent_p_score = _poisson_scores_probability(opponent_xg) / 100.0
        diagnostics["opponent_score_probability"] = round(opponent_p_score * 100.0, 2)

        if opponent_p_score >= OPPONENT_SCORE_THRESHOLD:
            candidates = _candidates_from_matrix(all_scores, top_scores)
            groups = _group_candidates(candidates)
            bucket_candidates = groups.get(predicted_bucket, [])
            original_prob = primary.probability
            btts_alts = [
                candidate
                for candidate in bucket_candidates
                if candidate.home_goals > 0
                and candidate.away_goals > 0
                and candidate.score_label != primary.score_label
            ]
            btts_alts.sort(key=lambda candidate: candidate.probability, reverse=True)

            chosen: ScorelineCandidate | None = None
            for alt in btts_alts:
                if alt.probability >= original_prob - CLOSE_PROBABILITY_PP:
                    chosen = alt
                    break
            if (
                chosen is None
                and btts_alts
                and opponent_p_score >= SEVERE_OPPONENT_SCORE_THRESHOLD
            ):
                chosen = btts_alts[0]

            if chosen is not None:
                pre_adjust_label = primary.score_label
                decision = _replace_primary(
                    decision,
                    chosen,
                    reason="PRIMARY_CLEAN_SHEET_CONFLICTS_WITH_OPPONENT_SCORE_PROBABILITY",
                )
                diagnostics.update(
                    {
                        "clean_sheet_primary_adjusted": True,
                        "original_primary_score": pre_adjust_label,
                        "adjusted_primary_score": chosen.score_label,
                        "clean_sheet_adjustment_reason": (
                            "PRIMARY_CLEAN_SHEET_CONFLICTS_WITH_OPPONENT_SCORE_PROBABILITY"
                        ),
                    }
                )
            else:
                diagnostics.update(
                    {
                        "clean_sheet_primary_warning": True,
                        "clean_sheet_warning_reason": "PRIMARY_CLEAN_SHEET_LOW_CONFIDENCE",
                    }
                )

    return decision, diagnostics
