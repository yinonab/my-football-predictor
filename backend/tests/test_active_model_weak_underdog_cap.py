"""Tests for hybrid tier + continuous served weak-underdog xG cap."""

from __future__ import annotations

import config
import pytest

from core.active_model_weak_underdog_cap import (
    apply_weak_underdog_xg_cap,
    classify_underdog_tier,
    compute_weak_underdog_cap,
    resolve_cap_attack,
)
from core.nr3_fcc_served_integration import (
    Nr3FccIntegratedSettings,
    run_nr3_fcc_integrated_prediction,
)


def _cap(home_xg, away_xg, **kw):
    base = dict(home_power=1000.0, away_power=580.0)
    base.update(kw)
    return apply_weak_underdog_xg_cap(home_xg, away_xg, **base)


# --- tier classification -------------------------------------------------


def test_tier_ultra_weak():
    assert classify_underdog_tier(0.10) == "ultra_weak"
    assert classify_underdog_tier(config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_ATTACK_THRESHOLD) == "ultra_weak"


def test_tier_medium_weak():
    assert classify_underdog_tier(0.20) == "medium_weak"
    assert classify_underdog_tier(0.33) == "medium_weak"
    assert classify_underdog_tier(config.ACTIVE_MODEL_WEAK_UNDERDOG_ATTACK_THRESHOLD) == "medium_weak"


def test_tier_strong():
    assert classify_underdog_tier(0.55) == "strong"
    assert classify_underdog_tier(0.67) == "strong"


# --- attack source resolution --------------------------------------------


def test_resolve_attack_fallback_uses_min():
    used, source, raw, hist = resolve_cap_attack(
        pipeline_attack=0.58,
        raw_attack=0.27,
        gf_ga_fallback=True,
    )
    assert used == 0.27
    assert source in ("min_fallback_conservative", "min_source_conflict")
    assert raw == 0.27
    assert hist == 0.58


def test_resolve_attack_conflict_uses_min():
    used, source, _, _ = resolve_cap_attack(
        pipeline_attack=0.58,
        raw_attack=0.27,
        gf_ga_fallback=False,
    )
    assert used == 0.27
    assert source == "min_source_conflict"


def test_resolve_attack_pipeline_when_no_conflict():
    used, source, _, _ = resolve_cap_attack(
        pipeline_attack=0.33,
        raw_attack=0.33,
        gf_ga_fallback=True,
    )
    assert used == 0.33
    assert source == "pipeline_get_team_data"


# --- monotonicity --------------------------------------------------------


def test_lower_attack_lower_cap_within_ultra():
    gap = 250.0
    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    weak = compute_weak_underdog_cap(
        "ultra_weak", 0.10, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    strong = compute_weak_underdog_cap(
        "ultra_weak", 0.14, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    assert weak < strong


def test_stronger_defense_lowers_cap():
    gap = 250.0
    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    weak_def = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.50, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    strong_def = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.80, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    assert strong_def < weak_def


def test_fallback_lowers_cap():
    gap = 250.0
    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    no_fb = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    fb = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.60, gf_ga_fallback=True,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    assert fb < no_fb


def test_bigger_gap_lowers_ultra_cap():
    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    small_gap = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=160.0, tier_gap_floor_value=floor,
    )[0]
    big_gap = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=400.0, tier_gap_floor_value=floor,
    )[0]
    assert big_gap < small_gap


# --- apply cap integration ------------------------------------------------


def test_ultra_weak_capped_lower_than_legacy_band():
    res = _cap(
        3.0, 0.83,
        away_attack=0.12,
        away_attack_raw=0.12,
        home_defense=0.88,
        power_gap=431.0,
        away_gf_ga_fallback=True,
    )
    assert res.applied is True
    assert res.tier == "ultra_weak"
    assert res.away_xg < 0.58  # below old ~0.58 cap
    assert res.away_xg >= config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG
    assert res.home_xg == 3.0


def test_medium_weak_higher_cap_than_ultra():
    ultra = _cap(3.0, 0.83, away_attack=0.12, power_gap=431.0)
    medium = _cap(2.68, 0.69, away_attack=0.33, power_gap=240.8)
    assert ultra.applied and medium.applied
    assert medium.away_xg > ultra.away_xg


def test_strong_underdog_preserved_croatia_like():
    res = _cap(2.0, 0.90, away_attack=0.55, home_defense=0.50, power_gap=250.0)
    assert res.applied is False
    assert res.reason == "strong_attack_preserved"
    assert res.tier == "strong"
    assert res.away_xg == 0.90


def test_no_cap_when_gap_below_tier_floor():
    res = _cap(
        1.8, 0.85,
        home_power=900.0, away_power=800.0,
        away_attack=0.12, power_gap=100.0,
    )
    assert res.applied is False
    assert res.reason == "gap_below_threshold"


def test_no_cap_when_underdog_already_below_cap():
    res = _cap(3.0, 0.35, away_attack=0.12, home_defense=0.52, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "underdog_xg_at_or_below_cap"
    assert res.away_xg == 0.35


def test_fallback_wiring_in_served_path():
    settings = Nr3FccIntegratedSettings(
        fusion_blowout_enabled=True,
        use_match_context=False,
        power_gap=420.0,
    )
    res = run_nr3_fcc_integrated_prediction(
        home_team="FavLand",
        away_team="DogLand",
        neutral_ground=True,
        home_power=1000.0,
        away_power=580.0,
        home_elo=1800.0,
        away_elo=1300.0,
        baseline_home_xg=2.4,
        baseline_away_xg=0.5,
        baseline_probabilities_1x2={"home_win": 78.0, "draw": 15.0, "away_win": 7.0},
        baseline_top_scores=[],
        home_advantage=0.0,
        settings=settings,
        home_attack=0.85,
        home_defense=0.55,
        away_attack=0.12,
        away_defense=0.20,
        away_gf_ga_fallback=True,
    )
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_gf_ga_fallback_used"] is True
    assert cap["active_model_weak_underdog_cap_applied"] is True


def test_served_strong_underdog_not_capped():
    settings = Nr3FccIntegratedSettings(
        fusion_blowout_enabled=True,
        use_match_context=False,
        power_gap=420.0,
    )
    res = run_nr3_fcc_integrated_prediction(
        home_team="FavLand",
        away_team="DogLand",
        neutral_ground=True,
        home_power=1000.0,
        away_power=580.0,
        home_elo=1800.0,
        away_elo=1300.0,
        baseline_home_xg=2.4,
        baseline_away_xg=0.5,
        baseline_probabilities_1x2={"home_win": 78.0, "draw": 15.0, "away_win": 7.0},
        baseline_top_scores=[],
        home_advantage=0.0,
        settings=settings,
        home_attack=0.85,
        home_defense=0.55,
        away_attack=0.55,
        away_defense=0.20,
    )
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_cap_applied"] is False
    assert cap["active_model_weak_underdog_cap_reason"] == "strong_attack_preserved"


def test_disabled_flag_skips(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED", False)
    res = _cap(3.0, 0.83, away_attack=0.12, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "disabled"


def test_cap_never_below_min_xg():
    cap, _, _ = compute_weak_underdog_cap(
        "ultra_weak",
        0.0,
        favorite_defense=0.95,
        gf_ga_fallback=True,
        power_gap=500.0,
        tier_gap_floor_value=150.0,
    )
    assert cap >= config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG
