"""World Cup 2018 — all 64 regulation-time results."""

from __future__ import annotations

from dataclasses import dataclass

WC2018_FIFA_ELO: dict[str, int] = {
    "Germany": 1555,
    "Brazil": 1742,
    "Belgium": 1730,
    "Portugal": 1671,
    "Argentina": 1678,
    "Switzerland": 1660,
    "France": 1755,
    "Spain": 1680,
    "Chile": 1635,
    "Poland": 1635,
    "Peru": 1625,
    "England": 1720,
    "Colombia": 1615,
    "Mexico": 1610,
    "Uruguay": 1600,
    "Croatia": 1595,
    "Denmark": 1585,
    "Sweden": 1580,
    "Iceland": 1570,
    "Costa Rica": 1560,
    "Tunisia": 1550,
    "Egypt": 1540,
    "Senegal": 1530,
    "Iran": 1520,
    "Serbia": 1510,
    "Nigeria": 1500,
    "Australia": 1490,
    "Japan": 1480,
    "Morocco": 1470,
    "South Korea": 1460,
    "Saudi Arabia": 1450,
    "Panama": 1440,
    "Russia": 1430,
}


@dataclass(frozen=True)
class Wc2018Match:
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True
    stage: str = "group"


WC2018_MATCHES: tuple[Wc2018Match, ...] = (
    # Group A
    Wc2018Match("Russia", "Saudi Arabia", 5, 0, neutral=False),
    Wc2018Match("Egypt", "Uruguay", 0, 1),
    Wc2018Match("Russia", "Egypt", 3, 1, neutral=False),
    Wc2018Match("Saudi Arabia", "Uruguay", 0, 1),
    Wc2018Match("Saudi Arabia", "Egypt", 2, 1),
    Wc2018Match("Russia", "Uruguay", 0, 3, neutral=False),
    # Group B
    Wc2018Match("Morocco", "Iran", 0, 1),
    Wc2018Match("Portugal", "Spain", 3, 3),
    Wc2018Match("Portugal", "Morocco", 1, 0),
    Wc2018Match("Iran", "Spain", 0, 1),
    Wc2018Match("Iran", "Portugal", 1, 1),
    Wc2018Match("Spain", "Morocco", 2, 2),
    # Group C
    Wc2018Match("France", "Australia", 2, 1),
    Wc2018Match("Peru", "Denmark", 0, 1),
    Wc2018Match("France", "Peru", 1, 0),
    Wc2018Match("Denmark", "Australia", 1, 1),
    Wc2018Match("Denmark", "France", 0, 0),
    Wc2018Match("Australia", "Peru", 0, 2),
    # Group D
    Wc2018Match("Argentina", "Iceland", 1, 1),
    Wc2018Match("Croatia", "Nigeria", 2, 0),
    Wc2018Match("Argentina", "Croatia", 0, 3),
    Wc2018Match("Nigeria", "Iceland", 2, 0),
    Wc2018Match("Nigeria", "Argentina", 1, 2),
    Wc2018Match("Iceland", "Croatia", 1, 2),
    # Group E
    Wc2018Match("Costa Rica", "Serbia", 0, 1),
    Wc2018Match("Brazil", "Switzerland", 1, 1),
    Wc2018Match("Brazil", "Costa Rica", 2, 0),
    Wc2018Match("Serbia", "Switzerland", 1, 2),
    Wc2018Match("Serbia", "Brazil", 0, 2),
    Wc2018Match("Switzerland", "Costa Rica", 2, 1),
    # Group F
    Wc2018Match("Germany", "Mexico", 0, 1),
    Wc2018Match("Sweden", "South Korea", 1, 0),
    Wc2018Match("South Korea", "Mexico", 1, 2),
    Wc2018Match("Germany", "Sweden", 2, 1),
    Wc2018Match("South Korea", "Germany", 2, 0),
    Wc2018Match("Mexico", "Sweden", 0, 3),
    # Group G
    Wc2018Match("Belgium", "Panama", 3, 0),
    Wc2018Match("England", "Tunisia", 2, 1),
    Wc2018Match("Belgium", "Tunisia", 5, 2),
    Wc2018Match("England", "Panama", 6, 1),
    Wc2018Match("England", "Belgium", 0, 1),
    Wc2018Match("Panama", "Tunisia", 1, 2),
    # Group H
    Wc2018Match("Colombia", "Japan", 1, 2),
    Wc2018Match("Poland", "Senegal", 1, 2),
    Wc2018Match("Japan", "Senegal", 2, 2),
    Wc2018Match("Colombia", "Poland", 3, 0),
    Wc2018Match("Japan", "Poland", 0, 1),
    Wc2018Match("Senegal", "Colombia", 0, 1),
    # Round of 16
    Wc2018Match("France", "Argentina", 4, 3, stage="r16"),
    Wc2018Match("Uruguay", "Portugal", 2, 1, stage="r16"),
    Wc2018Match("Spain", "Russia", 1, 1, stage="r16"),
    Wc2018Match("Croatia", "Denmark", 1, 1, stage="r16"),
    Wc2018Match("Brazil", "Mexico", 2, 0, stage="r16"),
    Wc2018Match("Belgium", "Japan", 3, 2, stage="r16"),
    Wc2018Match("Sweden", "Switzerland", 1, 0, stage="r16"),
    Wc2018Match("England", "Colombia", 1, 1, stage="r16"),
    # Quarter-finals
    Wc2018Match("Uruguay", "France", 0, 2, stage="qf"),
    Wc2018Match("Brazil", "Belgium", 1, 2, stage="qf"),
    Wc2018Match("Russia", "Croatia", 2, 2, stage="qf"),
    Wc2018Match("England", "Sweden", 2, 0, stage="qf"),
    # Semi-finals
    Wc2018Match("France", "Belgium", 1, 0, stage="sf"),
    Wc2018Match("Croatia", "England", 2, 1, stage="sf"),
    # Third place + Final
    Wc2018Match("Belgium", "England", 2, 0, stage="3rd"),
    Wc2018Match("France", "Croatia", 4, 2, stage="final"),
)
