"""Auto stadium altitude resolution for power modifiers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.venue_environment import resolve_effective_altitude_m


def test_manual_altitude_overrides_stadium() -> None:
    alt, auto, source = resolve_effective_altitude_m(
        request_altitude=1500,
        venue_city="Mexico City",
    )
    assert alt == 1500
    assert auto is False
    assert source == "request_override"


def test_stadium_altitude_when_no_manual_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.venue_environment.config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION",
        True,
    )
    alt, auto, source = resolve_effective_altitude_m(
        request_altitude=0,
        venue_city="Mexico City",
    )
    assert alt == 2240
    assert auto is True
    assert source == "static_metadata"


def test_stadium_altitude_disabled_by_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.venue_environment.config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION",
        False,
    )
    alt, auto, source = resolve_effective_altitude_m(
        request_altitude=0,
        venue_city="Mexico City",
    )
    assert alt == 0
    assert auto is False
    assert source == "disabled"
