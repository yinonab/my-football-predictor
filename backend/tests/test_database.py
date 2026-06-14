"""Tests for official WC 2026 database."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from data.database import FIFA_ELO_2026, LiveDataManager, compute_derived_metrics


def test_exactly_48_teams() -> None:
    dm = LiveDataManager()
    assert len(dm.list_teams()) == 48
    assert len(FIFA_ELO_2026) == 48


def test_argentina_top_elo() -> None:
    dm = LiveDataManager()
    data = dm.get_team_data("Argentina (ארגנטינה)")
    assert data["elo"] == 1877


def test_derived_metrics_in_range() -> None:
    for elo in [1255, 1500, 1877]:
        m = compute_derived_metrics(elo)
        assert 0.0 <= m["form"] <= 1.0
        assert 0.0 <= m["attack"] <= 1.0
        assert 0.0 <= m["defense"] <= 1.0


def test_hebrew_alias_resolution() -> None:
    dm = LiveDataManager()
    _, data = dm.resolve_team("אוסטרליה")
    assert data["elo"] == 1595


def test_new_wc_teams_present() -> None:
    dm = LiveDataManager()
    teams = dm.list_teams()
    assert "Haiti (האיטי)" in teams
    assert "Curacao (קוראסאו)" in teams
    assert "DR Congo (קונגו)" in teams
    assert "Cape Verde (כף ורד)" in teams


def test_removed_non_wc_teams() -> None:
    dm = LiveDataManager()
    teams = dm.list_teams()
    assert "Italy (איטליה)" not in teams
    assert "Poland (פולין)" not in teams
    assert "Chile (צ'ילה)" not in teams
