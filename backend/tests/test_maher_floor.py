"""Underdog xG floor tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.maher import compute_adaptive_underdog_floor, floor_underdog_xg


def test_floor_raises_weak_side_on_large_gap() -> None:
    # No team signals → backward-compatible standard floor (~0.8).
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


# --- Stage 2: adaptive underdog floor -------------------------------------


def test_adaptive_floor_lowers_for_weak_attack_fallback() -> None:
    """Haiti/Cape Verde style: very weak attack + fallback GF/GA + large gap."""
    home, away = floor_underdog_xg(
        2.0,
        0.35,
        998.0,
        582.0,
        0.0,
        away_attack=0.10,
        home_defense=0.88,
        away_gf_ga_fallback=True,
    )
    # Lowered well below the old 0.8 flat floor, into the target band, not zero.
    assert away < 0.8
    assert config.ADAPTIVE_UNDERDOG_FLOOR_MIN <= away <= 0.65
    assert home == 2.0


def test_adaptive_floor_respects_minimum() -> None:
    floor, reason = compute_adaptive_underdog_floor(
        420.0,
        underdog_attack=0.0,
        favorite_defense=0.99,
        gf_ga_fallback=True,
    )
    assert floor >= config.ADAPTIVE_UNDERDOG_FLOOR_MIN
    assert reason.startswith("adaptive_weak_underdog_floor")


def test_adaptive_floor_preserves_strong_underdog() -> None:
    """Attack above the weak threshold keeps the standard floor (no suppression)."""
    floor, reason = compute_adaptive_underdog_floor(
        420.0,
        underdog_attack=0.67,
        favorite_defense=0.88,
        gf_ga_fallback=True,
    )
    assert reason == "standard_floor_strong_attack"
    assert floor == round(min(0.8, 0.42 + 420.0 / 650.0), 2)


def test_adaptive_floor_fires_for_weak_attack_with_real_history() -> None:
    """Weak attack is the primary trigger even with real GF/GA (e.g. Cape Verde)."""
    floor, reason = compute_adaptive_underdog_floor(
        420.0,
        underdog_attack=0.10,
        favorite_defense=0.88,
        gf_ga_fallback=False,
    )
    assert reason == "adaptive_weak_underdog_floor"
    assert floor < round(min(0.8, 0.42 + 420.0 / 650.0), 2)
    assert config.ADAPTIVE_UNDERDOG_FLOOR_MIN <= floor <= 0.65


def test_adaptive_floor_fallback_lowers_a_touch_more() -> None:
    real, _ = compute_adaptive_underdog_floor(
        420.0, underdog_attack=0.10, favorite_defense=0.88, gf_ga_fallback=False
    )
    fallback, reason = compute_adaptive_underdog_floor(
        420.0, underdog_attack=0.10, favorite_defense=0.88, gf_ga_fallback=True
    )
    assert fallback <= real
    assert reason == "adaptive_weak_underdog_floor_fallback"


def test_adaptive_floor_weaker_attack_gets_lower_floor() -> None:
    weak, _ = compute_adaptive_underdog_floor(
        420.0, underdog_attack=0.10, favorite_defense=0.88, gf_ga_fallback=True
    )
    less_weak, _ = compute_adaptive_underdog_floor(
        420.0, underdog_attack=0.33, favorite_defense=0.88, gf_ga_fallback=True
    )
    assert weak <= less_weak


def test_floor_diagnostics_populated() -> None:
    diag: dict = {}
    floor_underdog_xg(
        2.0,
        0.35,
        998.0,
        582.0,
        0.0,
        away_attack=0.10,
        home_defense=0.88,
        away_gf_ga_fallback=True,
        diagnostics=diag,
    )
    assert diag["underdog_side"] == "away"
    assert diag["underdog_floor_reason"].startswith("adaptive_weak_underdog_floor")
    assert diag["underdog_floor_standard"] is not None
    assert diag["underdog_floor_adaptive"] <= diag["underdog_floor_standard"]


def test_adaptive_floor_disabled_restores_standard(monkeypatch) -> None:
    monkeypatch.setattr(config, "ADAPTIVE_UNDERDOG_FLOOR_ENABLED", False)
    floor, reason = compute_adaptive_underdog_floor(
        420.0, underdog_attack=0.10, favorite_defense=0.88, gf_ga_fallback=True
    )
    assert reason == "standard_floor_disabled"
    assert floor == round(min(0.8, 0.42 + 420.0 / 650.0), 2)


def test_adaptive_floor_no_attack_signal_uses_standard() -> None:
    floor, reason = compute_adaptive_underdog_floor(
        420.0, underdog_attack=None, favorite_defense=0.88, gf_ga_fallback=True
    )
    assert reason == "standard_floor_no_attack_signal"
    assert floor == round(min(0.8, 0.42 + 420.0 / 650.0), 2)
