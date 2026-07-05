"""Tests for four-level data-driven served underdog xG cap."""

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


# --- four-tier classification --------------------------------------------


def test_tier_ultra_weak():
    assert classify_underdog_tier(0.10) == "ultra_weak"
    assert classify_underdog_tier(0.15) == "ultra_weak"


def test_tier_weak():
    assert classify_underdog_tier(0.16) == "weak"
    assert classify_underdog_tier(0.27) == "weak"
    assert classify_underdog_tier(0.30) == "weak"


def test_tier_medium_underdog():
    assert classify_underdog_tier(0.33) == "medium_underdog"
    assert classify_underdog_tier(0.50) == "medium_underdog"


def test_tier_strong_underdog():
    assert classify_underdog_tier(0.55) == "strong_underdog"
    assert classify_underdog_tier(0.67) == "strong_underdog"


# --- monotonic cap ordering across tiers ---------------------------------


def test_tier_cap_ordering_ultra_lt_weak_lt_medium():
    gap = 300.0
    ultra = compute_weak_underdog_cap(
        "ultra_weak", 0.12, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=130.0,
    )[0]
    weak = compute_weak_underdog_cap(
        "weak", 0.27, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=115.0,
    )[0]
    medium = compute_weak_underdog_cap(
        "medium_underdog", 0.33, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=200.0,
    )[0]
    assert ultra < weak < medium


# --- attack source -------------------------------------------------------


def test_resolve_attack_conflict_uses_min():
    used, source, raw, hist, conflict = resolve_cap_attack(
        pipeline_attack=0.58, raw_attack=0.27, gf_ga_fallback=False,
    )
    assert used == 0.27
    assert source == "min_source_conflict"
    assert conflict is True
    assert raw == 0.27
    assert hist == 0.58


def test_resolve_attack_fallback_uses_min():
    used, source, _, _, conflict = resolve_cap_attack(
        pipeline_attack=0.33, raw_attack=0.35, gf_ga_fallback=True,
    )
    assert used == 0.33
    assert source == "min_conservative"


def test_resolve_attack_pipeline_when_no_conflict():
    used, source, _, _, conflict = resolve_cap_attack(
        pipeline_attack=0.33, raw_attack=0.33, gf_ga_fallback=False,
    )
    assert used == 0.33
    assert source == "pipeline_get_team_data"
    assert conflict is False


# --- continuous cap inside tier ------------------------------------------


def test_lower_attack_lower_cap_within_ultra():
    gap = 250.0
    floor = config.ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_POWER_GAP_THRESHOLD
    lo = compute_weak_underdog_cap(
        "ultra_weak", 0.10, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    hi = compute_weak_underdog_cap(
        "ultra_weak", 0.14, favorite_defense=0.60, gf_ga_fallback=False,
        power_gap=gap, tier_gap_floor_value=floor,
    )[0]
    assert lo < hi


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


# --- integration ---------------------------------------------------------


def test_ultra_weak_capped():
    res = _cap(
        3.0, 0.83, away_attack=0.12, away_attack_raw=0.12,
        home_defense=0.88, power_gap=431.0, away_gf_ga_fallback=True,
    )
    assert res.applied is True
    assert res.tier == "ultra_weak"
    assert res.away_xg < 0.58
    assert res.home_xg == 3.0


def test_weak_tier_higher_than_ultra():
    ultra = _cap(3.0, 0.83, away_attack=0.12, power_gap=431.0)
    weak = _cap(2.6, 0.67, away_attack=0.27, away_attack_raw=0.27,
                home_power=948.0, away_power=828.0, power_gap=120.0)
    assert ultra.applied and weak.applied
    assert ultra.tier == "ultra_weak"
    assert weak.tier == "weak"
    assert weak.away_xg > ultra.away_xg


def test_dr_congo_weak_tier_capped_at_gap_120():
    """DR Congo: attack_used=0.27 (weak), gap~120 > weak floor 115 => capped."""
    res = _cap(
        2.6, 0.67,
        home_power=948.62, away_power=828.98,
        away_attack=0.58, away_attack_raw=0.27,
        home_defense=0.82, power_gap=119.65,
        away_gf_ga_fallback=False,
    )
    assert res.tier == "weak"
    assert res.attack_used == 0.27
    assert res.attack_source_conflict is True
    assert res.applied is True
    assert res.away_xg < 0.67


def test_medium_underdog_higher_than_weak():
    weak = _cap(2.6, 0.67, away_attack=0.27, power_gap=250.0)
    medium = _cap(2.68, 0.69, away_attack=0.33, power_gap=240.8)
    assert weak.applied and medium.applied
    assert medium.away_xg > weak.away_xg


def test_strong_underdog_preserved():
    res = _cap(2.0, 0.90, away_attack=0.55, home_defense=0.50, power_gap=250.0)
    assert res.applied is False
    assert res.reason == "strong_underdog_preserved"
    assert res.tier == "strong_underdog"
    assert res.away_xg == 0.90


def test_medium_skipped_when_gap_below_200():
    res = _cap(
        2.6, 0.67,
        home_power=948.62, away_power=828.98,
        away_attack=0.33, away_attack_raw=0.33,
        power_gap=119.65,
    )
    assert res.tier == "medium_underdog"
    assert res.applied is False
    assert res.reason == "gap_below_threshold"


def test_fallback_wiring_in_served_path():
    settings = Nr3FccIntegratedSettings(
        fusion_blowout_enabled=True, use_match_context=False, power_gap=420.0,
    )
    res = run_nr3_fcc_integrated_prediction(
        home_team="FavLand", away_team="DogLand", neutral_ground=True,
        home_power=1000.0, away_power=580.0, home_elo=1800.0, away_elo=1300.0,
        baseline_home_xg=2.4, baseline_away_xg=0.5,
        baseline_probabilities_1x2={"home_win": 78.0, "draw": 15.0, "away_win": 7.0},
        baseline_top_scores=[], home_advantage=0.0, settings=settings,
        home_attack=0.85, home_defense=0.55, away_attack=0.12, away_defense=0.20,
        away_gf_ga_fallback=True,
    )
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_gf_ga_fallback_used"] is True
    assert cap["active_model_weak_underdog_cap_applied"] is True


def test_served_strong_underdog_not_capped():
    settings = Nr3FccIntegratedSettings(
        fusion_blowout_enabled=True, use_match_context=False, power_gap=420.0,
    )
    res = run_nr3_fcc_integrated_prediction(
        home_team="FavLand", away_team="DogLand", neutral_ground=True,
        home_power=1000.0, away_power=580.0, home_elo=1800.0, away_elo=1300.0,
        baseline_home_xg=2.4, baseline_away_xg=0.5,
        baseline_probabilities_1x2={"home_win": 78.0, "draw": 15.0, "away_win": 7.0},
        baseline_top_scores=[], home_advantage=0.0, settings=settings,
        home_attack=0.85, home_defense=0.55, away_attack=0.55, away_defense=0.20,
    )
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_cap_applied"] is False
    assert cap["active_model_weak_underdog_cap_reason"] == "strong_underdog_preserved"


def test_disabled_flag_skips(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED", False)
    res = _cap(3.0, 0.83, away_attack=0.12, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "disabled"
