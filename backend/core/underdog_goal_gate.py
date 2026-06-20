"""Phase 4Q.1 — Underdog goal permission gate for representative primary score."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from core.recent_scoring_form import RecentScoringFormMetrics, get_recent_scoring_form

OutcomeKey = Literal["home_win", "draw", "away_win"]
FavoriteClass = Literal[
    "elite_favorite",
    "strong_favorite",
    "normal_favorite",
    "weak_or_balanced_favorite",
]
GateLevel = Literal["BLOCK", "WEAK_ALLOW", "ALLOW", "STRONG_ALLOW", "BALANCED"]

UNDERDOG_GOAL_BLOCKED_LOW_XG = "UNDERDOG_GOAL_BLOCKED_LOW_XG"
UNDERDOG_GOAL_BLOCKED_LOW_MATRIX_PROB = "UNDERDOG_GOAL_BLOCKED_LOW_MATRIX_PROB"
UNDERDOG_GOAL_BLOCKED_LOW_BTTS = "UNDERDOG_GOAL_BLOCKED_LOW_BTTS"
UNDERDOG_GOAL_BLOCKED_ELITE_FAVORITE = "UNDERDOG_GOAL_BLOCKED_ELITE_FAVORITE"
UNDERDOG_GOAL_BLOCKED_WEAK_RECENT_FORM = "UNDERDOG_GOAL_BLOCKED_WEAK_RECENT_FORM"
UNDERDOG_GOAL_ALLOWED_BY_STRONG_FORM = "UNDERDOG_GOAL_ALLOWED_BY_STRONG_FORM"
UNDERDOG_GOAL_ALLOWED_BALANCED_MATCH = "UNDERDOG_GOAL_ALLOWED_BALANCED_MATCH"
UNDERDOG_GOAL_ALLOWED_CLOSE_CANDIDATE = "UNDERDOG_GOAL_ALLOWED_CLOSE_CANDIDATE"
UNDERDOG_GOAL_REJECTED_CANDIDATE_TOO_FAR = "UNDERDOG_GOAL_REJECTED_CANDIDATE_TOO_FAR"
RECENT_FORM_UNAVAILABLE = "RECENT_FORM_UNAVAILABLE"
RECENT_FORM_LOW_CONFIDENCE = "RECENT_FORM_LOW_CONFIDENCE"

CLEAR_UNDERDOG_MIN_FAV_PROB = 45.0
CLEAR_UNDERDOG_MIN_MARGIN = 8.0

THRESHOLD_BY_CLASS: dict[FavoriteClass, float] = {
    "weak_or_balanced_favorite": 45.0,
    "normal_favorite": 55.0,
    "strong_favorite": 65.0,
    "elite_favorite": 75.0,
}

LARGE_CANDIDATE_PROB_GAP = 3.5
CLOSE_CANDIDATE_PROB_GAP = 1.5


@dataclass(frozen=True)
class UnderdogMatchContext:
    favorite_team: str
    underdog_team: str
    favorite_side: Literal["home", "away", "none"]
    underdog_side: Literal["home", "away", "none"]
    favorite_win_probability: float
    underdog_win_probability: float
    draw_probability: float
    outcome_margin: float
    is_balanced: bool
    favorite_class: FavoriteClass
    favorite_power: float
    underdog_power: float
    power_gap: float
    underdog_xg: float


@dataclass(frozen=True)
class UnderdogGoalGateResult:
    level: GateLevel
    support_score: float
    threshold: float
    favorite_class: FavoriteClass
    underdog_xg: float
    underdog_scores_probability: float
    both_teams_score_probability: float
    recent_form_available: bool
    recent_form_confidence: str
    last_10_scored_rate: float | None
    last_10_goals_for_avg: float | None
    last_10_failed_to_score_rate: float | None
    scored_vs_similar_or_stronger_opponents: float | None
    reason_codes: list[str]
    # Phase 4R.1 diagnostics (do not affect gate level)
    recent_form_source: str | None = None
    recent_form_source_breakdown: dict[str, int] | None = None
    recent_form_reason_codes: list[str] | None = None
    matches_found: int | None = None
    requested_match_count: int | None = None
    last_10_goals_against_avg: float | None = None
    scored_vs_similar_or_stronger_opponents_rate: float | None = None
    scored_vs_strong_opponents_matches: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _recent_form_diagnostics(form: RecentScoringFormMetrics) -> dict[str, Any]:
    return {
        "recent_form_source": form.recent_form_source,
        "recent_form_source_breakdown": form.source_breakdown or {},
        "recent_form_reason_codes": form.reason_codes or [],
        "matches_found": form.matches_found,
        "requested_match_count": form.requested_match_count,
        "last_10_goals_against_avg": form.last_10_goals_against_avg,
        "scored_vs_similar_or_stronger_opponents_rate": (
            form.scored_vs_similar_or_stronger_opponents_rate
        ),
        "scored_vs_strong_opponents_matches": form.scored_vs_strong_opponents_matches,
    }


@dataclass(frozen=True)
class CandidateComparisonSummary:
    best_clean_sheet_candidate: str | None
    best_underdog_goal_candidate: str | None
    exact_probability_gap: float | None
    representative_score_gap: float | None
    selected_candidate: str | None
    why_selected: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_favorite_strength(
    *,
    favorite_power: float,
    power_gap: float,
    is_balanced: bool,
) -> FavoriteClass:
    if is_balanced or abs(power_gap) < 60:
        return "weak_or_balanced_favorite"
    gap = abs(power_gap)
    if favorite_power >= 900 or gap >= 180:
        return "elite_favorite"
    if favorite_power >= 830 or gap >= 120:
        return "strong_favorite"
    if favorite_power >= 760 or gap >= 60:
        return "normal_favorite"
    return "weak_or_balanced_favorite"


def build_underdog_match_context(
    *,
    favorite_outcome: OutcomeKey,
    probabilities_1x2: dict[str, float],
    home_team: str,
    away_team: str,
    home_xg: float,
    away_xg: float,
    favorite_power: float,
    underdog_power: float,
    power_gap: float,
) -> UnderdogMatchContext | None:
    home_win = float(probabilities_1x2.get("home_win", 0))
    draw = float(probabilities_1x2.get("draw", 0))
    away_win = float(probabilities_1x2.get("away_win", 0))

    if favorite_outcome == "draw":
        fav_prob = draw
        underdog_prob = min(home_win, away_win)
        margin = fav_prob - max(home_win, away_win)
        is_balanced = True
        favorite_side: Literal["home", "away", "none"] = "none"
        underdog_side: Literal["home", "away", "none"] = "none"
        favorite_team = ""
        underdog_team = ""
        underdog_xg = min(home_xg, away_xg)
    elif favorite_outcome == "home_win":
        fav_prob = home_win
        underdog_prob = away_win
        margin = fav_prob - max(draw, away_win)
        is_balanced = fav_prob < CLEAR_UNDERDOG_MIN_FAV_PROB or margin < CLEAR_UNDERDOG_MIN_MARGIN
        favorite_side = "home"
        underdog_side = "away"
        favorite_team = home_team
        underdog_team = away_team
        underdog_xg = away_xg
    else:
        fav_prob = away_win
        underdog_prob = home_win
        margin = fav_prob - max(draw, home_win)
        is_balanced = fav_prob < CLEAR_UNDERDOG_MIN_FAV_PROB or margin < CLEAR_UNDERDOG_MIN_MARGIN
        favorite_side = "away"
        underdog_side = "home"
        favorite_team = away_team
        underdog_team = home_team
        underdog_xg = home_xg

    fav_class = classify_favorite_strength(
        favorite_power=favorite_power,
        power_gap=power_gap if favorite_outcome == "home_win" else -power_gap
        if favorite_outcome == "away_win"
        else power_gap,
        is_balanced=is_balanced,
    )

    return UnderdogMatchContext(
        favorite_team=favorite_team,
        underdog_team=underdog_team,
        favorite_side=favorite_side,
        underdog_side=underdog_side,
        favorite_win_probability=round(fav_prob, 2),
        underdog_win_probability=round(underdog_prob, 2),
        draw_probability=round(draw, 2),
        outcome_margin=round(margin, 2),
        is_balanced=is_balanced,
        favorite_class=fav_class,
        favorite_power=round(favorite_power, 2),
        underdog_power=round(underdog_power, 2),
        power_gap=round(power_gap, 2),
        underdog_xg=round(underdog_xg, 2),
    )


def _score_points_underdog_xg(xg: float) -> float:
    if xg < 0.55:
        return 0.0
    if xg < 0.75:
        return 8.0 + (xg - 0.55) / 0.20 * 7.0
    if xg < 1.05:
        return 15.0 + (xg - 0.75) / 0.30 * 7.0
    if xg < 1.35:
        return 22.0 + (xg - 1.05) / 0.30 * 3.0
    return min(25.0, 25.0 + (xg - 1.35) * 2.0)


def _score_points_matrix_prob(prob_pct: float) -> float:
    if prob_pct < 40:
        return prob_pct / 40.0 * 10.0
    if prob_pct < 50:
        return 10.0 + (prob_pct - 40) / 10.0 * 8.0
    if prob_pct < 60:
        return 18.0 + (prob_pct - 50) / 10.0 * 8.0
    return min(30.0, 26.0 + (prob_pct - 60) / 40.0 * 4.0)


def _score_points_btts(prob_pct: float) -> float:
    if prob_pct < 35:
        return prob_pct / 35.0 * 4.0
    if prob_pct < 45:
        return 4.0 + (prob_pct - 35) / 10.0 * 5.0
    if prob_pct < 55:
        return 9.0 + (prob_pct - 45) / 10.0 * 4.0
    return min(15.0, 13.0 + (prob_pct - 55) / 45.0 * 2.0)


def _score_points_recent_form(form: RecentScoringFormMetrics) -> tuple[float, list[str]]:
    codes: list[str] = []
    if not form.recent_form_available:
        codes.append(RECENT_FORM_UNAVAILABLE)
        return 0.0, codes
    if form.recent_form_confidence == "low":
        codes.append(RECENT_FORM_LOW_CONFIDENCE)
    rate = form.last_10_scored_rate or 0.0
    points = rate * 20.0
    if rate >= 0.5:
        codes.append(UNDERDOG_GOAL_ALLOWED_BY_STRONG_FORM)
    elif rate <= 0.3:
        codes.append(UNDERDOG_GOAL_BLOCKED_WEAK_RECENT_FORM)
    return points, codes


def _strength_adjustment(favorite_class: FavoriteClass) -> float:
    return {
        "elite_favorite": -8.0,
        "strong_favorite": -4.0,
        "normal_favorite": 0.0,
        "weak_or_balanced_favorite": 3.0,
    }[favorite_class]


def compute_underdog_goal_gate(
    *,
    underdog_ctx: UnderdogMatchContext,
    underdog_scores_probability: float,
    btts_probability: float,
    recent_form: RecentScoringFormMetrics | None = None,
) -> UnderdogGoalGateResult:
    reason_codes: list[str] = []

    if underdog_ctx.is_balanced or underdog_ctx.favorite_side == "none":
        reason_codes.append(UNDERDOG_GOAL_ALLOWED_BALANCED_MATCH)
        return UnderdogGoalGateResult(
            level="BALANCED",
            support_score=0.0,
            threshold=THRESHOLD_BY_CLASS["weak_or_balanced_favorite"],
            favorite_class=underdog_ctx.favorite_class,
            underdog_xg=underdog_ctx.underdog_xg,
            underdog_scores_probability=underdog_scores_probability,
            both_teams_score_probability=btts_probability,
            recent_form_available=bool(recent_form and recent_form.recent_form_available),
            recent_form_confidence=(
                recent_form.recent_form_confidence if recent_form else "unavailable"
            ),
            last_10_scored_rate=recent_form.last_10_scored_rate if recent_form else None,
            last_10_goals_for_avg=recent_form.last_10_goals_for_avg if recent_form else None,
            last_10_failed_to_score_rate=(
                recent_form.last_10_failed_to_score_rate if recent_form else None
            ),
            scored_vs_similar_or_stronger_opponents=(
                recent_form.scored_vs_similar_or_stronger_opponents if recent_form else None
            ),
            reason_codes=reason_codes,
            **(_recent_form_diagnostics(recent_form) if recent_form else {}),
        )

    form = recent_form or get_recent_scoring_form(
        underdog_ctx.underdog_team,
        favorite_power=underdog_ctx.favorite_power,
    )

    xg_pts = _score_points_underdog_xg(underdog_ctx.underdog_xg)
    matrix_pts = _score_points_matrix_prob(underdog_scores_probability)
    btts_pts = _score_points_btts(btts_probability)
    form_pts, form_codes = _score_points_recent_form(form)
    reason_codes.extend(form_codes)

    if not form.recent_form_available:
        matrix_pts += 5.0
        btts_pts += 5.0

    strength_pts = 10.0 + _strength_adjustment(underdog_ctx.favorite_class)
    support_score = xg_pts + matrix_pts + form_pts + btts_pts + strength_pts

    threshold = THRESHOLD_BY_CLASS[underdog_ctx.favorite_class]

    if underdog_ctx.underdog_xg < 0.55:
        reason_codes.append(UNDERDOG_GOAL_BLOCKED_LOW_XG)
        support_score = min(support_score, threshold - 12)
    if underdog_scores_probability < 40:
        reason_codes.append(UNDERDOG_GOAL_BLOCKED_LOW_MATRIX_PROB)
        support_score = min(support_score, threshold - 8)
    if btts_probability < 35:
        reason_codes.append(UNDERDOG_GOAL_BLOCKED_LOW_BTTS)
        support_score = min(support_score, threshold - 6)
    if underdog_ctx.favorite_class == "elite_favorite" and (
        not form.recent_form_available or (form.last_10_scored_rate or 0) < 0.5
    ):
        reason_codes.append(UNDERDOG_GOAL_BLOCKED_ELITE_FAVORITE)
        support_score = min(support_score, threshold - 5)

    if support_score < threshold - 10:
        level: GateLevel = "BLOCK"
    elif support_score < threshold:
        level = "WEAK_ALLOW"
    elif support_score < threshold + 10:
        level = "ALLOW"
    else:
        level = "STRONG_ALLOW"

    if underdog_ctx.favorite_class == "elite_favorite":
        if underdog_ctx.underdog_xg < 1.0:
            if level in {"STRONG_ALLOW", "ALLOW"}:
                level = "WEAK_ALLOW"
            if underdog_ctx.underdog_xg < 0.75 and level == "WEAK_ALLOW":
                level = "BLOCK"
        if level == "STRONG_ALLOW" and (
            not form.recent_form_available or (form.last_10_scored_rate or 0) < 0.5
        ):
            level = "ALLOW"

    if underdog_ctx.favorite_class == "strong_favorite" and underdog_ctx.underdog_xg < 0.75:
        if level == "STRONG_ALLOW":
            level = "ALLOW"
        elif level == "ALLOW" and underdog_scores_probability < 55:
            level = "WEAK_ALLOW"

    return UnderdogGoalGateResult(
        level=level,
        support_score=round(support_score, 2),
        threshold=threshold,
        favorite_class=underdog_ctx.favorite_class,
        underdog_xg=underdog_ctx.underdog_xg,
        underdog_scores_probability=underdog_scores_probability,
        both_teams_score_probability=btts_probability,
        recent_form_available=form.recent_form_available,
        recent_form_confidence=form.recent_form_confidence,
        last_10_scored_rate=form.last_10_scored_rate,
        last_10_goals_for_avg=form.last_10_goals_for_avg,
        last_10_failed_to_score_rate=form.last_10_failed_to_score_rate,
        scored_vs_similar_or_stronger_opponents=form.scored_vs_similar_or_stronger_opponents,
        reason_codes=list(dict.fromkeys(reason_codes)),
        **_recent_form_diagnostics(form),
    )


def gate_candidate_adjustment(
    *,
    underdog_goals: int,
    gate: UnderdogGoalGateResult,
    clean_sheet_probability: float | None,
    candidate_probability: float,
) -> float:
    """Permission/penalty adjustment — not a universal BTTS bonus."""
    if underdog_goals == 0:
        if gate.level in {"BLOCK", "WEAK_ALLOW"}:
            return 0.04
        return 0.0

    prob_gap = (
        (clean_sheet_probability - candidate_probability)
        if clean_sheet_probability is not None
        else LARGE_CANDIDATE_PROB_GAP + 1.0
    )

    if gate.level == "BLOCK":
        return -0.42
    if gate.level == "WEAK_ALLOW":
        if prob_gap > CLOSE_CANDIDATE_PROB_GAP:
            return -0.32
        return -0.10
    if gate.level == "BALANCED":
        if prob_gap > 5.0:
            return -0.12
        return 0.0
    if gate.level == "ALLOW":
        if prob_gap > LARGE_CANDIDATE_PROB_GAP:
            return -0.18
        return 0.0
    # STRONG_ALLOW
    if prob_gap > LARGE_CANDIDATE_PROB_GAP + 1.0:
        return -0.15
    if prob_gap <= CLOSE_CANDIDATE_PROB_GAP:
        return 0.04
    return 0.0


def find_paired_clean_sheet(
    candidate_label: str,
    pool_by_label: dict[str, Any],
) -> Any | None:
    parts = candidate_label.split("-", 1)
    if len(parts) != 2:
        return None
    h, a = int(parts[0]), int(parts[1])
    if a == 0:
        return None
    paired = f"{h}-0"
    return pool_by_label.get(paired)


def build_candidate_comparison_summary(
    *,
    pool: list[Any],
    scored: list[tuple[Any, float]],
    selected: Any,
    gate: UnderdogGoalGateResult,
    favorite_outcome: OutcomeKey,
) -> CandidateComparisonSummary:
    def _dog_goals(c: Any) -> int:
        if favorite_outcome == "home_win":
            return c.away_goals
        if favorite_outcome == "away_win":
            return c.home_goals
        return min(c.home_goals, c.away_goals)

    clean = [c for c in pool if _dog_goals(c) == 0]
    dog = [c for c in pool if _dog_goals(c) >= 1]
    best_clean = max(clean, key=lambda c: c.probability) if clean else None
    best_dog = max(dog, key=lambda c: c.probability) if dog else None

    prob_gap = None
    rep_gap = None
    if best_clean and best_dog:
        prob_gap = round(best_clean.probability - best_dog.probability, 2)
        clean_rep = next((s for c, s in scored if c.score_label == best_clean.score_label), 0.0)
        dog_rep = next((s for c, s in scored if c.score_label == best_dog.score_label), 0.0)
        rep_gap = round(clean_rep - dog_rep, 4)

    why = f"gate={gate.level}, support={gate.support_score:.1f}/{gate.threshold:.0f}"
    if best_clean and best_dog:
        why += f", clean={best_clean.score_label} vs dog={best_dog.score_label}, prob_gap={prob_gap}"

    return CandidateComparisonSummary(
        best_clean_sheet_candidate=best_clean.score_label if best_clean else None,
        best_underdog_goal_candidate=best_dog.score_label if best_dog else None,
        exact_probability_gap=prob_gap,
        representative_score_gap=rep_gap,
        selected_candidate=selected.score_label if selected else None,
        why_selected=why,
    )
