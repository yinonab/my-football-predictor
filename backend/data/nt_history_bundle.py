"""Bundled national-team history from major tournaments (offline baseline)."""

from __future__ import annotations

from datetime import date, timedelta

from data.copa2024 import COPA2024_MATCHES
from data.euro2024 import EURO2024_MATCHES
from data.nt_match import NationalTeamMatch
from data.wc2018 import WC2018_MATCHES
from data.wc2022 import WC2022_MATCHES
from data.wc2026_qualifiers import WC2026_QUALIFIER_MATCHES


def _tournament_to_nt_matches(
    matches: tuple,
    *,
    competition: str,
    weight: float,
    start: date,
) -> list[NationalTeamMatch]:
    out: list[NationalTeamMatch] = []
    for index, match in enumerate(matches):
        match_date = (start + timedelta(days=index)).isoformat()
        out.append(
            NationalTeamMatch(
                date=match_date,
                home=match.home,
                away=match.away,
                home_goals=match.home_goals,
                away_goals=match.away_goals,
                neutral=match.neutral,
                competition=competition,
                weight=weight,
            )
        )
    return out


def bundled_tournament_matches() -> list[NationalTeamMatch]:
    """WC 2018 + WC 2022 + Euro 2024 + Copa 2024."""
    wc18 = _tournament_to_nt_matches(
        WC2018_MATCHES,
        competition="FIFA World Cup",
        weight=1.0,
        start=date(2018, 6, 14),
    )
    wc22 = _tournament_to_nt_matches(
        WC2022_MATCHES,
        competition="FIFA World Cup",
        weight=1.0,
        start=date(2022, 11, 20),
    )
    euro = _tournament_to_nt_matches(
        EURO2024_MATCHES,
        competition="UEFA European Championship",
        weight=0.95,
        start=date(2024, 6, 14),
    )
    copa = _tournament_to_nt_matches(
        COPA2024_MATCHES,
        competition="Copa America",
        weight=0.95,
        start=date(2024, 6, 20),
    )
    qual = [
        NationalTeamMatch(
            date=q.date,
            home=q.home,
            away=q.away,
            home_goals=q.home_goals,
            away_goals=q.away_goals,
            neutral=True,
            competition=q.competition,
            weight=0.75,
        )
        for q in WC2026_QUALIFIER_MATCHES
    ]
    return wc18 + wc22 + euro + copa + qual


BUNDLED_NT_MATCHES: tuple[NationalTeamMatch, ...] = tuple(bundled_tournament_matches())
