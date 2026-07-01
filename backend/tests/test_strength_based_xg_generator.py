"""Tests for Priority 1.7B strength-based xG generator (runtime-only)."""

from __future__ import annotations

import inspect

from core.priority1_options import Priority1Config
from core.strength_based_xg_generator import (
    GENERATOR_VERSION,
    P1C2_SHADOW_NAME,
    StrengthSignals,
    StrengthXgParams,
    _apply_favorite_share_boost,
    build_p1c_narrow_grid,
    build_strength_xg_grid,
    generate_strength_based_xg,
    p1c2_shadow_params,
    source_uses_global_xg_avg,
)
from core.strength_stage_recovery import StageRecoveryParams, apply_stage_recovery, stage_recovery_applies

import config


def _signals(**kwargs) -> StrengthSignals:
    defaults = dict(
        home_team="Brazil",
        away_team="France",
        home_power=900.0,
        away_power=880.0,
        home_elo=2100.0,
        away_elo=2080.0,
        home_attack=0.62,
        home_defense=0.58,
        away_attack=0.60,
        away_defense=0.61,
        population_powers=[800.0, 900.0, 1000.0, 850.0, 920.0, 870.0],
    )
    defaults.update(kwargs)
    return StrengthSignals(**defaults)


def _params(**kwargs) -> StrengthXgParams:
    defaults = dict(
        name="test",
        scale=-0.4,
        overall_weight=0.15,
        opponent_overall_weight=0.12,
        gap_weight=0.10,
        use_attack_defense=False,
    )
    defaults.update(kwargs)
    return StrengthXgParams(**defaults)


def test_production_defaults_unchanged():
    assert config.STRENGTH_BASED_XG_ENABLED is False
    assert config.XG_BASELINE_GENERATOR == "current"
    assert config.strength_based_xg_enabled() is False
    assert config.NR3_FCC_SHADOW_ENABLED is False


def test_flag_off_baseline_config():
    p1 = Priority1Config.baseline()
    assert p1.xg_baseline_generator == "current"
    assert p1.strength_xg_params is None


def test_generator_does_not_reference_global_xg_avg():
    assert source_uses_global_xg_avg() is False
    src = inspect.getsource(generate_strength_based_xg)
    assert "GLOBAL_XG_AVG" not in src
    assert "config.GLOBAL_XG_AVG" not in src


def test_no_literal_2_6_in_formula():
    src = inspect.getsource(generate_strength_based_xg)
    assert "2.6" not in src


def test_total_is_sum_of_sides():
    h, a, diag = generate_strength_based_xg(_signals(), _params())
    assert diag["total"]["total_xg"] == round(h + a, 3)
    assert h > 0 and a > 0


def test_stronger_home_power_increases_home_xg():
    base_h, _, _ = generate_strength_based_xg(_signals(home_power=850), _params())
    strong_h, _, _ = generate_strength_based_xg(_signals(home_power=1050), _params())
    assert strong_h >= base_h


def test_stronger_away_attack_increases_away_xg():
    p = _params(use_attack_defense=True, attack_weight=0.2, defense_weight=0.2, overall_weight=0.05)
    _, low_a, _ = generate_strength_based_xg(_signals(away_attack=0.45), p)
    _, high_a, _ = generate_strength_based_xg(_signals(away_attack=0.75), p)
    assert high_a >= low_a


def test_opponent_defense_reduces_side_xg():
    p = _params(use_attack_defense=True, attack_weight=0.2, defense_weight=0.25, overall_weight=0.05)
    weak_def_h, _, _ = generate_strength_based_xg(_signals(away_defense=0.40), p)
    strong_def_h, _, _ = generate_strength_based_xg(_signals(away_defense=0.80), p)
    assert weak_def_h >= strong_def_h


def test_min_side_cap():
    p = _params(scale=-3.0, min_side=0.25)
    h, a, _ = generate_strength_based_xg(_signals(), p)
    assert h >= 0.25 and a >= 0.25


def test_max_side_cap():
    p = _params(scale=1.5, overall_weight=0.8, max_side=1.5)
    h, a, _ = generate_strength_based_xg(_signals(), p)
    assert h <= 1.5 and a <= 1.5


