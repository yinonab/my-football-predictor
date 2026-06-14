"""Tests for Elo updater, tournament sim, and new API endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.elo_updater import update_elo_pair
from core.tournament_sim import TournamentSimulator
from data.database import LiveDataManager


def test_elo_update_after_home_win() -> None:
    new_h, new_a, meta = update_elo_pair(1700, 1500, 2, 0)
    assert new_h > 1700
    assert new_a < 1500
    assert meta["home_delta"] > 0


def test_elo_update_draw() -> None:
    new_h, new_a, _ = update_elo_pair(1600, 1600, 1, 1)
    assert abs(new_h - 1600) < 5
    assert abs(new_a - 1600) < 5


def test_tournament_sim_group() -> None:
    sim = TournamentSimulator(seed=42)
    standings = sim.simulate_group("A", iterations=100)
    assert len(standings) == 4
    assert sum(s.top2_probability for s in standings) > 150


def test_tournament_champion_odds_sum() -> None:
    sim = TournamentSimulator(seed=7)
    odds = sim.simulate_champion(iterations=200)
    assert len(odds) >= 5
    assert odds[0].probability >= odds[1].probability


def test_list_groups_has_12() -> None:
    dm = LiveDataManager()
    groups = dm.list_groups()
    assert len(groups) == 12
    assert len(groups["A"]) == 4
