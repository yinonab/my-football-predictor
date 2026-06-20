"""Offline recent national-team scoring form (Phase 4Q.1 extension point)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026
from data.nt_match import NationalTeamMatch, registry_key_for_nt

RecentFormConfidence = Literal["high", "medium", "low", "unavailable"]

MIN_MATCHES_FOR_FORM = 3
FORM_WINDOW = 10


@dataclass(frozen=True)
class RecentScoringFormMetrics:
    recent_form_available: bool
    recent_form_confidence: RecentFormConfidence
    last_10_scored_rate: float | None
    last_10_goals_for_avg: float | None
    last_10_failed_to_score_rate: float | None
    scored_vs_similar_or_stronger_opponents: float | None
    matches_used: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _team_goals_in_match(match: NationalTeamMatch, team_key: str) -> int | None:
    registry = set(FIFA_ELO_2026.keys())
    home_key = registry_key_for_nt(match.home, registry)
    away_key = registry_key_for_nt(match.away, registry)
    if team_key == home_key:
        return match.home_goals
    if team_key == away_key:
        return match.away_goals
    return None


def _opponent_key_in_match(match: NationalTeamMatch, team_key: str) -> str | None:
    registry = set(FIFA_ELO_2026.keys())
    home_key = registry_key_for_nt(match.home, registry)
    away_key = registry_key_for_nt(match.away, registry)
    if team_key == home_key:
        return away_key
    if team_key == away_key:
        return home_key
    return None


def get_recent_scoring_form(
    team_key: str,
    *,
    favorite_power: float | None = None,
    matches: list[NationalTeamMatch] | None = None,
    window: int = FORM_WINDOW,
) -> RecentScoringFormMetrics:
    """
    Last-N scoring form from offline bundled + cache match history.

    Not a live API dependency. Confidence reflects data depth, not recency precision
    (tournament bundles mix dated qualifiers with synthetic tournament sequencing).
    """
    if not team_key or team_key not in FIFA_ELO_2026:
        return RecentScoringFormMetrics(
            recent_form_available=False,
            recent_form_confidence="unavailable",
            last_10_scored_rate=None,
            last_10_goals_for_avg=None,
            last_10_failed_to_score_rate=None,
            scored_vs_similar_or_stronger_opponents=None,
            matches_used=0,
        )

    all_matches = matches if matches is not None else build_all_matches()
    team_rows: list[tuple[str, int, str | None]] = []
    for match in all_matches:
        goals = _team_goals_in_match(match, team_key)
        if goals is None:
            continue
        opponent = _opponent_key_in_match(match, team_key)
        team_rows.append((match.date, goals, opponent))

    team_rows.sort(key=lambda row: row[0], reverse=True)
    last_n = team_rows[:window]
    if len(last_n) < MIN_MATCHES_FOR_FORM:
        return RecentScoringFormMetrics(
            recent_form_available=False,
            recent_form_confidence="unavailable",
            last_10_scored_rate=None,
            last_10_goals_for_avg=None,
            last_10_failed_to_score_rate=None,
            scored_vs_similar_or_stronger_opponents=None,
            matches_used=len(last_n),
        )

    scored = sum(1 for _, goals, _ in last_n if goals >= 1)
    failed = sum(1 for _, goals, _ in last_n if goals == 0)
    goals_avg = sum(goals for _, goals, _ in last_n) / len(last_n)
    scored_rate = scored / len(last_n)
    failed_rate = failed / len(last_n)

    vs_strong: float | None = None
    if favorite_power is not None and favorite_power > 0:
        # Proxy: compare opponent Elo to a threshold derived from favorite power.
        strong_elo_threshold = 1200 + (favorite_power - 700) * 0.85
        strong_matches = []
        for _, goals, opp in last_n:
            if not opp:
                continue
            opp_elo = FIFA_ELO_2026.get(opp)
            if opp_elo is not None and opp_elo >= strong_elo_threshold:
                strong_matches.append(goals)
        if strong_matches:
            vs_strong = sum(1 for goals in strong_matches if goals >= 1) / len(
                strong_matches
            )

    if len(last_n) >= 8:
        confidence: RecentFormConfidence = "high"
    elif len(last_n) >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    return RecentScoringFormMetrics(
        recent_form_available=True,
        recent_form_confidence=confidence,
        last_10_scored_rate=round(scored_rate, 3),
        last_10_goals_for_avg=round(goals_avg, 3),
        last_10_failed_to_score_rate=round(failed_rate, 3),
        scored_vs_similar_or_stronger_opponents=(
            round(vs_strong, 3) if vs_strong is not None else None
        ),
        matches_used=len(last_n),
    )
