"""Phase 4M — Scoreline decision layer (display only; does not alter prediction math)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.fixture_state import FIXTURE_STATE_UNAVAILABLE, MATCH_ALREADY_COMPLETED
from core.match_context_diagnostics import MatchContextDiagnostics
from core.strength_result import StrengthResult

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

    def to_dict(self) -> dict[str, Any]:
        primary = self.primary_predicted_score.to_dict() if self.primary_predicted_score else None
        top_exact = (
            self.top_exact_score_overall.to_dict() if self.top_exact_score_overall else None
        )
        return {
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

    primary: ScorelineCandidate | None
    if prediction_invalid:
        primary = top_exact
    elif balanced:
        primary = top_exact
    elif clear_favorite or strong_favorite or heavy_favorite:
        primary = _pick_from_pool(
            favorite_pool,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            strong_or_heavy=strong_favorite or heavy_favorite,
            context=ctx,
        )
        if primary is None and top_exact:
            primary = top_exact
    else:
        primary = _pick_from_pool(
            favorite_pool,
            home_xg=home_xg,
            away_xg=away_xg,
            power_gap=power_gap,
            strong_or_heavy=False,
            context=ctx,
        ) or top_exact

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
    )
