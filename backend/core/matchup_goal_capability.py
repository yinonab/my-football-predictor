"""Shadow diagnostics: matchup-relative goal capability (display only; no prediction impact)."""

from __future__ import annotations

import math
from typing import Any, Literal

from core.scoreline_decision import ScorelineDecision

CapabilityLevel = Literal["LOW", "MEDIUM", "HIGH"]


def _poisson_scores_probability(xg: float) -> float:
    return round((1.0 - math.exp(-max(float(xg), 0.0))) * 100.0, 2)


def _poisson_scores_at_least_probability(xg: float, goals: int) -> float:
    lam = max(float(xg), 0.0)
    cumulative = 0.0
    term = math.exp(-lam)
    for k in range(goals):
        cumulative += term
        term = term * lam / (k + 1)
    return round((1.0 - cumulative) * 100.0, 2)


def _poisson_btts_probability(home_xg: float, away_xg: float) -> float:
    p_home = (1.0 - math.exp(-max(float(home_xg), 0.0))) * 100.0
    p_away = (1.0 - math.exp(-max(float(away_xg), 0.0))) * 100.0
    return round((p_home / 100.0) * (p_away / 100.0) * 100.0, 2)


def _bucket_side_goal_capability(p_scores: float, xg: float) -> CapabilityLevel:
    if p_scores >= 50.0 or xg >= 0.75:
        return "HIGH"
    if p_scores >= 40.0 or xg >= 0.55:
        return "MEDIUM"
    return "LOW"


def _bucket_underdog_goal_capability(p_ud: float, ud_xg: float) -> CapabilityLevel:
    return _bucket_side_goal_capability(p_ud, ud_xg)


def _bucket_favorite_goal_capability(p_fav: float, fav_xg: float) -> CapabilityLevel:
    if fav_xg >= 1.8 or p_fav >= 75.0:
        return "HIGH"
    if fav_xg >= 1.2:
        return "MEDIUM"
    return "LOW"


def _bucket_favorite_multi_goal_capability(p_2_plus: float) -> CapabilityLevel:
    if p_2_plus >= 60.0:
        return "HIGH"
    if p_2_plus >= 45.0:
        return "MEDIUM"
    return "LOW"


def _bucket_favorite_clean_sheet_reliability(p_ud_scores: float) -> CapabilityLevel:
    if p_ud_scores < 35.0:
        return "HIGH"
    if p_ud_scores < 45.0:
        return "MEDIUM"
    return "LOW"


def _bucket_clean_sheet_risk(
    *,
    primary_is_favorite_clean_sheet: bool,
    p_ud_scores: float,
) -> CapabilityLevel:
    if not primary_is_favorite_clean_sheet:
        return "LOW"
    if p_ud_scores >= 45.0:
        return "HIGH"
    if p_ud_scores >= 35.0:
        return "MEDIUM"
    return "LOW"


def _bucket_btts_likelihood(p_btts: float) -> CapabilityLevel:
    if p_btts >= 50.0:
        return "HIGH"
    if p_btts >= 35.0:
        return "MEDIUM"
    return "LOW"


def _resolve_favorite_underdog(
    *,
    home_team: str,
    away_team: str,
    probabilities_1x2: dict[str, float],
    home_power: float | None,
    away_power: float | None,
    scoreline_decision: ScorelineDecision | None,
) -> tuple[str, str, str, str]:
    """Return (favorite_team, underdog_team, favorite_side, underdog_side). side is home|away."""
    favorite_outcome = (
        scoreline_decision.favorite_outcome if scoreline_decision else None
    )
    if favorite_outcome == "home":
        return home_team, away_team, "home", "away"
    if favorite_outcome == "away":
        return away_team, home_team, "away", "home"

    home_win = float(probabilities_1x2.get("home_win", 0.0))
    away_win = float(probabilities_1x2.get("away_win", 0.0))
    if home_win >= away_win:
        return home_team, away_team, "home", "away"
    return away_team, home_team, "away", "home"


def _primary_is_favorite_clean_sheet(
    scoreline_decision: ScorelineDecision | None,
    favorite_side: str,
) -> bool:
    if scoreline_decision is None or scoreline_decision.primary_predicted_score is None:
        return False
    primary = scoreline_decision.primary_predicted_score
    if favorite_side == "home":
        return primary.home_goals > 0 and primary.away_goals == 0
    return primary.away_goals > 0 and primary.home_goals == 0


def _level_hebrew(level: CapabilityLevel) -> str:
    return {"LOW": "נמוך", "MEDIUM": "בינוני", "HIGH": "גבוה"}[level]


def _short_team_name(full: str) -> str:
    if "(" in full and ")" in full:
        start = full.index("(") + 1
        end = full.index(")")
        inner = full[start:end].strip()
        if inner:
            return inner
    return full


