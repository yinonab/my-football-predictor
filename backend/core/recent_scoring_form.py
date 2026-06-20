"""Offline recent national-team scoring form (Phase 4R.1 normalized store)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from core.recent_match_history import (
    NormalizedRecentMatch,
    build_normalized_recent_match_history,
    get_team_recent_matches,
)
from data.database import FIFA_ELO_2026

RecentFormConfidence = Literal["high", "medium", "low", "unavailable"]

MIN_MATCHES_FOR_FORM = 3
FORM_WINDOW = 10

# Diagnostics reason codes (Phase 4R.1)
RECENT_FORM_HIGH_CONFIDENCE = "RECENT_FORM_HIGH_CONFIDENCE"
RECENT_FORM_MEDIUM_CONFIDENCE = "RECENT_FORM_MEDIUM_CONFIDENCE"
RECENT_FORM_LOW_CONFIDENCE = "RECENT_FORM_LOW_CONFIDENCE"
RECENT_FORM_UNAVAILABLE = "RECENT_FORM_UNAVAILABLE"
RECENT_FORM_STATIC_REAL_DATES_USED = "RECENT_FORM_STATIC_REAL_DATES_USED"
RECENT_FORM_STATIC_SYNTHETIC_DATES_USED = "RECENT_FORM_STATIC_SYNTHETIC_DATES_USED"
RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED = "RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED"
RECENT_FORM_OPPONENT_STRENGTH_UNAVAILABLE = "RECENT_FORM_OPPONENT_STRENGTH_UNAVAILABLE"

# Gate behavior unchanged in 4R.1 — diagnostics/store only until 4R.4
RECENT_FORM_AFFECTS_SCORELINE = False


@dataclass(frozen=True)
class RecentScoringFormMetrics:
    recent_form_available: bool
    recent_form_confidence: RecentFormConfidence
    last_10_scored_rate: float | None
    last_10_goals_for_avg: float | None
    last_10_failed_to_score_rate: float | None
    scored_vs_similar_or_stronger_opponents: float | None
    matches_used: int
    # Phase 4R.1 extended diagnostics
    team: str | None = None
    matches_found: int | None = None
    requested_match_count: int | None = None
    before_date: str | None = None
    scored_matches: int | None = None
    failed_to_score_matches: int | None = None
    last_10_goals_against_avg: float | None = None
    scored_vs_similar_or_stronger_opponents_rate: float | None = None
    scored_vs_strong_opponents_matches: int | None = None
    recent_form_source: str | None = None
    source_breakdown: dict[str, int] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _empty_metrics(
    *,
    team: str | None = None,
    matches_found: int = 0,
    before_date: str | None = None,
    window: int = FORM_WINDOW,
    reason_codes: list[str] | None = None,
) -> RecentScoringFormMetrics:
    codes = reason_codes or [RECENT_FORM_UNAVAILABLE]
    return RecentScoringFormMetrics(
        recent_form_available=False,
        recent_form_confidence="unavailable",
        last_10_scored_rate=None,
        last_10_goals_for_avg=None,
        last_10_failed_to_score_rate=None,
        scored_vs_similar_or_stronger_opponents=None,
        matches_used=matches_found,
        team=team,
        matches_found=matches_found,
        requested_match_count=window,
        before_date=before_date,
        scored_matches=0,
        failed_to_score_matches=0,
        last_10_goals_against_avg=None,
        scored_vs_similar_or_stronger_opponents_rate=None,
        scored_vs_strong_opponents_matches=0,
        recent_form_source="unavailable",
        source_breakdown={},
        reason_codes=codes,
    )


def _classify_confidence(
    matches: list[NormalizedRecentMatch],
) -> RecentFormConfidence:
    n = len(matches)
    if n <= 2:
        return "unavailable"
    if n <= 5:
        return "low"
    real_count = sum(1 for m in matches if m.date_confidence == "real")
    if n >= 8 and real_count >= 8:
        return "high"
    if n >= 6:
        return "medium"
    return "low"


def _primary_source_label(breakdown: dict[str, int]) -> str:
    if not breakdown:
        return "unavailable"
    top = max(breakdown.items(), key=lambda item: item[1])[0]
    if top.startswith("bundled_wc2026"):
        return "static_real_dated"
    if top.startswith("cache_"):
        return "api_cache_fresh"
    if top.startswith("bundled_"):
        return "static_synthetic"
    return top


def _build_reason_codes(
    confidence: RecentFormConfidence,
    matches: list[NormalizedRecentMatch],
    *,
    opponent_proxy_used: bool,
    opponent_proxy_unavailable: bool,
) -> list[str]:
    codes: list[str] = []
    if confidence == "high":
        codes.append(RECENT_FORM_HIGH_CONFIDENCE)
    elif confidence == "medium":
        codes.append(RECENT_FORM_MEDIUM_CONFIDENCE)
    elif confidence == "low":
        codes.append(RECENT_FORM_LOW_CONFIDENCE)
    else:
        codes.append(RECENT_FORM_UNAVAILABLE)

    if any(m.date_confidence == "real" for m in matches):
        codes.append(RECENT_FORM_STATIC_REAL_DATES_USED)
    if any(m.date_confidence == "synthetic" for m in matches):
        codes.append(RECENT_FORM_STATIC_SYNTHETIC_DATES_USED)
    if opponent_proxy_used:
        codes.append(RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED)
    if opponent_proxy_unavailable and matches:
        codes.append(RECENT_FORM_OPPONENT_STRENGTH_UNAVAILABLE)
    return list(dict.fromkeys(codes))


def get_recent_scoring_form(
    team_key: str,
    *,
    favorite_power: float | None = None,
    matches: list[NormalizedRecentMatch] | None = None,
    window: int = FORM_WINDOW,
    before_date: str | date | None = None,
    history: list[NormalizedRecentMatch] | None = None,
) -> RecentScoringFormMetrics:
    """
    Last-N scoring form from normalized offline match history.

    Uses static/bundled sources only (no live API). Gate scoring inputs
    (availability, scored rate) follow the same match window as Phase 4Q.1;
    confidence rules are stricter per Phase 4R architecture.
    """
    cutoff = str(before_date) if before_date is not None else None

    if not team_key or team_key not in FIFA_ELO_2026:
        return _empty_metrics(team=team_key, before_date=cutoff, window=window)

    if matches is not None:
        last_n = list(matches)[:window]
    else:
        last_n = get_team_recent_matches(
            team_key,
            before_date=cutoff,
            limit=window,
            history=history,
        )

    if len(last_n) < MIN_MATCHES_FOR_FORM:
        return _empty_metrics(
            team=team_key,
            matches_found=len(last_n),
            before_date=cutoff,
            window=window,
        )

    scored = sum(1 for m in last_n if m.goals_for >= 1)
    failed = sum(1 for m in last_n if m.goals_for == 0)
    goals_for_avg = sum(m.goals_for for m in last_n) / len(last_n)
    goals_against_avg = sum(m.goals_against for m in last_n) / len(last_n)
    scored_rate = scored / len(last_n)
    failed_rate = failed / len(last_n)

    source_breakdown: dict[str, int] = {}
    for m in last_n:
        source_breakdown[m.source] = source_breakdown.get(m.source, 0) + 1

    vs_strong_rate: float | None = None
    strong_match_count = 0
    opponent_proxy_used = False
    opponent_proxy_unavailable = False

    if favorite_power is not None and favorite_power > 0:
        threshold = favorite_power - 50.0
        strong_scored = 0
        for m in last_n:
            if m.opponent_power_proxy is None:
                opponent_proxy_unavailable = True
                continue
            opponent_proxy_used = True
            if m.opponent_power_proxy >= threshold:
                strong_match_count += 1
                if m.goals_for >= 1:
                    strong_scored += 1
        if strong_match_count > 0:
            vs_strong_rate = strong_scored / strong_match_count
        elif last_n:
            opponent_proxy_unavailable = True
    else:
        opponent_proxy_unavailable = True

    confidence = _classify_confidence(last_n)
    reason_codes = _build_reason_codes(
        confidence,
        last_n,
        opponent_proxy_used=opponent_proxy_used,
        opponent_proxy_unavailable=opponent_proxy_unavailable,
    )

    return RecentScoringFormMetrics(
        recent_form_available=True,
        recent_form_confidence=confidence,
        last_10_scored_rate=round(scored_rate, 3),
        last_10_goals_for_avg=round(goals_for_avg, 3),
        last_10_failed_to_score_rate=round(failed_rate, 3),
        scored_vs_similar_or_stronger_opponents=(
            round(vs_strong_rate, 3) if vs_strong_rate is not None else None
        ),
        matches_used=len(last_n),
        team=team_key,
        matches_found=len(last_n),
        requested_match_count=window,
        before_date=cutoff,
        scored_matches=scored,
        failed_to_score_matches=failed,
        last_10_goals_against_avg=round(goals_against_avg, 3),
        scored_vs_similar_or_stronger_opponents_rate=(
            round(vs_strong_rate, 3) if vs_strong_rate is not None else None
        ),
        scored_vs_strong_opponents_matches=strong_match_count,
        recent_form_source=_primary_source_label(source_breakdown),
        source_breakdown=source_breakdown,
        reason_codes=reason_codes,
    )


def build_normalized_history_for_tests() -> list[NormalizedRecentMatch]:
    """Test helper — offline normalized history."""
    return build_normalized_recent_match_history(include_optional_caches=False)
