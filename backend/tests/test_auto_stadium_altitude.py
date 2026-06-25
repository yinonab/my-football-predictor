"""Auto stadium altitude resolution for power modifiers."""

from __future__ import annotations

import sys
from pathlib import Path

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


def test_stadium_altitude_when_enabled() -> None:
    alt, auto, source = resolve_effective_altitude_m(
        request_altitude=0,
        venue_city="Mexico City",
        auto_stadium_altitude=True,
    )
    assert alt == 2240
    assert auto is True
    assert source == "static_metadata"


def test_stadium_altitude_disabled_by_request_flag() -> None:
    alt, auto, source = resolve_effective_altitude_m(
        request_altitude=0,
        venue_city="Mexico City",
        auto_stadium_altitude=False,
    )
    assert alt == 0
    assert auto is False
    assert source == "user_disabled"