def _build_summary(
    *,
    favorite_team: str,
    underdog_team: str,
    favorite_goal_capability: CapabilityLevel,
    underdog_goal_capability: CapabilityLevel,
    favorite_multi_goal_capability: CapabilityLevel,
    clean_sheet_risk: CapabilityLevel,
    btts_likelihood: CapabilityLevel,
    p_ud_scores: float,
    p_btts: float,
    primary_is_favorite_clean_sheet: bool,
) -> dict[str, str]:
    fav_short = _short_team_name(favorite_team)
    ud_short = _short_team_name(underdog_team)

    short_parts: list[str] = [
        f"יכולת {fav_short} להבקיע: {_level_hebrew(favorite_goal_capability)}",
        f"יכולת {ud_short} להבקיע: {_level_hebrew(underdog_goal_capability)}",
        f"סיכוי ש-{ud_short} תבקיע: {p_ud_scores:.0f}%",
    ]
    if primary_is_favorite_clean_sheet:
        short_parts.append(f"סיכון לשער נקי: {_level_hebrew(clean_sheet_risk)}")
    short_parts.append(f"שתי הקבוצות כובשות: {_level_hebrew(btts_likelihood)}")

    clean_sheet_text = ""
    if primary_is_favorite_clean_sheet and clean_sheet_risk in ("HIGH", "MEDIUM"):
        clean_sheet_text = (
            "הפייבוריט עדיין מוביל בתחזית, אבל שער נקי אינו בטוח."
        )

    underdog_text = ""
    if underdog_goal_capability == "HIGH":
        underdog_text = "לאנדרדוג יש סיכוי משמעותי להבקיע במשחק הזה."
    elif underdog_goal_capability == "MEDIUM":
        underdog_text = "לאנדרדוג יש סיכוי סביר להבקיע במשחק הזה."

    favorite_text = ""
    if favorite_multi_goal_capability == "HIGH":
        favorite_text = "לפייבוריט יש יכולת טובה להגיע ל-2+ שערים."

    return {
        "title": "יכולת הבקעה לפי מפגש",
        "short_text": " · ".join(short_parts),
        "clean_sheet_text": clean_sheet_text,
        "underdog_text": underdog_text,
        "favorite_text": favorite_text,
    }


