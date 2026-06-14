"""Monte Carlo tournament simulation for World Cup 2026 format."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import config
from core.math_engine import AdvancedDixonColesEngine
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager, _build_groups


@dataclass
class GroupStandingEstimate:
    group: str
    team: str
    avg_points: float
    top2_probability: float
    win_group_probability: float


@dataclass
class ChampionEstimate:
    team: str
    probability: float


class TournamentSimulator:
    """Simulate group stage and simplified knockout bracket."""

    def __init__(
        self,
        data_manager: LiveDataManager | None = None,
        engine: AdvancedDixonColesEngine | None = None,
        seed: int | None = None,
    ) -> None:
        self._dm = data_manager or LiveDataManager()
        self._evaluator = TeamPowerEvaluator(self._dm)
        self._engine = engine or AdvancedDixonColesEngine()
        self._rng = random.Random(seed)
        self._groups = _build_groups()

    def _powers(self, team: str) -> float:
        return self._evaluator.calculate_composite_power(team)

    def _sample_match(
        self,
        home: str,
        away: str,
        *,
        neutral: bool = True,
    ) -> tuple[int, int]:
        home_power = self._powers(home)
        away_power = self._powers(away)
        advantage = 0.0 if neutral else config.DEFAULT_HOME_ADV
        return self._engine.sample_match_score(home_power, away_power, advantage)

    def _group_fixtures(self, teams: list[str]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for i, home in enumerate(teams):
            for away in teams[i + 1 :]:
                pairs.append((home, away))
        return pairs

    def _simulate_group_once(self, teams: list[str]) -> list[tuple[str, int, int, int]]:
        """Return list of (team, points, gf, ga) sorted by ranking rules."""
        stats = {team: {"pts": 0, "gf": 0, "ga": 0} for team in teams}
        for home, away in self._group_fixtures(teams):
            hg, ag = self._sample_match(home, away)
            stats[home]["gf"] += hg
            stats[home]["ga"] += ag
            stats[away]["gf"] += ag
            stats[away]["ga"] += hg
            if hg > ag:
                stats[home]["pts"] += 3
            elif ag > hg:
                stats[away]["pts"] += 3
            else:
                stats[home]["pts"] += 1
                stats[away]["pts"] += 1

        ranked = sorted(
            teams,
            key=lambda t: (
                stats[t]["pts"],
                stats[t]["gf"] - stats[t]["ga"],
                stats[t]["gf"],
            ),
            reverse=True,
        )
        return [
            (team, stats[team]["pts"], stats[team]["gf"], stats[team]["ga"])
            for team in ranked
        ]

    def simulate_group(
        self,
        group: str,
        iterations: int = 500,
    ) -> list[GroupStandingEstimate]:
        teams = self._groups[group.upper()]
        top2_counts: dict[str, int] = {t: 0 for t in teams}
        win_counts: dict[str, int] = {t: 0 for t in teams}
        points_sum: dict[str, float] = {t: 0.0 for t in teams}

        for _ in range(iterations):
            table = self._simulate_group_once(teams)
            win_counts[table[0][0]] += 1
            for row in table[:2]:
                top2_counts[row[0]] += 1
            for team, pts, _, _ in table:
                points_sum[team] += pts

        return [
            GroupStandingEstimate(
                group=group.upper(),
                team=team,
                avg_points=round(points_sum[team] / iterations, 2),
                top2_probability=round(top2_counts[team] / iterations * 100, 1),
                win_group_probability=round(win_counts[team] / iterations * 100, 1),
            )
            for team in sorted(
                teams,
                key=lambda t: points_sum[t],
                reverse=True,
            )
        ]

    def simulate_all_groups(self, iterations: int = 300) -> dict[str, list[GroupStandingEstimate]]:
        return {
            letter: self.simulate_group(letter, iterations=iterations)
            for letter in self._groups
        }

    def simulate_champion(self, iterations: int = 1000) -> list[ChampionEstimate]:
        """
        Simplified WC knockout: seed all 48 teams by Elo, simulate single-elim bracket.
        Top 32 by Elo enter knockout (approximation of 2026 format).
        """
        teams = self._dm.list_teams()
        by_elo = sorted(
            teams,
            key=lambda t: self._dm.get_team_data(t)["elo"],
            reverse=True,
        )
        bracket = by_elo[:32]
        win_counts: dict[str, int] = {t: 0 for t in teams}

        for _ in range(iterations):
            remaining = list(bracket)
            self._rng.shuffle(remaining)
            while len(remaining) > 1:
                next_round: list[str] = []
                for i in range(0, len(remaining), 2):
                    if i + 1 >= len(remaining):
                        next_round.append(remaining[i])
                        continue
                    home, away = remaining[i], remaining[i + 1]
                    hg, ag = self._sample_match(home, away)
                    next_round.append(home if hg >= ag else away)
                remaining = next_round
            win_counts[remaining[0]] += 1

        ranked = sorted(win_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            ChampionEstimate(
                team=team,
                probability=round(count / iterations * 100, 2),
            )
            for team, count in ranked[:15]
            if count > 0
        ]

    def summary(self, iterations: int = 500) -> dict[str, Any]:
        groups = self.simulate_all_groups(iterations=iterations)
        champion = self.simulate_champion(iterations=iterations)
        return {
            "iterations": iterations,
            "groups": {
                letter: [g.__dict__ for g in standings]
                for letter, standings in groups.items()
            },
            "champion_odds": [c.__dict__ for c in champion],
        }
