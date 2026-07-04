"""Tests for the served (NR3-FCC) attack-aware weak-underdog xG cap."""

from __future__ import annotations

import config
import pytest

from core.active_model_weak_underdog_cap import (
    apply_weak_underdog_xg_cap,
    compute_weak_underdog_cap,
)
from core.nr3_fcc_served_integration import (
    Nr3FccIntegratedSettings,
    run_nr3_fcc_integrated_prediction,
)


# --- direct unit tests on the cap helper ---------------------------------


def _cap(home_xg, away_xg, **kw):
    base = dict(home_power=1000.0, away_power=580.0)
    base.update(kw)
    return apply_weak_underdog_xg_cap(home_xg, away_xg, **base)


def test_weak_underdog_capped_cape_verde_like():
    res = _cap(3.0, 0.83, away_attack=0.12, home_defense=0.52, power_gap=431.0)
    assert res.applied is True
    assert res.underdog_side == "away"
    assert res.away_xg < 0.83
    assert res.away_xg == pytest.approx(0.58, abs=0.01)
    assert res.home_xg == 3.0  # favorite untouched
    assert res.reason == "weak_underdog_cap_applied"


def test_strong_underdog_preserved_croatia_like():
    res = _cap(2.0, 0.90, away_attack=0.55, home_defense=0.50, power_gap=250.0)
    assert res.applied is False
    assert res.reason == "strong_attack_preserved"
    assert res.away_xg == 0.90


def test_curacao_edge_reduces_but_not_collapse():
    res = _cap(2.68, 0.69, away_attack=0.33, home_defense=0.60, power_gap=240.8)
    assert res.applied is True
    # attack 0.33 near threshold -> cap near MAX_XG_HIGH, clearly above MIN.
    assert res.away_xg == pytest.approx(0.63, abs=0.02)
    assert res.away_xg > config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG


def test_no_cap_when_gap_below_threshold():
    res = _cap(1.8, 0.85, home_power=900.0, away_power=800.0, away_attack=0.12, power_gap=100.0)
    assert res.applied is False
    assert res.reason == "gap_below_threshold"


def test_no_cap_when_underdog_already_below_cap():
    res = _cap(3.0, 0.50, away_attack=0.12, home_defense=0.52, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "underdog_xg_at_or_below_cap"
    assert res.away_xg == 0.50  # never raised (cap is a max, not a floor)


def test_no_attack_signal_skips():
    res = _cap(3.0, 0.83, away_attack=None, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "no_attack_signal"


def test_home_underdog_side_capped():
    res = apply_weak_underdog_xg_cap(
        0.85, 3.0, home_power=560.0, away_power=1000.0,
        home_attack=0.12, away_defense=0.55, power_gap=-440.0,
    )
    assert res.applied is True
    assert res.underdog_side == "home"
    assert res.home_xg == pytest.approx(0.58, abs=0.01)
    assert res.away_xg == 3.0


def test_disabled_flag_skips(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED", False)
    res = _cap(3.0, 0.83, away_attack=0.12, power_gap=431.0)
    assert res.applied is False
    assert res.reason == "disabled"
    assert res.away_xg == 0.83


def test_favorite_defense_strong_tightens_cap():
    weak_def = compute_weak_underdog_cap(0.12, favorite_defense=0.50, gf_ga_fallback=False)
    strong_def = compute_weak_underdog_cap(0.12, favorite_defense=0.75, gf_ga_fallback=False)
    assert strong_def < weak_def


def test_fallback_tightens_cap():
    no_fb = compute_weak_underdog_cap(0.20, favorite_defense=0.5, gf_ga_fallback=False)
    fb = compute_weak_underdog_cap(0.20, favorite_defense=0.5, gf_ga_fallback=True)
    assert fb < no_fb


def test_cap_never_below_min_xg():
    cap = compute_weak_underdog_cap(0.0, favorite_defense=0.95, gf_ga_fallback=True)
    assert cap >= config.ACTIVE_MODEL_WEAK_UNDERDOG_MIN_XG


# --- integration through the served NR3-FCC pipeline ---------------------


def _served(away_attack, away_power=580.0):
    settings = Nr3FccIntegratedSettings(
        fusion_blowout_enabled=True,
        use_match_context=False,
        power_gap=1000.0 - away_power,
    )
    return run_nr3_fcc_integrated_prediction(
        home_team="FavLand",
        away_team="DogLand",
        neutral_ground=True,
        home_power=1000.0,
        away_power=away_power,
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
        away_attack=away_attack,
        away_defense=0.20,
    )


def test_served_weak_underdog_is_capped():
    res = _served(away_attack=0.12)
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_cap_applied"] is True
    assert res["shadow_away_xg"] <= 0.60
    assert res["shadow_away_xg"] < cap["active_model_weak_underdog_cap_original_xg"]
    # cap step recorded in the decomposition
    steps = {a["name"]: a for a in res["nr3_xg_decomposition"]["adjustments"]}
    assert steps["weak_underdog_cap"]["status"] == "applied"


def test_served_strong_underdog_not_capped():
    res = _served(away_attack=0.55)
    cap = res["weak_underdog_cap"]
    assert cap["active_model_weak_underdog_cap_applied"] is False
    assert cap["active_model_weak_underdog_cap_reason"] == "strong_attack_preserved"
    steps = {a["name"]: a for a in res["nr3_xg_decomposition"]["adjustments"]}
    assert steps["weak_underdog_cap"]["status"] == "skipped"


def test_served_favorite_xg_unchanged_by_cap():
    weak = _served(away_attack=0.12)
    # favorite (home) side should be a strong blowout value, unaffected by the dog cap
    assert weak["shadow_home_xg"] >= 2.0
