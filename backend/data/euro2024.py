"""UEFA Euro 2024 — regulation-time results (51 matches)."""

from __future__ import annotations

from dataclasses import dataclass

EURO2024_FIFA_ELO: dict[str, int] = {
    "France": 1850,
    "England": 1790,
    "Spain": 1760,
    "Portugal": 1740,
    "Netherlands": 1700,
    "Belgium": 1690,
    "Germany": 1680,
    "Switzerland": 1650,
    "Italy": 1640,
    "Croatia": 1620,
    "Austria": 1600,
    "Turkey": 1580,
    "Denmark": 1570,
    "Serbia": 1550,
    "Ukraine": 1540,
    "Romania": 1520,
    "Czechia": 1510,
    "Scotland": 1500,
    "Hungary": 1490,
    "Slovakia": 1470,
    "Slovenia": 1460,
    "Albania": 1440,
    "Georgia": 1420,
}


@dataclass(frozen=True)
class Euro2024Match:
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True
    stage: str = "group"


EURO2024_MATCHES: tuple[Euro2024Match, ...] = (
    # Group A
    Euro2024Match("Germany", "Scotland", 5, 1),
    Euro2024Match("Hungary", "Switzerland", 1, 3),
    Euro2024Match("Scotland", "Switzerland", 1, 1),
    Euro2024Match("Germany", "Hungary", 2, 0),
    Euro2024Match("Scotland", "Hungary", 1, 0),
    Euro2024Match("Switzerland", "Germany", 1, 1),
    # Group B
    Euro2024Match("Spain", "Croatia", 3, 0),
    Euro2024Match("Italy", "Albania", 2, 1),
    Euro2024Match("Spain", "Italy", 1, 0),
    Euro2024Match("Croatia", "Albania", 2, 2),
    Euro2024Match("Croatia", "Italy", 1, 1),
    Euro2024Match("Albania", "Spain", 0, 1),
    # Group C
    Euro2024Match("Slovenia", "Denmark", 1, 1),
    Euro2024Match("Serbia", "England", 0, 1),
    Euro2024Match("Slovenia", "Serbia", 1, 1),
    Euro2024Match("Denmark", "England", 1, 1),
    Euro2024Match("Denmark", "Serbia", 0, 0),
    Euro2024Match("England", "Slovenia", 0, 0),
    # Group D
    Euro2024Match("Poland", "Netherlands", 1, 2),
    Euro2024Match("Austria", "France", 0, 1),
    Euro2024Match("Poland", "Austria", 1, 3),
    Euro2024Match("Netherlands", "France", 0, 0),
    Euro2024Match("Netherlands", "Austria", 2, 3),
    Euro2024Match("France", "Poland", 1, 1),
    # Group E
    Euro2024Match("Romania", "Ukraine", 3, 0),
    Euro2024Match("Belgium", "Slovakia", 0, 1),
    Euro2024Match("Belgium", "Romania", 2, 0),
    Euro2024Match("Slovakia", "Ukraine", 1, 1),
    Euro2024Match("Ukraine", "Slovakia", 2, 1),
    Euro2024Match("Belgium", "Ukraine", 0, 0),
    # Group F
    Euro2024Match("Turkey", "Georgia", 3, 1),
    Euro2024Match("Portugal", "Czechia", 2, 1),
    Euro2024Match("Georgia", "Czechia", 1, 1),
    Euro2024Match("Turkey", "Portugal", 0, 3),
    Euro2024Match("Czechia", "Turkey", 1, 2),
    Euro2024Match("Georgia", "Portugal", 2, 0),
    # Round of 16
    Euro2024Match("Spain", "Georgia", 4, 1, stage="r16"),
    Euro2024Match("Germany", "Denmark", 2, 0, stage="r16"),
    Euro2024Match("Portugal", "Slovenia", 0, 0, stage="r16"),
    Euro2024Match("France", "Belgium", 1, 0, stage="r16"),
    Euro2024Match("Switzerland", "Italy", 2, 0, stage="r16"),
    Euro2024Match("England", "Slovakia", 2, 1, stage="r16"),
    Euro2024Match("Netherlands", "Romania", 3, 0, stage="r16"),
    Euro2024Match("Austria", "Turkey", 2, 1, stage="r16"),
    # Quarter-finals
    Euro2024Match("Spain", "Germany", 2, 1, stage="qf"),
    Euro2024Match("Portugal", "France", 0, 0, stage="qf"),
    Euro2024Match("England", "Switzerland", 1, 1, stage="qf"),
    Euro2024Match("Netherlands", "Turkey", 2, 1, stage="qf"),
    # Semi-finals
    Euro2024Match("Spain", "France", 2, 1, stage="sf"),
    Euro2024Match("Netherlands", "England", 1, 2, stage="sf"),
    # Final
    Euro2024Match("Spain", "England", 2, 1, stage="final"),
)
