"""Tests for rest/travel/weather context modifiers."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.context_adjustments import (
    apply_xg_context_delta,
    compute_context_adjustments,
)


def test_rest_penalty_short_turnaround() -> None:
    adj = compute_context_adjustments(
        home_rest_days=1,
        away_rest_days=5,
        away_travel_km=None,
    )
    assert adj.home_power_mult < 1.0
    assert adj.away_power_mult == 1.0
    assert any("עייפות" in n for n in adj.notes)


def test_travel_penalty_long_haul() -> None:
    adj = compute_context_adjustments(
        home_rest_days=5,
        away_rest_days=5,
        away_travel_km=4200,
    )
    assert adj.away_power_mult < 0.95
    assert any("נסיעה" in n for n in adj.notes)


def test_weather_reduces_total_xg() -> None:
    adj = compute_context_adjustments(
        home_rest_days=4,
        away_rest_days=4,
        away_travel_km=None,
        rain_mm=5.0,
        temp_c=34.0,
    )
    assert adj.xg_total_delta < 0
    home_xg, away_xg = apply_xg_context_delta(1.5, 1.2, adj.xg_total_delta)
    assert home_xg + away_xg < 2.7


def test_xg_delta_proportional() -> None:
    h, a = apply_xg_context_delta(2.0, 1.0, -0.3)
    assert round(h + a, 2) == 2.7
    assert h > a
