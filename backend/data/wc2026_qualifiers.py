"""WC 2026 qualification — key matches involving qualified teams (offline)."""

from __future__ import annotations

from dataclasses import dataclass

# Regulation-time scores. Includes CONMEBOL round-robin highlights,
# UEFA playoff finals (March 2026), intercontinental playoffs, and AFC 4th round.


@dataclass(frozen=True)
class QualifierMatch:
    home: str
    away: str
    home_goals: int
    away_goals: int
    date: str = "2025-01-01"
    competition: str = "World Cup Qualification"


def _m(h: str, a: str, hg: int, ag: int, d: str = "2025-06-01") -> QualifierMatch:
    return QualifierMatch(h, a, hg, ag, date=d)


# CONMEBOL 2026 cycle — matches among qualified teams (Argentina, Brazil, Colombia,
# Ecuador, Paraguay, Uruguay) + decisive games vs non-qualifiers.
CONMEBOL_QUAL: tuple[QualifierMatch, ...] = (
    _m("Argentina", "Ecuador", 1, 0, "2023-09-07"),
    _m("Colombia", "Venezuela", 3, 0, "2023-09-07"),
    _m("Brazil", "Bolivia", 5, 1, "2023-09-08"),
    _m("Uruguay", "Chile", 3, 1, "2023-09-08"),
    _m("Paraguay", "Peru", 0, 0, "2023-09-08"),
    _m("Ecuador", "Uruguay", 2, 1, "2023-09-12"),
    _m("Venezuela", "Paraguay", 1, 0, "2023-09-12"),
    _m("Chile", "Colombia", 0, 0, "2023-09-12"),
    _m("Peru", "Brazil", 0, 1, "2023-09-12"),
    _m("Bolivia", "Argentina", 0, 3, "2023-09-12"),
    _m("Brazil", "Venezuela", 1, 1, "2023-10-12"),
    _m("Argentina", "Paraguay", 1, 0, "2023-10-12"),
    _m("Colombia", "Uruguay", 2, 2, "2023-10-12"),
    _m("Chile", "Ecuador", 1, 0, "2023-10-12"),
    _m("Peru", "Bolivia", 2, 0, "2023-10-12"),
    _m("Paraguay", "Chile", 0, 0, "2023-10-17"),
    _m("Uruguay", "Brazil", 2, 0, "2023-10-17"),
    _m("Ecuador", "Colombia", 0, 2, "2023-10-17"),
    _m("Venezuela", "Peru", 1, 0, "2023-10-17"),
    _m("Bolivia", "Argentina", 1, 2, "2023-10-17"),
    _m("Argentina", "Brazil", 1, 0, "2024-11-21"),
    _m("Colombia", "Ecuador", 0, 1, "2024-11-21"),
    _m("Uruguay", "Paraguay", 1, 0, "2024-11-21"),
    _m("Peru", "Chile", 0, 0, "2024-11-21"),
    _m("Venezuela", "Bolivia", 4, 0, "2024-11-21"),
    _m("Brazil", "Argentina", 1, 1, "2025-03-25"),
    _m("Ecuador", "Paraguay", 1, 0, "2025-03-25"),
    _m("Colombia", "Brazil", 2, 1, "2025-03-25"),
    _m("Uruguay", "Argentina", 0, 1, "2025-03-25"),
    _m("Chile", "Ecuador", 0, 0, "2025-03-25"),
    _m("Bolivia", "Uruguay", 0, 0, "2025-06-05"),
    _m("Paraguay", "Uruguay", 1, 1, "2025-06-05"),
    _m("Ecuador", "Brazil", 0, 0, "2025-06-05"),
    _m("Argentina", "Colombia", 1, 1, "2025-06-05"),
    _m("Peru", "Ecuador", 0, 1, "2025-06-10"),
    _m("Uruguay", "Venezuela", 2, 0, "2025-06-10"),
    _m("Brazil", "Paraguay", 1, 0, "2025-06-10"),
    _m("Colombia", "Peru", 0, 0, "2025-06-10"),
    _m("Argentina", "Chile", 3, 0, "2025-09-04"),
    _m("Ecuador", "Argentina", 1, 1, "2025-09-09"),
    _m("Brazil", "Chile", 2, 1, "2025-09-09"),
    _m("Paraguay", "Colombia", 1, 2, "2025-09-09"),
    _m("Uruguay", "Ecuador", 0, 0, "2025-09-09"),
)