def _build_reason_codes(
    *,
    underdog_goal_capability: CapabilityLevel,
    underdog_xg: float,
    btts_likelihood: CapabilityLevel,
    btts_probability: float,
    favorite_multi_goal_capability: CapabilityLevel,
    clean_sheet_risk: CapabilityLevel,
) -> list[str]:
    codes: list[str] = []
    if underdog_goal_capability in ("HIGH", "MEDIUM") or underdog_xg >= 0.55:
        codes.append("UNDERDOG_XG_MEANINGFUL")
    if btts_likelihood in ("HIGH", "MEDIUM") or btts_probability >= 35.0:
        codes.append("BTTS_PROBABILITY_MEANINGFUL")
    if favorite_multi_goal_capability == "HIGH":
        codes.append("FAVORITE_MULTI_GOAL_PROBABILITY_HIGH")
    if clean_sheet_risk in ("HIGH", "MEDIUM"):
        codes.append("FAVORITE_CLEAN_SHEET_RISKY")
    return codes


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_matchup_goal_capability(
    *,
    home_team: str,
    away_team: str,
    served_home_xg: float,
    served_away_xg: float,
    maher_reference_home_xg: float | None,
    maher_reference_away_xg: float | None,
    home_attack_rating: float | None,
    home_defense_rating: float | None,
    away_attack_rating: float | None,
    away_defense_rating: float | None,
    home_gf_per_game: float | None,
    home_ga_per_game: float | None,
    away_gf_per_game: float | None,
    away_ga_per_game: float | None,
    home_power: float | None,
    away_power: float | None,
    probabilities_1x2: dict[str, float],
    scoreline_decision: ScorelineDecision | None,
    active_model: str,
) -> dict[str, Any]:
    favorite_team, underdog_team, favorite_side, underdog_side = _resolve_favorite_underdog(
        home_team=home_team,
        away_team=away_team,
        probabilities_1x2=probabilities_1x2,
        home_power=home_power,
        away_power=away_power,
        scoreline_decision=scoreline_decision,
    )

    fav_xg = served_home_xg if favorite_side == "home" else served_away_xg
    ud_xg = served_away_xg if favorite_side == "home" else served_home_xg

    p_home_scores = _poisson_scores_probability(served_home_xg)
    p_away_scores = _poisson_scores_probability(served_away_xg)
    p_fav_scores = p_home_scores if favorite_side == "home" else p_away_scores
    p_ud_scores = (
        float(scoreline_decision.underdog_scores_probability)
        if scoreline_decision and scoreline_decision.underdog_scores_probability is not None
        else (p_away_scores if favorite_side == "home" else p_home_scores)
    )

    goal_bands = (
        scoreline_decision.favorite_goal_band_probabilities
        if scoreline_decision
        else {}
    )
    p_fav_2_plus = float(goal_bands.get("favorite_2_plus", 0.0))
    p_fav_3_plus = float(goal_bands.get("favorite_3_plus", 0.0))
    if p_fav_2_plus <= 0.0:
        p_fav_2_plus = _poisson_scores_at_least_probability(fav_xg, 2)
    if p_fav_3_plus <= 0.0:
        p_fav_3_plus = _poisson_scores_at_least_probability(fav_xg, 3)

    p_btts = _poisson_btts_probability(served_home_xg, served_away_xg)

    home_goal_capability = _bucket_side_goal_capability(p_home_scores, served_home_xg)
    away_goal_capability = _bucket_side_goal_capability(p_away_scores, served_away_xg)
    favorite_goal_capability = _bucket_favorite_goal_capability(p_fav_scores, fav_xg)
    underdog_goal_capability = _bucket_underdog_goal_capability(p_ud_scores, ud_xg)
    favorite_multi_goal_capability = _bucket_favorite_multi_goal_capability(p_fav_2_plus)
    favorite_clean_sheet_reliability = _bucket_favorite_clean_sheet_reliability(p_ud_scores)

    primary_clean_sheet = _primary_is_favorite_clean_sheet(
        scoreline_decision, favorite_side
    )
    clean_sheet_risk = _bucket_clean_sheet_risk(
        primary_is_favorite_clean_sheet=primary_clean_sheet,
        p_ud_scores=p_ud_scores,
    )
    btts_likelihood = _bucket_btts_likelihood(p_btts)

    power_gap = None
    if home_power is not None and away_power is not None:
        power_gap = round(float(home_power) - float(away_power), 2)

    summary = _build_summary(
        favorite_team=favorite_team,
        underdog_team=underdog_team,
        favorite_goal_capability=favorite_goal_capability,
        underdog_goal_capability=underdog_goal_capability,
        favorite_multi_goal_capability=favorite_multi_goal_capability,
        clean_sheet_risk=clean_sheet_risk,
        btts_likelihood=btts_likelihood,
        p_ud_scores=p_ud_scores,
        p_btts=p_btts,
        primary_is_favorite_clean_sheet=primary_clean_sheet,
    )

    reason_codes = _build_reason_codes(
        underdog_goal_capability=underdog_goal_capability,
        underdog_xg=ud_xg,
        btts_likelihood=btts_likelihood,
        btts_probability=p_btts,
        favorite_multi_goal_capability=favorite_multi_goal_capability,
        clean_sheet_risk=clean_sheet_risk,
    )

    return {
        "active_model": active_model,
        "home_team": home_team,
        "away_team": away_team,
        "favorite_team": favorite_team,
        "underdog_team": underdog_team,
        "home_goal_capability": home_goal_capability,
        "away_goal_capability": away_goal_capability,
        "favorite_goal_capability": favorite_goal_capability,
        "underdog_goal_capability": underdog_goal_capability,
        "favorite_multi_goal_capability": favorite_multi_goal_capability,
        "favorite_clean_sheet_reliability": favorite_clean_sheet_reliability,
        "clean_sheet_risk": clean_sheet_risk,
        "btts_likelihood": btts_likelihood,
        "probabilities": {
            "home_scores_probability": p_home_scores,
            "away_scores_probability": p_away_scores,
            "favorite_scores_probability": p_fav_scores,
            "underdog_scores_probability": p_ud_scores,
            "favorite_scores_2_plus_probability": round(p_fav_2_plus, 2),
            "favorite_scores_3_plus_probability": round(p_fav_3_plus, 2),
            "btts_probability": round(p_btts, 2),
        },
        "matchup_inputs": {
            "served_home_xg": round(float(served_home_xg), 2),
            "served_away_xg": round(float(served_away_xg), 2),
            "maher_reference_home_xg": _safe_float(maher_reference_home_xg),
            "maher_reference_away_xg": _safe_float(maher_reference_away_xg),
            "home_attack_rating": _safe_float(home_attack_rating),
            "home_defense_rating": _safe_float(home_defense_rating),
            "away_attack_rating": _safe_float(away_attack_rating),
            "away_defense_rating": _safe_float(away_defense_rating),
            "home_gf_per_game": _safe_float(home_gf_per_game),
            "home_ga_per_game": _safe_float(home_ga_per_game),
            "away_gf_per_game": _safe_float(away_gf_per_game),
            "away_ga_per_game": _safe_float(away_ga_per_game),
            "power_gap": power_gap,
        },
        "reason_codes": reason_codes,
        "summary": summary,
    }
