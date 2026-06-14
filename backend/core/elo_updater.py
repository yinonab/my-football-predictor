"""Dynamic Elo rating updates from match results."""

from __future__ import annotations

import math


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400))


def actual_score(home_goals: int, away_goals: int) -> tuple[float, float]:
    if home_goals > away_goals:
        return 1.0, 0.0
    if away_goals > home_goals:
        return 0.0, 1.0
    return 0.5, 0.5


def goal_diff_multiplier(home_goals: int, away_goals: int) -> float:
    """FIFA-style margin-of-victory multiplier (capped)."""
    diff = abs(home_goals - away_goals)
    if diff <= 1:
        return 1.0
    if diff == 2:
        return 1.5
    return (11 + diff) / 8.0


def update_elo_pair(
    home_elo: float,
    away_elo: float,
    home_goals: int,
    away_goals: int,
    *,
    k: float = 40.0,
    home_advantage: float = 0.0,
) -> tuple[float, float, dict[str, float]]:
    """
    Return updated (home_elo, away_elo) after a single match.
    home_advantage is added to home rating for expectation only.
    """
    exp_home = expected_score(home_elo + home_advantage, away_elo)
    exp_away = 1.0 - exp_home
    act_home, act_away = actual_score(home_goals, away_goals)
    mult = goal_diff_multiplier(home_goals, away_goals)

    delta_home = k * mult * (act_home - exp_home)
    delta_away = k * mult * (act_away - exp_away)

    new_home = round(home_elo + delta_home, 1)
    new_away = round(away_elo + delta_away, 1)
    return new_home, new_away, {
        "home_delta": round(delta_home, 1),
        "away_delta": round(delta_away, 1),
        "expected_home": round(exp_home, 3),
    }