# UEFA playoff finals + key qual (teams in WC 2026 roster)
UEFA_QUAL: tuple[QualifierMatch, ...] = (
    _m("Bosnia and Herzegovina", "Italy", 1, 1, "2026-03-24"),
    _m("Wales", "North Macedonia", 2, 1, "2026-03-24"),
    _m("Poland", "Albania", 2, 0, "2026-03-24"),
    _m("Czechia", "Ireland", 2, 1, "2026-03-24"),
    _m("Turkey", "Romania", 3, 2, "2026-03-24"),
    _m("Slovakia", "Kosovo", 1, 0, "2026-03-24"),
    _m("Denmark", "North Macedonia", 3, 1, "2026-03-27"),
    _m("Wales", "Bosnia and Herzegovina", 0, 0, "2026-03-27"),
    _m("Poland", "Czechia", 1, 1, "2026-03-27"),
    _m("Turkey", "Slovakia", 2, 0, "2026-03-27"),
    _m("England", "Serbia", 2, 0, "2025-03-21"),
    _m("France", "Croatia", 2, 0, "2025-03-21"),
    _m("Germany", "Netherlands", 2, 2, "2025-03-21"),
    _m("Spain", "Portugal", 1, 0, "2025-03-21"),
    _m("Norway", "Sweden", 3, 1, "2025-03-21"),
    _m("Scotland", "Austria", 0, 0, "2025-03-21"),
    _m("Belgium", "Switzerland", 1, 1, "2025-03-21"),
)

# AFC 3rd/4th round — qualified teams
AFC_QUAL: tuple[QualifierMatch, ...] = (
    _m("Japan", "Australia", 2, 1, "2025-03-20"),
    _m("South Korea", "Iran", 1, 1, "2025-03-20"),
    _m("Jordan", "Iraq", 0, 0, "2025-03-20"),
    _m("Qatar", "Saudi Arabia", 2, 2, "2025-03-20"),
    _m("Uzbekistan", "United Arab Emirates", 1, 0, "2025-03-20"),
    _m("Australia", "Saudi Arabia", 2, 1, "2025-06-05"),
    _m("Japan", "Indonesia", 6, 0, "2025-06-05"),
    _m("Iran", "Uzbekistan", 2, 0, "2025-06-05"),
    _m("South Korea", "Kuwait", 4, 0, "2025-06-05"),
    _m("Iraq", "Oman", 1, 0, "2025-06-05"),
    _m("Jordan", "Palestine", 3, 0, "2025-06-05"),
    _m("Qatar", "United Arab Emirates", 2, 1, "2025-10-08"),
    _m("Saudi Arabia", "Iraq", 0, 0, "2025-10-11"),
    _m("United Arab Emirates", "Oman", 2, 1, "2025-11-13"),
    _m("Iraq", "United Arab Emirates", 2, 1, "2025-11-18"),
)

# CAF — qualified teams highlights
CAF_QUAL: tuple[QualifierMatch, ...] = (
    _m("Morocco", "Tunisia", 2, 1, "2025-03-21"),
    _m("Senegal", "Egypt", 1, 0, "2025-03-21"),
    _m("Algeria", "Ghana", 2, 0, "2025-03-21"),
    _m("Ivory Coast", "DR Congo", 1, 1, "2025-03-21"),
    _m("South Africa", "Cape Verde", 2, 0, "2025-03-21"),
    _m("Morocco", "Egypt", 1, 0, "2025-06-05"),
    _m("Senegal", "Algeria", 0, 0, "2025-06-05"),
    _m("Ghana", "Tunisia", 1, 2, "2025-06-05"),
    _m("DR Congo", "South Africa", 2, 1, "2025-11-14"),
)

# CONCACAF + intercontinental playoffs
CONCACAF_QUAL: tuple[QualifierMatch, ...] = (
    _m("Panama", "Jamaica", 1, 0, "2025-11-14"),
    _m("Haiti", "Trinidad and Tobago", 2, 1, "2025-11-14"),
    _m("Curacao", "Jamaica", 1, 0, "2025-11-18"),
    _m("DR Congo", "Jamaica", 2, 1, "2026-03-26"),
    _m("Iraq", "Bolivia", 1, 0, "2026-03-26"),
    _m("Bolivia", "Iraq", 0, 2, "2026-03-31"),
    _m("Jamaica", "DR Congo", 0, 0, "2026-03-31"),
)

WC2026_QUALIFIER_MATCHES: tuple[QualifierMatch, ...] = (
    CONMEBOL_QUAL + UEFA_QUAL + AFC_QUAL + CAF_QUAL + CONCACAF_QUAL
)
