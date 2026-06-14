"""World Cup 2022 — pre-tournament FIFA points + all 64 match results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.database import compute_derived_metrics

# FIFA ranking points — October 2022 (pre-tournament, fifa.com)
WC2022_FIFA_ELO: dict[str, int] = {
    "Brazil": 1841,
    "Belgium": 1816,
    "Argentina": 1774,
    "France": 1765,
    "England": 1728,
    "Spain": 1715,
    "Portugal": 1695,
    "Netherlands": 1678,
    "Denmark": 1667,
    "Germany": 1650,
    "Croatia": 1642,
    "Mexico": 1642,
    "Uruguay": 1640,
    "Switzerland": 1637,
    "USA": 1637,
    "Senegal": 1585,
    "Iran": 1580,
    "Morocco": 1562,
    "Japan": 1560,
    "Serbia": 1550,
    "South Korea": 1530,
    "Poland": 1529,
    "Tunisia": 1528,
    "Costa Rica": 1501,
    "Australia": 1489,
    "Wales": 1487,
    "Saudi Arabia": 1440,
    "Ecuador": 1438,
    "Canada": 1416,
    "Cameroon": 1412,
    "Ghana": 1395,
    "Qatar": 1394,
}


@dataclass(frozen=True)
class Wc2022Match:
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True
    stage: str = "group"


# Regulation-time scores (penalty shootouts keep draw score).
WC2022_MATCHES: tuple[Wc2022Match, ...] = (
    # Group A
    Wc2022Match("Qatar", "Ecuador", 0, 2, neutral=False),
    Wc2022Match("Senegal", "Netherlands", 0, 2),
    Wc2022Match("Qatar", "Senegal", 1, 3, neutral=False),
    Wc2022Match("Netherlands", "Ecuador", 1, 1),
    Wc2022Match("Ecuador", "Senegal", 1, 2),
    Wc2022Match("Netherlands", "Qatar", 2, 0, neutral=False),
    # Group B
    Wc2022Match("England", "Iran", 6, 2),
    Wc2022Match("USA", "Wales", 1, 1),
    Wc2022Match("Wales", "Iran", 0, 2),
    Wc2022Match("England", "USA", 0, 0),
    Wc2022Match("Wales", "England", 0, 3),
    Wc2022Match("Iran", "USA", 0, 1),
    # Group C
    Wc2022Match("Argentina", "Saudi Arabia", 1, 2),
    Wc2022Match("Mexico", "Poland", 0, 0),
    Wc2022Match("Poland", "Saudi Arabia", 2, 0),
    Wc2022Match("Argentina", "Mexico", 2, 0),
    Wc2022Match("Saudi Arabia", "Mexico", 1, 2),
    Wc2022Match("Poland", "Argentina", 0, 2),
    # Group D
    Wc2022Match("Denmark", "Tunisia", 0, 0),
    Wc2022Match("France", "Australia", 4, 1),
    Wc2022Match("Tunisia", "Australia", 0, 1),
    Wc2022Match("France", "Denmark", 2, 1),
    Wc2022Match("Australia", "Denmark", 1, 0),
    Wc2022Match("Tunisia", "France", 1, 0),
    # Group E
    Wc2022Match("Germany", "Japan", 1, 2),
    Wc2022Match("Spain", "Costa Rica", 7, 0),
    Wc2022Match("Japan", "Costa Rica", 0, 1),
    Wc2022Match("Spain", "Germany", 1, 1),
    Wc2022Match("Japan", "Spain", 2, 1),
    Wc2022Match("Costa Rica", "Germany", 2, 4),
    # Group F
    Wc2022Match("Morocco", "Croatia", 0, 0),
    Wc2022Match("Belgium", "Canada", 1, 0),
    Wc2022Match("Belgium", "Morocco", 0, 2),
    Wc2022Match("Croatia", "Canada", 4, 1),
    Wc2022Match("Croatia", "Belgium", 0, 0),
    Wc2022Match("Canada", "Morocco", 1, 2),
    # Group G
    Wc2022Match("Switzerland", "Cameroon", 1, 0),
    Wc2022Match("Brazil", "Serbia", 2, 0),
    Wc2022Match("Cameroon", "Serbia", 3, 3),
    Wc2022Match("Brazil", "Switzerland", 1, 0),
    Wc2022Match("Cameroon", "Brazil", 1, 0),
    Wc2022Match("Serbia", "Switzerland", 2, 3),
    # Group H
    Wc2022Match("Uruguay", "South Korea", 0, 0),
    Wc2022Match("Portugal", "Ghana", 3, 2),
    Wc2022Match("South Korea", "Ghana", 2, 3),
    Wc2022Match("Portugal", "Uruguay", 2, 0),
    Wc2022Match("Ghana", "Uruguay", 0, 2),
    Wc2022Match("South Korea", "Portugal", 2, 1),
    # Round of 16
    Wc2022Match("Netherlands", "USA", 3, 1, stage="r16"),
    Wc2022Match("Argentina", "Australia", 2, 1, stage="r16"),
    Wc2022Match("France", "Poland", 3, 1, stage="r16"),
    Wc2022Match("England", "Senegal", 3, 0, stage="r16"),
    Wc2022Match("Japan", "Croatia", 1, 1, stage="r16"),
    Wc2022Match("Brazil", "South Korea", 4, 1, stage="r16"),
    Wc2022Match("Morocco", "Spain", 0, 0, stage="r16"),
    Wc2022Match("Portugal", "Switzerland", 6, 1, stage="r16"),
    # Quarter-finals
    Wc2022Match("Croatia", "Brazil", 1, 1, stage="qf"),
    Wc2022Match("Netherlands", "Argentina", 2, 2, stage="qf"),
    Wc2022Match("Morocco", "Portugal", 1, 0, stage="qf"),
    Wc2022Match("England", "France", 1, 2, stage="qf"),
    # Semi-finals
    Wc2022Match("Argentina", "Croatia", 3, 0, stage="sf"),
    Wc2022Match("France", "Morocco", 2, 0, stage="sf"),
    # Third place + Final
    Wc2022Match("Croatia", "Morocco", 2, 1, stage="3rd"),
    Wc2022Match("Argentina", "France", 3, 3, stage="final"),
)


class Wc2022DataManager:
    """Minimal team registry for historical backtesting."""

    def __init__(self) -> None:
        self.team_database: dict[str, dict[str, float]] = {
            name: compute_derived_metrics(elo)
            for name, elo in WC2022_FIFA_ELO.items()
        }

    def get_team_data(self, team_name: str, *, use_live: bool = False) -> dict[str, Any]:
        if team_name not in self.team_database:
            raise KeyError(f"Unknown WC 2022 team: {team_name}")
        return self.team_database[team_name]

    def list_teams(self) -> list[str]:
        return list(self.team_database.keys())
