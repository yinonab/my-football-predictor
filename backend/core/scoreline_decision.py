"""Phase 4M — Scoreline decision layer (display only; does not alter prediction math)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from core.fixture_state import FIXTURE_STATE_UNAVAILABLE, MATCH_ALREADY_COMPLETED
from core.match_context_diagnostics import MatchContextDiagnostics
import config
from core.recent_form_shadow import (
    evaluate_recent_form_shadow,
    gate_result_with_level,
)
from core.recent_scoring_form import get_recent_scoring_form
from core.strength_result import StrengthResult
from core.underdog_goal_gate import (
    LARGE_CANDIDATE_PROB_GAP,
    UNDERDOG_GOAL_ALLOWED_CLOSE_CANDIDATE,
    UNDERDOG_GOAL_REJECTED_CANDIDATE_TOO_FAR,
    CandidateComparisonSummary,
    UnderdogGoalGateResult,
    build_candidate_comparison_summary,
    build_underdog_match_context,
    compute_underdog_goal_gate,
    find_paired_clean_sheet,
    gate_candidate_adjustment,
)

OutcomeKey = Literal["home_win", "draw", "away_win"]

# Decision thresholds (percentage points)
BALANCED_MARGIN_PP = 5.0
CLEAR_FAVORITE_MARGIN_PP = 8.0
STRONG_FAVORITE_PROB = 60.0
HEAVY_FAVORITE_PROB = 70.0
CLOSE_SCORELINE_PP = 1.5
GROUP_TOP_N = 3

# Warning / advisory codes
BALANCED_MATCH_LOW_CONFIDENCE = "BALANCED_MATCH_LOW_CONFIDENCE"
PREDICTION_NOT_VALID = "PREDICTION_NOT_VALID"
CONTEXT_LIMITED = "CONTEXT_LIMITED"
SCORE_MATRIX_LIMITED = "SCORE_MATRIX_LIMITED"

# Phase 4Q — representative primary score realism warnings
PRIMARY_CLEAN_SHEET_WITH_UNDERDOG_XG_HIGH = "PRIMARY_CLEAN_SHEET_WITH_UNDERDOG_XG_HIGH"
PRIMARY_TOO_LOW_FOR_FAVORITE_XG = "PRIMARY_TOO_LOW_FOR_FAVORITE_XG"
PRIMARY_CAPPED_BELOW_EXPECTED_GOALS = "PRIMARY_CAPPED_BELOW_EXPECTED_GOALS"
PRIMARY_DIFFERS_FROM_TOP_EXACT_SCORE = "PRIMARY_DIFFERS_FROM_TOP_EXACT_SCORE"
HIGH_XG_BUT_LOW_PRIMARY_SCORE = "HIGH_XG_BUT_LOW_PRIMARY_SCORE"
UNDERDOG_GOAL_PROBABILITY_IGNORED = "UNDERDOG_GOAL_PROBABILITY_IGNORED"
EXPECTED_GOALS_REPRESENTATIVE_SELECTION = "EXPECTED_GOALS_REPRESENTATIVE_SELECTION"

REPRESENTATIVE_SCORE_METHOD = "representative_v3_expected_goals"
# Eligibility floor only — candidates below this cannot compete in the pool.
REPRESENTATIVE_CANDIDATE_ELIGIBILITY_REL = 0.35
REPRESENTATIVE_CANDIDATE_MIN_ABS = 1.0
REPRESENTATIVE_POOL_TOP_K = 20
UNDERDOG_XG_REPRESENTATIVE_THRESHOLD = 0.75
UNDERDOG_SCORES_PROB_CLEAN_SHEET_PENALTY = 0.35
EXPECTED_GOAL_TARGET_FIT_SCALE = 3.0

OUTCOME_KEYS: tuple[OutcomeKey, ...] = ("home_win", "draw", "away_win")

# Documented future weighted formula (not implemented in MVP):
# display_score =
#   0.55 * normalized_matrix_probability
# + 0.20 * outcome_alignment_score
# + 0.10 * xg_shape_fit
# + 0.10 * strength_gap_fit
# + 0.05 * context_fit


@dataclass(frozen=True)
class ScorelineCandidate:
    home_goals: int
    away_goals: int
    probability: float
    outcome: OutcomeKey

    @property
    def score_label(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "probability": round(self.probability, 2),
            "outcome": self.outcome,
        }


@dataclass
class ScorelineDecision:
    favorite_outcome: OutcomeKey
    favorite_outcome_probability: float
    second_outcome: OutcomeKey
    second_outcome_probability: float
    outcome_margin: float
    confidence_label: Literal["low", "medium", "high"]
    primary_predicted_score: ScorelineCandidate | None
    primary_score_reason: str
    top_exact_score_overall: ScorelineCandidate | None
    top_exact_score_differs_from_primary: bool
    favorite_outcome_top_scores: list[ScorelineCandidate] = field(default_factory=list)
    score_groups: dict[str, list[ScorelineCandidate]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    representative_score_method: str | None = None
    both_teams_score_probability: float | None = None
    underdog_scores_probability: float | None = None
    favorite_goal_band_probabilities: dict[str, float] = field(default_factory=dict)
    primary_score_warnings: list[str] = field(default_factory=list)
    primary_score_candidates: list[dict[str, Any]] = field(default_factory=list)
    selection_rationale: str = ""
    underdog_goal_gate: dict[str, Any] = field(default_factory=dict)
    candidate_comparison_summary: dict[str, Any] = field(default_factory=dict)
    recent_form_shadow: dict[str, Any] = field(default_factory=dict)
    representative_selection: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        primary = self.primary_predicted_score.to_dict() if self.primary_predicted_score else None
        top_exact = (
            self.top_exact_score_overall.to_dict() if self.top_exact_score_overall else None
        )
        payload: dict[str, Any] = {
            "favorite_outcome": self.favorite_outcome,
            "favorite_outcome_probability": round(self.favorite_outcome_probability, 2),
            "second_outcome": self.second_outcome,
            "second_outcome_probability": round(self.second_outcome_probability, 2),
            "outcome_margin": round(self.outcome_margin, 2),
            "confidence_label": self.confidence_label,
            "primary_predicted_score": primary,
            "primary_score_reason": self.primary_score_reason,
            "top_exact_score_overall": top_exact,
            "top_exact_score_differs_from_primary": self.top_exact_score_differs_from_primary,
            "favorite_outcome_top_scores": [c.to_dict() for c in self.favorite_outcome_top_scores],
            "score_groups": {
                key: [c.to_dict() for c in group]
                for key, group in self.score_groups.items()
            },
            "warnings": list(self.warnings),
        }
        if self.representative_score_method:
            payload["representative_score_method"] = self.representative_score_method
        if self.both_teams_score_probability is not None:
            payload["both_teams_score_probability"] = round(
                self.both_teams_score_probability, 2
            )
        if self.underdog_scores_probability is not None:
            payload["underdog_scores_probability"] = round(
                self.underdog_scores_probability, 2
            )
        if self.favorite_goal_band_probabilities:
            payload["favorite_goal_band_probabilities"] = {
                k: round(v, 2) for k, v in self.favorite_goal_band_probabilities.items()
            }
        if self.primary_score_warnings:
            payload["primary_score_warnings"] = list(self.primary_score_warnings)
        if self.primary_score_candidates:
            payload["primary_score_candidates"] = self.primary_score_candidates
        if self.selection_rationale:
            payload["selection_rationale"] = self.selection_rationale
        if self.underdog_goal_gate:
            payload["underdog_goal_gate"] = self.underdog_goal_gate
        if self.candidate_comparison_summary:
            payload["candidate_comparison_summary"] = self.candidate_comparison_summary
        if self.recent_form_shadow:
            payload["recent_form_shadow"] = self.recent_form_shadow
        if self.representative_selection:
            payload["representative_selection"] = self.representative_selection
        return payload


def _outcome_from_goals(home_goals: int, away_goals: int) -> OutcomeKey:
    if home_goals > away_goals:
        return "home_win"
    if away_goals > home_goals:
        return "away_win"
    return "draw"


def _parse_score(score: str, probability: float) -> ScorelineCandidate:
    parts = score.strip().split("-", 1)
    h, a = int(parts[0]), int(parts[1])
    return ScorelineCandidate(
        home_goals=h,
        away_goals=a,
        probability=float(probability),
        outcome=_outcome_from_goals(h, a),
    )


def _candidates_from_matrix(
    all_scores: dict[str, float] | None,
    top_scores: list[Any],
) -> list[ScorelineCandidate]:
    if all_scores:
        return [
            _parse_score(score, prob)
            for score, prob in sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
        ]
    return [_parse_score(item["score"], item["probability"]) for item in top_scores]


def _rank_outcomes(probabilities_1x2: dict[str, float]) -> tuple[OutcomeKey, float, OutcomeKey, float, float]:
    ordered = sorted(OUTCOME_KEYS, key=lambda k: float(probabilities_1x2.get(k, 0)), reverse=True)
    favorite = ordered[0]
    second = ordered[1]
    fav_prob = float(probabilities_1x2[favorite])
    second_prob = float(probabilities_1x2[second])
    return favorite, fav_prob, second, second_prob, fav_prob - second_prob


def _group_candidates(
    candidates: list[ScorelineCandidate],
) -> dict[OutcomeKey, list[ScorelineCandidate]]:
    groups: dict[OutcomeKey, list[ScorelineCandidate]] = {
        "home_win": [],
        "draw": [],
        "away_win": [],
    }
    for candidate in candidates:
        groups[candidate.outcome].append(candidate)
    for key in groups:
        groups[key].sort(key=lambda c: c.probability, reverse=True)
    return groups


def _favorite_volume_score_label(
    favorite: OutcomeKey,
    favorite_goals: int,
    underdog_goals: int,
) -> str:
    if favorite == "home_win":
        return f"{favorite_goals}-{underdog_goals}"
    if favorite == "away_win":
        return f"{underdog_goals}-{favorite_goals}"
    return ""


def _lookup_candidate(
    label: str,
    *,
    pool_by_label: dict[str, ScorelineCandidate],
    all_scores: dict[str, float] | None,
) -> ScorelineCandidate | None:
    cand = pool_by_label.get(label)
    if cand is not None:
        return cand
    if all_scores and label in all_scores:
        return _parse_score(label, all_scores[label])
    return None


def _representative_goal_target(xg: float) -> int:
    """Round-half-up goal target: 0.50+ xG pulls toward the next goal count."""
    return max(0, int(math.floor(xg + 0.5)))


def _expected_goal_target_fit(
    candidate: ScorelineCandidate,
    *,
    home_target_goals: int,
    away_target_goals: int,
) -> float:
    target_distance = abs(candidate.home_goals - home_target_goals) + abs(
        candidate.away_goals - away_target_goals
    )
    return max(0.0, 1.0 - target_distance / EXPECTED_GOAL_TARGET_FIT_SCALE)


def _realism_penalty(
    candidate: ScorelineCandidate,
    *,
    stats: MatrixStats,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
) -> float:
    """Penalties for scorelines that clash with matrix mass or xG expectations."""
    penalty = 0.0
    fav_goals, underdog_goals = _favorite_side_goals(candidate, favorite)
    fav_xg = home_xg if favorite == "home_win" else away_xg
    dog_xg = away_xg if favorite == "home_win" else home_xg
    fav_target = _representative_goal_target(fav_xg)
    dog_target = _representative_goal_target(dog_xg)

    if (
        underdog_goals == 0
        and dog_xg >= UNDERDOG_XG_REPRESENTATIVE_THRESHOLD
        and stats.underdog_scores_probability >= 40.0
    ):
        penalty += 0.10

    if fav_xg >= 1.7 and fav_goals < 2 and stats.favorite_scores_2_plus >= 45.0:
        penalty += 0.06

    if fav_goals < fav_target - 1 and stats.favorite_scores_3_plus >= 25.0:
        penalty += 0.05

    if underdog_goals == 0 and dog_target >= 2 and fav_goals >= 4:
        penalty += 0.08

    return penalty


def _build_representative_candidate_pool(
    pool: list[ScorelineCandidate],
    *,
    all_scores: dict[str, float] | None,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
) -> list[ScorelineCandidate]:
    """Eligible favorite-outcome candidates from the matrix; never invents scores."""
    ordered = sorted(pool, key=lambda c: c.probability, reverse=True)
    if not ordered:
        return []

    home_target = _representative_goal_target(home_xg)
    away_target = _representative_goal_target(away_xg)
    top_prob = ordered[0].probability
    threshold = max(
        REPRESENTATIVE_CANDIDATE_MIN_ABS,
        top_prob * REPRESENTATIVE_CANDIDATE_ELIGIBILITY_REL,
    )
    by_label: dict[str, ScorelineCandidate] = {c.score_label: c for c in ordered}
    shortlist = [c for c in ordered if c.probability >= threshold]

    if all_scores:
        pool_by_label = {c.score_label: c for c in pool}
        for h in range(max(0, home_target - 1), home_target + 2):
            for a in range(max(0, away_target - 1), away_target + 2):
                label = f"{h}-{a}"
                if label in by_label:
                    continue
                cand = _lookup_candidate(
                    label, pool_by_label=pool_by_label, all_scores=all_scores
                )
                if cand is None or cand.outcome != favorite:
                    continue
                if cand.probability >= REPRESENTATIVE_CANDIDATE_MIN_ABS:
                    by_label[label] = cand
                    shortlist.append(cand)

    deduped = sorted(
        {c.score_label: c for c in shortlist}.values(),
        key=lambda c: c.probability,
        reverse=True,
    )[:REPRESENTATIVE_POOL_TOP_K]
    return deduped if deduped else ordered[:REPRESENTATIVE_POOL_TOP_K]


def _compute_representative_utility(
    candidate: ScorelineCandidate,
    *,
    stats: MatrixStats,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
    home_target_goals: int,
    away_target_goals: int,
    max_prob: float,
    power_gap: float,
    context: MatchContextDiagnostics | None,
    gate: UnderdogGoalGateResult,
    pool_by_label: dict[str, ScorelineCandidate],
) -> tuple[float, dict[str, float]]:
    _, underdog_goals = _favorite_side_goals(candidate, favorite)

    prob_fit = candidate.probability / max_prob if max_prob > 0 else 0.0
    goal_target_fit = _expected_goal_target_fit(
        candidate,
        home_target_goals=home_target_goals,
        away_target_goals=away_target_goals,
    )
    xg_shape_fit = _normalize_fit(_xg_shape_fit(candidate, home_xg, away_xg))
    expected_total = home_xg + away_xg
    actual_total = candidate.home_goals + candidate.away_goals
    total_goals_fit = _normalize_fit(-abs(actual_total - expected_total))
    strength_fit = max(0.0, min(1.0, 0.5 + _strength_gap_fit(candidate, power_gap) / 20.0))
    context_fit = max(0.0, min(1.0, 0.5 + _context_fit(candidate, context)))

    paired_clean = find_paired_clean_sheet(candidate.score_label, pool_by_label)
    clean_prob = paired_clean.probability if paired_clean else None
    gate_adjustment = gate_candidate_adjustment(
        underdog_goals=underdog_goals,
        gate=gate,
        clean_sheet_probability=clean_prob,
        candidate_probability=candidate.probability,
    )
    realism_penalty_val = _realism_penalty(
        candidate,
        stats=stats,
        favorite=favorite,
        home_xg=home_xg,
        away_xg=away_xg,
    )

    composite = (
        0.22 * prob_fit
        + 0.34 * goal_target_fit
        + 0.14 * xg_shape_fit
        + 0.10 * total_goals_fit
        + 0.04 * strength_fit
        + 0.02 * context_fit
        - realism_penalty_val
        + gate_adjustment
    )

    components = {
        "candidate_probability_fit": round(prob_fit, 4),
        "expected_goal_target_fit": round(goal_target_fit, 4),
        "adjusted_xg_shape_fit": round(xg_shape_fit, 4),
        "total_goals_fit": round(total_goals_fit, 4),
        "realism_penalty": round(realism_penalty_val, 4),
        "gate_penalty": round(-gate_adjustment, 4),
        "composite": round(composite, 4),
    }
    return composite, components


def _confidence_label(
    *,
    balanced: bool,
    favorite_probability: float,
    outcome_margin: float,
    prediction_invalid: bool,
) -> Literal["low", "medium", "high"]:
    if prediction_invalid or balanced:
        return "low"
    if favorite_probability >= STRONG_FAVORITE_PROB:
        return "high"
    if outcome_margin >= CLEAR_FAVORITE_MARGIN_PP:
        return "medium"
    return "low"


def _xg_shape_fit(candidate: ScorelineCandidate, home_xg: float, away_xg: float) -> float:
    expected_margin = home_xg - away_xg
    actual_margin = candidate.home_goals - candidate.away_goals
    if candidate.outcome == "draw":
        target_total = home_xg + away_xg
        actual_total = candidate.home_goals + candidate.away_goals
        return -abs(actual_total - target_total)
    return -abs(actual_margin - expected_margin)


def _strength_gap_fit(candidate: ScorelineCandidate, power_gap: float) -> float:
    if abs(power_gap) < 1.0:
        return 0.0
    favorite_side = 1 if power_gap > 0 else -1
    margin = candidate.home_goals - candidate.away_goals
    if candidate.outcome == "draw":
        return -abs(power_gap) * 0.5
    if margin * favorite_side <= 0:
        return -abs(power_gap)
    return min(abs(margin), abs(power_gap) / 40.0)


def _context_fit(candidate: ScorelineCandidate, context: MatchContextDiagnostics | None) -> float:
    if context is None:
        return 0.0
    tilt = 0.0
    if context.host_advantage_applied and candidate.outcome == "home_win":
        tilt += 0.5
    if context.host_country_match and candidate.outcome == "home_win":
        tilt += 0.25
    if context.neutral_ground_requested and candidate.outcome == "home_win":
        tilt -= 0.1
    return tilt


@dataclass(frozen=True)
class MatrixStats:
    btts_probability: float
    underdog_scores_probability: float
    favorite_scores_2_plus: float
    favorite_scores_3_plus: float
    favorite_scores_4_plus: float
    expected_home_goals: float
    expected_away_goals: float
    expected_goal_difference: float
    upset_probability: float


def _compute_matrix_stats(
    all_scores: dict[str, float],
    favorite_outcome: OutcomeKey,
    probabilities_1x2: dict[str, float],
) -> MatrixStats:
    total_mass = sum(all_scores.values()) or 100.0
    scale = 100.0 / total_mass

    exp_home = 0.0
    exp_away = 0.0
    btts = 0.0
    home_scores = 0.0
    away_scores = 0.0
    home_2_plus = home_3_plus = home_4_plus = 0.0
    away_2_plus = away_3_plus = away_4_plus = 0.0

    for score, prob_pct in all_scores.items():
        prob = prob_pct * scale / 100.0
        parts = score.split("-", 1)
        h, a = int(parts[0]), int(parts[1])
        exp_home += h * prob
        exp_away += a * prob
        if h >= 1 and a >= 1:
            btts += prob
        if h >= 1:
            home_scores += prob
        if a >= 1:
            away_scores += prob
        if h >= 2:
            home_2_plus += prob
        if h >= 3:
            home_3_plus += prob
        if h >= 4:
            home_4_plus += prob
        if a >= 2:
            away_2_plus += prob
        if a >= 3:
            away_3_plus += prob
        if a >= 4:
            away_4_plus += prob

    if favorite_outcome == "home_win":
        underdog_scores = away_scores
        fav_2, fav_3, fav_4 = home_2_plus, home_3_plus, home_4_plus
        upset = probabilities_1x2.get("away_win", 0.0) / 100.0
    elif favorite_outcome == "away_win":
        underdog_scores = home_scores
        fav_2, fav_3, fav_4 = away_2_plus, away_3_plus, away_4_plus
        upset = probabilities_1x2.get("home_win", 0.0) / 100.0
    else:
        underdog_scores = min(home_scores, away_scores)
        fav_2 = fav_3 = fav_4 = 0.0
        upset = min(
            probabilities_1x2.get("home_win", 0.0),
            probabilities_1x2.get("away_win", 0.0),
        ) / 100.0

    return MatrixStats(
        btts_probability=round(btts * 100, 2),
        underdog_scores_probability=round(underdog_scores * 100, 2),
        favorite_scores_2_plus=round(fav_2 * 100, 2),
        favorite_scores_3_plus=round(fav_3 * 100, 2),
        favorite_scores_4_plus=round(fav_4 * 100, 2),
        expected_home_goals=round(exp_home, 3),
        expected_away_goals=round(exp_away, 3),
        expected_goal_difference=round(exp_home - exp_away, 3),
        upset_probability=round(upset * 100, 2),
    )


def _normalize_fit(raw: float, scale: float = 3.0) -> float:
    return max(0.0, min(1.0, 1.0 + raw / scale))


def _favorite_side_goals(
    candidate: ScorelineCandidate, favorite: OutcomeKey
) -> tuple[int, int]:
    if favorite == "home_win":
        return candidate.home_goals, candidate.away_goals
    if favorite == "away_win":
        return candidate.away_goals, candidate.home_goals
    return candidate.home_goals, candidate.away_goals


def _score_representative_candidates(
    pool: list[ScorelineCandidate],
    *,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
    power_gap: float,
    stats: MatrixStats,
    context: MatchContextDiagnostics | None,
    gate: UnderdogGoalGateResult,
    all_scores: dict[str, float] | None = None,
) -> tuple[
    ScorelineCandidate,
    float,
    ScorelineCandidate,
    float,
    list[tuple[ScorelineCandidate, float, dict[str, float]]],
    CandidateComparisonSummary,
]:
    shortlist = _build_representative_candidate_pool(
        pool,
        all_scores=all_scores,
        favorite=favorite,
        home_xg=home_xg,
        away_xg=away_xg,
    )
    modal = max(pool, key=lambda c: c.probability)
    pool_by_label = {c.score_label: c for c in pool}
    max_prob = max(c.probability for c in shortlist)
    home_target_goals = _representative_goal_target(home_xg)
    away_target_goals = _representative_goal_target(away_xg)
    scored: list[tuple[ScorelineCandidate, float, dict[str, float]]] = []
    for c in shortlist:
        composite, components = _compute_representative_utility(
            c,
            stats=stats,
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            home_target_goals=home_target_goals,
            away_target_goals=away_target_goals,
            max_prob=max_prob,
            power_gap=power_gap,
            context=context,
            gate=gate,
            pool_by_label=pool_by_label,
        )
        scored.append((c, composite, components))

    best, best_score, _ = max(scored, key=lambda item: item[1])
    modal_entry = next(
        (item for item in scored if item[0].score_label == modal.score_label),
        None,
    )
    modal_score = modal_entry[1] if modal_entry else 0.0
    comparison = build_candidate_comparison_summary(
        pool=pool,
        scored=[(c, s) for c, s, _ in scored],
        selected=best,
        gate=gate,
        favorite_outcome=favorite,
    )
    return best, best_score, modal, modal_score, scored, comparison


def _assess_primary_realism_warnings(
    primary: ScorelineCandidate,
    modal_favorite: ScorelineCandidate | None,
    *,
    stats: MatrixStats,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
    top_exact: ScorelineCandidate | None,
) -> list[str]:
    warnings: list[str] = []
    fav_goals, underdog_goals = _favorite_side_goals(primary, favorite)
    fav_xg = home_xg if favorite == "home_win" else away_xg
    dog_xg = away_xg if favorite == "home_win" else home_xg

    if (
        underdog_goals == 0
        and dog_xg >= UNDERDOG_XG_REPRESENTATIVE_THRESHOLD
        and stats.underdog_scores_probability >= 40.0
    ):
        warnings.append(PRIMARY_CLEAN_SHEET_WITH_UNDERDOG_XG_HIGH)

    if fav_xg >= 1.7 and fav_goals < 2 and stats.favorite_scores_2_plus >= 45.0:
        warnings.append(PRIMARY_TOO_LOW_FOR_FAVORITE_XG)

    if fav_xg >= 3.5 and fav_goals < round(fav_xg - 0.5) and stats.favorite_scores_3_plus >= 25.0:
        warnings.append(PRIMARY_CAPPED_BELOW_EXPECTED_GOALS)

    if fav_xg >= 3.5 and fav_goals <= 3 and stats.favorite_scores_4_plus >= 12.0:
        warnings.append(HIGH_XG_BUT_LOW_PRIMARY_SCORE)

    if (
        underdog_goals == 0
        and stats.underdog_scores_probability >= 50.0
        and stats.btts_probability >= 35.0
    ):
        warnings.append(UNDERDOG_GOAL_PROBABILITY_IGNORED)

    if top_exact and (
        primary.home_goals != top_exact.home_goals or primary.away_goals != top_exact.away_goals
    ):
        warnings.append(PRIMARY_DIFFERS_FROM_TOP_EXACT_SCORE)

    if modal_favorite and primary.score_label != modal_favorite.score_label:
        pass  # expected when representative beats modal favorite cell

    return warnings


def _pick_representative_score(
    pool: list[ScorelineCandidate],
    *,
    favorite: OutcomeKey,
    home_xg: float,
    away_xg: float,
    power_gap: float,
    all_scores: dict[str, float] | None,
    probabilities_1x2: dict[str, float],
    context: MatchContextDiagnostics | None,
    home_team: str,
    away_team: str,
    home_power: float,
    away_power: float,
) -> tuple[ScorelineCandidate | None, dict[str, Any]]:
    if not pool:
        return None, {}
    if not all_scores:
        return _pick_from_pool(
            pool,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            strong_or_heavy=True,
            context=context,
        ), {}

    stats = _compute_matrix_stats(all_scores, favorite, probabilities_1x2)
    if favorite == "home_win":
        fav_power, dog_power = home_power, away_power
    elif favorite == "away_win":
        fav_power, dog_power = away_power, home_power
    else:
        fav_power = max(home_power, away_power)
        dog_power = min(home_power, away_power)

    underdog_ctx = build_underdog_match_context(
        favorite_outcome=favorite,
        probabilities_1x2=probabilities_1x2,
        home_team=home_team,
        away_team=away_team,
        home_xg=home_xg,
        away_xg=away_xg,
        favorite_power=fav_power,
        underdog_power=dog_power,
        power_gap=power_gap,
    )
    recent_form = None
    if underdog_ctx and underdog_ctx.underdog_team:
        recent_form = get_recent_scoring_form(
            underdog_ctx.underdog_team,
            favorite_power=underdog_ctx.favorite_power,
        )
    gate = compute_underdog_goal_gate(
        underdog_ctx=underdog_ctx
        or build_underdog_match_context(
            favorite_outcome=favorite,
            probabilities_1x2=probabilities_1x2,
            home_team=home_team,
            away_team=away_team,
            home_xg=home_xg,
            away_xg=away_xg,
            favorite_power=fav_power,
            underdog_power=dog_power,
            power_gap=power_gap,
        ),
        underdog_scores_probability=stats.underdog_scores_probability,
        btts_probability=stats.btts_probability,
        recent_form=recent_form,
    )

    best, best_score, modal, modal_score, scored, comparison = _score_representative_candidates(
        pool,
        favorite=favorite,
        home_xg=home_xg,
        away_xg=away_xg,
        power_gap=power_gap,
        stats=stats,
        context=context,
        gate=gate,
        all_scores=all_scores,
    )

    shadow_primary: ScorelineCandidate | None = None
    active_gate = gate
    shadow_outcome = evaluate_recent_form_shadow(
        underdog_ctx=underdog_ctx,
        baseline_gate=gate,
        underdog_scores_probability=stats.underdog_scores_probability,
        btts_probability=stats.btts_probability,
        comparison=comparison,
        baseline_primary_label=best.score_label,
        shadow_primary_label=None,
    )

    if config.recent_form_shadow_enabled() and shadow_outcome.shadow_gate_level != gate.level:
        shadow_gate = gate_result_with_level(gate, shadow_outcome.shadow_gate_level)
        shadow_primary, _, _, _, _, _ = _score_representative_candidates(
            pool,
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            stats=stats,
            context=context,
            gate=shadow_gate,
            all_scores=all_scores,
        )
        shadow_outcome = evaluate_recent_form_shadow(
            underdog_ctx=underdog_ctx,
            baseline_gate=gate,
            underdog_scores_probability=stats.underdog_scores_probability,
            btts_probability=stats.btts_probability,
            comparison=comparison,
            baseline_primary_label=best.score_label,
            shadow_primary_label=shadow_primary.score_label,
        )

    if shadow_outcome.active_change_applied:
        active_gate = gate_result_with_level(
            gate,
            shadow_outcome.active_gate_level,
            extra_reason_codes=list(
                shadow_outcome.diagnostics.get("reason_codes") or []
            ),
        )
        best, best_score, modal, modal_score, scored, comparison = _score_representative_candidates(
            pool,
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            stats=stats,
            context=context,
            gate=active_gate,
            all_scores=all_scores,
        )

    home_target_goals = _representative_goal_target(home_xg)
    away_target_goals = _representative_goal_target(away_xg)
    modal_components = next(
        (components for c, _, components in scored if c.score_label == modal.score_label),
        {},
    )
    selected_components = next(
        (components for c, _, components in scored if c.score_label == best.score_label),
        {},
    )
    expected_goals_changed_selection = best.score_label != modal.score_label
    expected_goals_influenced = expected_goals_changed_selection and (
        selected_components.get("expected_goal_target_fit", 0.0)
        >= modal_components.get("expected_goal_target_fit", 0.0)
    )

    top_utilities = [
        {
            "score": c.score_label,
            "probability": round(c.probability, 2),
            "utility_components": components,
        }
        for c, _, components in sorted(scored, key=lambda item: item[1], reverse=True)[:5]
    ]
    representative_selection: dict[str, Any] = {
        "selected_primary_score": best.score_label,
        "previous_modal_score": modal.score_label,
        "modal_probability": round(modal.probability, 2),
        "selected_probability": round(best.probability, 2),
        "representative_score_method": REPRESENTATIVE_SCORE_METHOD,
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "home_target_goals": home_target_goals,
        "away_target_goals": away_target_goals,
        "expected_goals_target_changed_selection": expected_goals_changed_selection,
        "expected_goals_target_influenced": expected_goals_influenced,
        "top_candidate_utilities": top_utilities,
    }
    if expected_goals_influenced:
        representative_selection["selection_reason_code"] = (
            EXPECTED_GOALS_REPRESENTATIVE_SELECTION
        )

    rationale = (
        f"{REPRESENTATIVE_SCORE_METHOD}: selected {best.score_label} (composite={best_score:.3f}) "
        f"over modal {modal.score_label} ({modal_score:.3f}); "
        f"gate={active_gate.level} support={active_gate.support_score:.1f}/{active_gate.threshold:.0f}; "
        f"BTTS={stats.btts_probability:.1f}%, underdog scores={stats.underdog_scores_probability:.1f}%"
    )

    goal_bands = {
        "favorite_2_plus": stats.favorite_scores_2_plus,
        "favorite_3_plus": stats.favorite_scores_3_plus,
        "favorite_4_plus": stats.favorite_scores_4_plus,
    }
    candidate_preview = [
        {
            "score": c.score_label,
            "probability": round(c.probability, 2),
            "composite": components.get("composite", round(score, 4)),
            "utility_components": components,
        }
        for c, score, components in sorted(scored, key=lambda item: item[1], reverse=True)[:5]
    ]
    primary_warnings = _assess_primary_realism_warnings(
        best,
        modal,
        stats=stats,
        favorite=favorite,
        home_xg=home_xg,
        away_xg=away_xg,
        top_exact=None,
    )
    if expected_goals_influenced and EXPECTED_GOALS_REPRESENTATIVE_SELECTION not in primary_warnings:
        primary_warnings.append(EXPECTED_GOALS_REPRESENTATIVE_SELECTION)
    primary_warnings.extend(active_gate.reason_codes)
    if comparison.exact_probability_gap is not None:
        if comparison.exact_probability_gap <= CLOSE_SCORELINE_PP:
            primary_warnings.append(UNDERDOG_GOAL_ALLOWED_CLOSE_CANDIDATE)
        elif (
            best.score_label == comparison.best_underdog_goal_candidate
            and comparison.exact_probability_gap > LARGE_CANDIDATE_PROB_GAP
            and active_gate.level not in {"STRONG_ALLOW"}
        ):
            primary_warnings.append(UNDERDOG_GOAL_REJECTED_CANDIDATE_TOO_FAR)

    gate_payload = active_gate.to_dict()
    recent_form_shadow = shadow_outcome.diagnostics
    if recent_form_shadow:
        gate_payload["recent_form"] = recent_form_shadow

    diagnostics: dict[str, Any] = {
        "representative_score_method": REPRESENTATIVE_SCORE_METHOD,
        "both_teams_score_probability": stats.btts_probability,
        "underdog_scores_probability": stats.underdog_scores_probability,
        "favorite_goal_band_probabilities": goal_bands,
        "primary_score_warnings": list(dict.fromkeys(primary_warnings)),
        "primary_score_candidates": candidate_preview,
        "selection_rationale": rationale,
        "underdog_goal_gate": gate_payload,
        "candidate_comparison_summary": comparison.to_dict(),
        "recent_form_shadow": recent_form_shadow,
        "representative_selection": representative_selection,
    }
    return best, diagnostics


def _pick_from_pool(
    pool: list[ScorelineCandidate],
    *,
    home_xg: float,
    away_xg: float,
    power_gap: float,
    strong_or_heavy: bool,
    context: MatchContextDiagnostics | None,
) -> ScorelineCandidate | None:
    if not pool:
        return None
    ordered = sorted(pool, key=lambda c: c.probability, reverse=True)
    if len(ordered) == 1 or not strong_or_heavy:
        return ordered[0]
    top, second = ordered[0], ordered[1]
    if top.probability - second.probability > CLOSE_SCORELINE_PP:
        return top

    def composite(c: ScorelineCandidate) -> float:
        return (
            c.probability
            + 0.35 * _xg_shape_fit(c, home_xg, away_xg)
            + 0.25 * _strength_gap_fit(c, power_gap)
            + 0.05 * _context_fit(c, context)
        )

    return max([top, second], key=composite)


def _short_team_name(full_name: str) -> str:
    if "(" in full_name and ")" in full_name:
        return full_name.split("(")[1].rstrip(")").strip()
    return full_name


def _outcome_hebrew(outcome: OutcomeKey, home_team: str, away_team: str) -> str:
    home = _short_team_name(home_team)
    away = _short_team_name(away_team)
    if outcome == "home_win":
        return f"ניצחון {home}"
    if outcome == "away_win":
        return f"ניצחון {away}"
    return "תיקו"


def build_primary_score_reason(
    *,
    primary: ScorelineCandidate | None,
    top_exact: ScorelineCandidate | None,
    favorite_outcome: OutcomeKey,
    home_team: str,
    away_team: str,
    balanced: bool,
    differs: bool,
    context_limited: bool,
    prediction_invalid: bool,
    completed: bool,
) -> str:
    if prediction_invalid and completed:
        return (
            "המשחק כבר הסתיים — התחזית המרכזית אינה תחזית עתידית. "
            "התוצאה בפועל מופיעה בנתוני ההקשר של המשחק."
        )
    if prediction_invalid:
        return "תחזית זו אינה תקפה למשחק עתידי — נתוני מצב המשחק מגבילים את הביטחון."

    if balanced:
        base = "המשחק מאוזן יחסית, ולכן תחזית התוצאה המדויקת היא בביטחון נמוך."
        if differs and top_exact and primary:
            base += (
                f" התוצאה הבודדת הנפוצה ביותר במטריצה ({top_exact.score_label}) "
                "מייצגת תא יחיד ולא את סכום כל תרחישי התוצאה."
            )
        return base

    home = _short_team_name(home_team)
    away = _short_team_name(away_team)
    fav_label = _outcome_hebrew(favorite_outcome, home_team, away_team)

    if differs and top_exact and primary:
        if favorite_outcome == "home_win":
            return (
                f"{home} היא התרחיש הכללי המוביל, לכן התחזית המרכזית נבחרה מתוך תרחישי הניצחון של {home}. "
                f"{top_exact.score_label} עשויה להיות התוצאה הבודדת הנפוצה ביותר במטריצה, "
                f"אך בסיכום כל תרחישי הניצחון {home} עדיין הפייבוריטית."
            )
        if favorite_outcome == "away_win":
            return (
                f"{away} היא התרחיש הכללי המוביל, לכן התחזית המרכזית נבחרה מתוך תרחישי הניצחון של {away}. "
                f"{top_exact.score_label} עשויה להיות התוצאה הבודדת הנפוצה ביותר במטריצה, "
                "אך בסיכום כל תרחישי הניצחון עדיין מעדיפים את האורחת."
            )
        return (
            f"התיקו הוא התרחיש הכללי המוביל. התחזית המרכזית נבחרה מתוך תרחישי התיקו במטריצה. "
            f"{top_exact.score_label} עשויה להיות התוצאה הבודדת הנפוצה ביותר במטריצה, "
            "אך היא מייצגת תא יחיד ולא את סכום כל תרחישי התיקו."
        )

    if primary:
        return (
            f"התחזית המרכזית ({primary.score_label}) תואמת את התרחיש הכללי המוביל — {fav_label}."
        )

    return (
        "התחזית המרכזית נבחרה מתוך התרחיש המוביל. התוצאה הבודדת הנפוצה ביותר במטריצה "
        "יכולה להיות שונה, כי היא מייצגת תא יחיד ולא את סכום כל תרחישי הניצחון."
    )


def build_scoreline_decision(
    *,
    final_probabilities_1x2: dict[str, float],
    top_scores: list[Any],
    all_scores: dict[str, float] | None = None,
    home_xg: float,
    away_xg: float,
    home_team: str,
    away_team: str,
    strength: StrengthResult | None = None,
    match_context_diagnostics: MatchContextDiagnostics | None = None,
) -> ScorelineDecision:
    """
    Choose user-facing primary exact score from matrix + 1X2 favorite.

    Does not modify probabilities, xG, or top_scores.
    """
    warnings: list[str] = []
    favorite, fav_prob, second, second_prob, margin = _rank_outcomes(final_probabilities_1x2)
    balanced = margin <= BALANCED_MARGIN_PP
    clear_favorite = margin >= CLEAR_FAVORITE_MARGIN_PP
    strong_favorite = fav_prob >= STRONG_FAVORITE_PROB
    heavy_favorite = fav_prob >= HEAVY_FAVORITE_PROB

    candidates = _candidates_from_matrix(all_scores, top_scores)
    if not all_scores:
        warnings.append(SCORE_MATRIX_LIMITED)

    groups = _group_candidates(candidates)
    score_groups = {
        key: groups[key][:GROUP_TOP_N] for key in ("home_win", "draw", "away_win")
    }

    top_exact = candidates[0] if candidates else None
    favorite_pool = groups[favorite]
    favorite_outcome_top_scores = favorite_pool[:GROUP_TOP_N]

    ctx = match_context_diagnostics
    prediction_invalid = bool(ctx and not ctx.prediction_valid)
    completed = bool(ctx and ctx.fixture_status == "completed")

    if ctx:
        for code in ctx.warnings:
            if code not in warnings:
                warnings.append(code)

    context_limited = bool(
        ctx
        and (
            not ctx.fixture_source_available
            or not ctx.venue_context_available
            or FIXTURE_STATE_UNAVAILABLE in (ctx.warnings or [])
        )
    )

    if prediction_invalid:
        if PREDICTION_NOT_VALID not in warnings:
            warnings.append(PREDICTION_NOT_VALID)
        if completed and MATCH_ALREADY_COMPLETED not in warnings:
            warnings.append(MATCH_ALREADY_COMPLETED)

    if balanced and not prediction_invalid:
        if BALANCED_MATCH_LOW_CONFIDENCE not in warnings:
            warnings.append(BALANCED_MATCH_LOW_CONFIDENCE)

    if context_limited and CONTEXT_LIMITED not in warnings:
        warnings.append(CONTEXT_LIMITED)

    power_gap = strength.final_gap if strength else 0.0
    home_power = strength.final_home_power if strength else 700.0
    away_power = strength.final_away_power if strength else 700.0

    rep_diagnostics: dict[str, Any] = {}
    primary: ScorelineCandidate | None
    if prediction_invalid:
        primary = top_exact
    elif balanced:
        primary = top_exact
    elif clear_favorite or strong_favorite or heavy_favorite:
        primary, rep_diagnostics = _pick_representative_score(
            favorite_pool,
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            all_scores=all_scores,
            probabilities_1x2=final_probabilities_1x2,
            context=ctx,
            home_team=home_team,
            away_team=away_team,
            home_power=home_power,
            away_power=away_power,
        )
        if primary is None and top_exact:
            primary = top_exact
    else:
        primary, rep_diagnostics = _pick_representative_score(
            favorite_pool,
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            all_scores=all_scores,
            probabilities_1x2=final_probabilities_1x2,
            context=ctx,
            home_team=home_team,
            away_team=away_team,
            home_power=home_power,
            away_power=away_power,
        )
        if primary is None:
            primary = top_exact

    if rep_diagnostics.get("primary_score_warnings") and top_exact and primary:
        extra = _assess_primary_realism_warnings(
            primary,
            None,
            stats=_compute_matrix_stats(all_scores or {}, favorite, final_probabilities_1x2)
            if all_scores
            else MatrixStats(0, 0, 0, 0, 0, 0, 0, 0, 0),
            favorite=favorite,
            home_xg=home_xg,
            away_xg=away_xg,
            top_exact=top_exact,
        )
        merged = list(
            dict.fromkeys(rep_diagnostics.get("primary_score_warnings", []) + extra)
        )
        rep_diagnostics["primary_score_warnings"] = merged

    differs = bool(
        primary
        and top_exact
        and (
            primary.home_goals != top_exact.home_goals
            or primary.away_goals != top_exact.away_goals
        )
    )

    confidence = _confidence_label(
        balanced=balanced,
        favorite_probability=fav_prob,
        outcome_margin=margin,
        prediction_invalid=prediction_invalid,
    )
    if prediction_invalid:
        confidence = "low"

    reason = build_primary_score_reason(
        primary=primary,
        top_exact=top_exact,
        favorite_outcome=favorite,
        home_team=home_team,
        away_team=away_team,
        balanced=balanced,
        differs=differs,
        context_limited=context_limited,
        prediction_invalid=prediction_invalid,
        completed=completed,
    )
    if context_limited and not prediction_invalid:
        reason += " חלק מנתוני ההקשר של המשחק אינם זמינים, לכן התחזית מוגבלת הקשר."

    return ScorelineDecision(
        favorite_outcome=favorite,
        favorite_outcome_probability=fav_prob,
        second_outcome=second,
        second_outcome_probability=second_prob,
        outcome_margin=margin,
        confidence_label=confidence,
        primary_predicted_score=primary,
        primary_score_reason=reason,
        top_exact_score_overall=top_exact,
        top_exact_score_differs_from_primary=differs,
        favorite_outcome_top_scores=favorite_outcome_top_scores,
        score_groups=score_groups,
        warnings=warnings,
        representative_score_method=rep_diagnostics.get("representative_score_method"),
        both_teams_score_probability=rep_diagnostics.get("both_teams_score_probability"),
        underdog_scores_probability=rep_diagnostics.get("underdog_scores_probability"),
        favorite_goal_band_probabilities=rep_diagnostics.get(
            "favorite_goal_band_probabilities", {}
        ),
        primary_score_warnings=rep_diagnostics.get("primary_score_warnings", []),
        primary_score_candidates=rep_diagnostics.get("primary_score_candidates", []),
        selection_rationale=rep_diagnostics.get("selection_rationale", ""),
        underdog_goal_gate=rep_diagnostics.get("underdog_goal_gate", {}),
        candidate_comparison_summary=rep_diagnostics.get("candidate_comparison_summary", {}),
        recent_form_shadow=rep_diagnostics.get("recent_form_shadow", {}),
        representative_selection=rep_diagnostics.get("representative_selection", {}),
    )
