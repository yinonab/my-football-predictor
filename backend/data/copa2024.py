"""Copa America 2024 — regulation-time results (32 matches, no R16)."""

from __future__ import annotations

from dataclasses import dataclass

COPA2024_FIFA_ELO: dict[str, int] = {
    "Argentina": 1880,
    "Brazil": 1820,
    "Colombia": 1700,
    "Uruguay": 1680,
    "USA": 1650,
    "Ecuador": 1620,
    "Mexico": 1600,
    "Paraguay": 1550,
    "Panama": 1520,
    "Venezuela": 1500,
    "Canada": 1480,
    "Chile": 1470,
    "Peru": 1460,
    "Costa Rica": 1440,
    "Bolivia": 1400,
    "Jamaica": 1380,
}


@dataclass(frozen=True)
class Copa2024Match:
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True
    stage: str = "group"


COPA2024_MATCHES: tuple[Copa2024Match, ...] = (
    # Group A
    Copa2024Match("Argentina", "Canada", 2, 0),
    Copa2024Match("Peru", "Chile", 0, 0),
    Copa2024Match("Canada", "Chile", 1, 0),
    Copa2024Match("Argentina", "Chile", 1, 0),
    Copa2024Match("Argentina", "Peru", 2, 0),
    Copa2024Match("Canada", "Peru", 1, 0),
    # Group B
    Copa2024Match("Ecuador", "Venezuela", 2, 1),
    Copa2024Match("Mexico", "Jamaica", 1, 0),
    Copa2024Match("Mexico", "Venezuela", 0, 0),
    Copa2024Match("Ecuador", "Jamaica", 3, 1),
    Copa2024Match("Mexico", "Ecuador", 0, 0),
    Copa2024Match("Jamaica", "Venezuela", 0, 3),
    # Group C
    Copa2024Match("Uruguay", "Panama", 3, 1),
    Copa2024Match("USA", "Bolivia", 2, 0),
    Copa2024Match("USA", "Panama", 1, 1),
    Copa2024Match("Uruguay", "Bolivia", 1, 0),
    Copa2024Match("USA", "Uruguay", 1, 0),
    Copa2024Match("Bolivia", "Panama", 1, 3),
    # Group D
    Copa2024Match("Colombia", "Paraguay", 2, 1),
    Copa2024Match("Brazil", "Costa Rica", 0, 0),
    Copa2024Match("Brazil", "Paraguay", 4, 1),
    Copa2024Match("Colombia", "Costa Rica", 2, 1),
    Copa2024Match("Brazil", "Colombia", 1, 1),
    Copa2024Match("Costa Rica", "Paraguay", 2, 4),
    # Quarter-finals (top-2 per group)
    Copa2024Match("Argentina", "Ecuador", 1, 1, stage="qf"),
    Copa2024Match("Canada", "Venezuela", 1, 1, stage="qf"),
    Copa2024Match("Uruguay", "Brazil", 0, 0, stage="qf"),
    Copa2024Match("Colombia", "Panama", 1, 1, stage="qf"),
    # Semi-finals
    Copa2024Match("Argentina", "Canada", 2, 0, stage="sf"),
    Copa2024Match("Colombia", "Uruguay", 1, 0, stage="sf"),
    # Third place + Final
    Copa2024Match("Canada", "Uruguay", 2, 2, stage="3rd"),
    Copa2024Match("Argentina", "Colombia", 1, 0, stage="final"),
)
