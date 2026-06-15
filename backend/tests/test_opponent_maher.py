"""Tests for per-opponent Maher xG."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.opponent_maher import build_opponent_index, estimate_xg_opponent_aware
from data.database import FIFA_ELO_2026
from data.nt_match import NationalTeamMatch


def test_opponent_index_tracks_pair_rates() -> None:
    matches = [
        NationalTeamMatch("2024-01-01", "Brazil", "France", 2, 0),
        NationalTeamMatch("2024-02-01", "France", "Brazil", 1, 1),
    ]
    index = build_opponent_index(matches, set(FIFA_ELO_2026.keys()))
    brazil_key = "Brazil (ברזיל)"
    france_key = "France (צרפת)"
    br_vs_fr = index[(brazil_key, france_key)]
    assert br_vs_fr.matches == 2
    assert br_vs_fr.goals_for_per_game == 1.5


def test_opponent_aware_xg_differs_from_global_when_h2h_exists() -> None:
    matches = [
        NationalTeamMatch("2024-01-01", "Brazil", "France", 3, 0),
        NationalTeamMatch("2024-02-01", "Brazil", "France", 3, 0),
    ]
    index = build_opponent_index(matches, set(FIFA_ELO_2026.keys()))
    home_xg, away_xg, note = estimate_xg_opponent_aware(
        "Brazil (ברזיל)",
        "France (צרפת)",
        1.5,
        1.0,
        1.4,
        1.1,
        index,
        global_avg=2.6,
    )
    assert home_xg > away_xg
    assert "Maher" in note