def test_max_total_scales_proportionally():
    p = _params(scale=0.5, overall_weight=0.5, max_side=3.0, max_total=2.0)
    h, a, diag = generate_strength_based_xg(_signals(), p)
    assert round(h + a, 2) <= 2.0 + 1e-6
    if diag["total"]["total_cap_applied"]:
        assert diag["total"]["total_scale_factor_if_capped"] is not None


def test_missing_attack_defense_fallback():
    p = _params(use_attack_defense=True, attack_weight=0.2, overall_weight=0.0)
    h, a, diag = generate_strength_based_xg(
        _signals(home_attack=None, away_attack=None, home_defense=None, away_defense=None),
        p,
    )
    assert h > 0 and a > 0
    assert "missing_attack_signal" in diag["warnings"]


def test_overall_power_only_variant():
    p = _params(use_attack_defense=False, overall_weight=0.2, gap_weight=0.1)
    _, _, diag = generate_strength_based_xg(_signals(), p)
    assert "overall_power" in diag["data_signals_used"]
    assert diag["uses_global_xg_avg"] is False
    assert diag["uses_fixed_2_6"] is False


def test_diagnostics_expose_parameters():
    _, _, diag = generate_strength_based_xg(_signals(), _params())
    assert diag["parameters"]["scale"] == -0.4
    assert diag["generator_version"] == GENERATOR_VERSION
    assert diag["uses_global_xg_avg"] is False
    assert "no_global_xg_avg_used" in diag["warnings"]


def test_diagnostics_baseline_comparison():
    _, _, diag = generate_strength_based_xg(
        _signals(), _params(), baseline_home_xg=1.2, baseline_away_xg=1.4
    )
    cmp_ = diag["comparison_to_current_baseline"]
    assert cmp_["current_baseline_total_xg"] == 2.6
    assert "delta_total_xg" in cmp_


def test_grid_not_empty():
    grid = build_strength_xg_grid()
    assert len(grid) >= 20


def test_p1c_narrow_grid_size():
    grid = build_p1c_narrow_grid()
    assert len(grid) == 10 * 6 * 5 * 4
    assert all(p.signal_mode == "share_stronger_total_safe" for _, p in grid)


def test_favorite_share_boost_preserves_total():
    p = _params(
        scale=0.05,
        favorite_share_boost=0.04,
        favorite_share_boost_start=0.52,
        max_favorite_share=0.70,
    )
    h, a = 1.35, 0.95
    nh, na, applied = _apply_favorite_share_boost(h, a, p)
    assert applied is True
    assert abs((nh + na) - (h + a)) < 0.01


def test_p1c2_shadow_params():
    p = p1c2_shadow_params()
    assert p.name == P1C2_SHADOW_NAME
    assert p.favorite_share_boost == 0.06
    assert p.max_favorite_share == 0.68


def test_r16_recovery_applies_only_for_r16_scope():
    p = StageRecoveryParams(
        name="t",
        enabled=True,
        stage_scope="r16_only",
        total_recovery_weight=0.5,
        max_total_recovery_delta=0.4,
    )
    h, a, d = apply_stage_recovery(1.0, 1.0, 2.0, 2.0, "group", p)
    assert h == 1.0 and a == 1.0
    assert d["recovery_applied"] is False
    h2, a2, d2 = apply_stage_recovery(1.0, 1.0, 2.5, 2.5, "r16", p)
    assert h2 + a2 > 2.0
    assert d2["recovery_applied"] is True


def test_knockout_recovery_scope():
    p = StageRecoveryParams(name="k", enabled=True, stage_scope="knockout_all")
    assert stage_recovery_applies("qf", p) is True
    assert stage_recovery_applies("group", p) is False


def test_missing_stage_handled_safely():
    p = StageRecoveryParams(name="m", enabled=True, stage_scope="r16_only")
    h, a, d = apply_stage_recovery(1.0, 1.0, 1.5, 1.5, None, p)
    assert h == 1.0 and a == 1.0
    assert d["recovery_applied"] is False
