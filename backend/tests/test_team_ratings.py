"""Team ratings from national-team match history."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.team_ratings import TeamRatingsCalculator  # noqa: E402
from data.database import LiveDataManager  # noqa: E402
from data.nt_history_bundle import BUNDLED_NT_MATCHES  # noqa: E402
from data.nt_match import NationalTeamMatch  # noqa: E402


def test_bundled_includes_qualifiers() -> None:
    assert len(BUNDLED_NT_MATCHES) >= 300


def test_ratings_use_history_for_wc_teams() -> None:
    calculator = TeamRatingsCalculator()
    ratings = calculator.compute(list(BUNDLED_NT_MATCHES))
    brazil = ratings["Brazil (ברזיל)"]
    assert brazil.matches_used >= 6
    assert brazil.rating_source == "history_blend"
    assert 0.05 <= brazil.attack <= 0.95


def test_unknown_team_keeps_baseline() -> None:
    calculator = TeamRatingsCalculator()
    ratings = calculator.compute([])
    haiti = ratings["Haiti (האיטי)"]
    assert haiti.matches_used == 0
    assert haiti.rating_source == "fifa_baseline"


def test_merge_deduplicates_matches() -> None:
    from core.team_ratings import merge_matches

    m = NationalTeamMatch(
        date="2022-11-20",
        home="Qatar",
        away="Ecuador",
        home_goals=0,
        away_goals=2,
        competition="FIFA World Cup",
    )
    merged = merge_matches([m, m])
    assert len(merged) == 1


def test_live_data_manager_applies_history_ratings() -> None:
    from core.team_ratings import build_and_save_ratings

    build_and_save_ratings()
    dm = LiveDataManager()
    brazil = dm.get_team_data("Brazil")
    assert brazil.get("matches_used", 0) >= 6
    assert "attack" in brazil


def test_competition_weight() -> None:
    from data.nt_match import competition_weight

    assert competition_weight("World Cup Qualification UEFA") == 0.75
    assert competition_weight("Friendlies") == 0.5
