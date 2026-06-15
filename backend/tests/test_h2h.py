"""H2H adjustment tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.h2h_adjustment import (
    apply_h2h_adjustment,
    build_h2h_index,
    lookup_h2h,
)
from data.nt_match import NationalTeamMatch


def _sample_matches() -> list[NationalTeamMatch]:
    return [
        NationalTeamMatch("2020-01-01", "Brazil", "Argentina", 2, 0),
        NationalTeamMatch("2021-01-01", "Argentina", "Brazil", 1, 1),
        NationalTeamMatch("2022-01-01", "Brazil", "Argentina", 3, 1),
        NationalTeamMatch("2023-01-01", "Argentina", "Brazil", 0, 2),
    ]


def test_h2h_index_requires_min_three_matches() -> None:
    registry = {"Brazil (ברזיל)", "Argentina (ארגנטינה)"}
    index = build_h2h_index(_sample_matches(), registry)
    assert len(index) == 1
    summary = lookup_h2h(index, "Brazil (ברזיל)", "Argentina (ארגנטינה)")
    assert summary is not None
    assert summary.match_count == 4


def test_h2h_adjustment_shifts_power() -> None:
    registry = {"Brazil (ברזיל)", "Argentina (ארגנטינה)"}
    index = build_h2h_index(_sample_matches(), registry)
    summary = lookup_h2h(index, "Brazil (ברזיל)", "Argentina (ארגנטינה)")
    home, away, note = apply_h2h_adjustment(1600.0, 1580.0, summary)
    assert home != 1600.0 or away != 1580.0
    assert "מפגשים ישירים" in note


def test_h2h_skipped_when_insufficient_history() -> None:
    home, away, note = apply_h2h_adjustment(1600.0, 1580.0, None)
    assert home == 1600.0
    assert away == 1580.0
    assert note == ""
