"""Underdog xG floor tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.maher import floor_underdog_xg


def test_floor_raises_weak_side_on_large_gap() -> None:
    home, away = floor_underdog_xg(2.2, 0.35, 998.0, 582.0, 0.0)
    assert away >= 0.8
    assert home == 2.2


def test_floor_inactive_on_medium_gap() -> None:
    home, away = floor_underdog_xg(1.55, 1.05, 938.0, 829.0, 0.0)
    assert home == 1.55
    assert away == 1.05


def test_floor_inactive_on_close_match() -> None:
    home, away = floor_underdog_xg(1.3, 1.2, 850.0, 840.0, 0.0)
    assert home == 1.3
    assert away == 1.2
