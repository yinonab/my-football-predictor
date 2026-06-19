"""Phase 4D — Coherence checks between 1X2, xG, and top scores."""

from __future__ import annotations

from typing import Any

# Warning codes
PROBABILITY_SUM_INVALID = "PROBABILITY_SUM_INVALID"
ODDS_BLEND_APPLIED = "ODDS_BLEND_APPLIED"
ODDS_BLEND_1X2_SCORELINE_MISMATCH = "ODDS_BLEND_1X2_SCORELINE_MISMATCH"
FAVORITE_PROBABILITY_XG_MISMATCH = "FAVORITE_PROBABILITY_XG_MISMATCH"
TOP_SCORE_DIRECTION_MISMATCH = "TOP_SCORE_DIRECTION_MISMATCH"

PROB_SUM_MIN = 99.5
PROB_SUM_MAX = 100.2
BALANCED_FAVORITE_MAX_PROB = 45.0
XG_FAVORITE_MIN_DELTA = 0.12
MATERIAL_PROB_SHIFT_PP = 3.0
PROB_KEY_TOLERANCE = 0.06


def probability_sum(probabilities: dict[str, float]) -> float:
    return round(
        float(probabilities.get("home_win", 0))
        + float(probabilities.get("draw", 0))
        + float(probabilities.get("away_win", 0)),
        2,
    )


def probability_sum_valid(probabilities: dict[str, float]) -> bool:
    total = probability_sum(probabilities)
    return PROB_SUM_MIN <= total <= PROB_SUM_MAX


def favorite_from_1x2(probabilities: dict[str, float]) -> str | None:
    home = float(probabilities.get("home_win", 0))
    draw = float(probabilities.get("draw", 0))
    away = float(probabilities.get("away_win", 0))
    best = max(home, draw, away)
    if best < BALANCED_FAVORITE_MAX_PROB:
        return None
    if home >= draw and home >= away:
        return "home"
    if away >= draw and away >= home:
        return "away"
    return "draw"


def favorite_from_xg(
    home_xg: float,
    away_xg: float,
    *,
    min_delta: float = XG_FAVORITE_MIN_DELTA,
) -> str | None:
    delta = float(home_xg) - float(away_xg)
    if abs(delta) < min_delta:
        return None
    return "home" if delta > 0 else "away"


def _score_direction(score: str) -> str | None:
    if "-" not in score:
        return None
    parts = score.strip().split("-", 1)
    if len(parts) != 2:
        return None
    try:
        home_goals = int(parts[0])
        away_goals = int(parts[1])
    except ValueError:
        return None
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def favorite_from_top_scores(top_scores: list[Any]) -> str | None:
    if not top_scores:
        return None
    first = top_scores[0]
    score = first.get("score") if isinstance(first, dict) else getattr(first, "score", None)
    if not score:
        return None
    return _score_direction(str(score))


def _probabilities_differ(
    raw: dict[str, float],
    final: dict[str, float],
) -> bool:
    for key in ("home_win", "draw", "away_win"):
        if abs(float(raw.get(key, 0)) - float(final.get(key, 0))) > PROB_KEY_TOLERANCE:
            return True
    return False


def _favorite_changed(raw: dict[str, float], final: dict[str, float]) -> bool:
    raw_fav = favorite_from_1x2(raw)
    final_fav = favorite_from_1x2(final)
    if raw_fav is None or final_fav is None:
        return False
    return raw_fav != final_fav


def _material_prob_shift(raw: dict[str, float], final: dict[str, float]) -> bool:
    return any(
        abs(float(raw.get(key, 0)) - float(final.get(key, 0))) >= MATERIAL_PROB_SHIFT_PP
        for key in ("home_win", "draw", "away_win")
    )


def build_coherence_warnings(
    *,
    raw_probabilities_1x2: dict[str, float],
    final_probabilities_1x2: dict[str, float],
    home_xg: float,
    away_xg: float,
    top_scores: list[Any],
    odds_blend_applied: bool,
) -> list[str]:
    warnings: list[str] = []

    if not probability_sum_valid(final_probabilities_1x2):
        warnings.append(PROBABILITY_SUM_INVALID)

    if odds_blend_applied:
        warnings.append(ODDS_BLEND_APPLIED)

    fav_final = favorite_from_1x2(final_probabilities_1x2)
    fav_xg = favorite_from_xg(home_xg, away_xg)
    fav_top = favorite_from_top_scores(top_scores)

    if (
        fav_final is not None
        and fav_xg is not None
        and fav_final != "draw"
        and fav_xg != fav_final
    ):
        warnings.append(FAVORITE_PROBABILITY_XG_MISMATCH)

    if (
        fav_final is not None
        and fav_top is not None
        and fav_final != "draw"
        and fav_top != "draw"
        and fav_final != fav_top
    ):
        warnings.append(TOP_SCORE_DIRECTION_MISMATCH)

    if odds_blend_applied and (
        _favorite_changed(raw_probabilities_1x2, final_probabilities_1x2)
        or _material_prob_shift(raw_probabilities_1x2, final_probabilities_1x2)
    ):
        xg_points_other = fav_xg is not None and fav_final is not None and fav_xg != fav_final
        top_points_other = (
            fav_top is not None
            and fav_final is not None
            and fav_top != "draw"
            and fav_top != fav_final
        )
        if xg_points_other or top_points_other:
            warnings.append(ODDS_BLEND_1X2_SCORELINE_MISMATCH)

    return warnings


def detect_odds_blend_applied(
    raw_probabilities_1x2: dict[str, float],
    final_probabilities_1x2: dict[str, float],
    market_probabilities_1x2: dict[str, float] | None,
) -> bool:
    if market_probabilities_1x2 is None:
        return False
    return _probabilities_differ(raw_probabilities_1x2, final_probabilities_1x2)
