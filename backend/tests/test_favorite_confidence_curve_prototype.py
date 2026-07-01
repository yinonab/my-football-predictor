"""Tests for P1.7B.16 favorite confidence curve runtime (shadow sidecar only)."""

from __future__ import annotations

import config
from core.favorite_confidence_curve_prototype import (
    NOT_ACTIVATION,
    PROTOTYPE_NAME,
    SHADOW_ONLY_LABEL,
    apply_favorite_confidence_curve,
    build_fcc_stack,
    fcc_fixed_params,
    run_pre_prototype_sanity_checks,
)
from core.priority1_options import Priority1Config
from core.strength_based_xg_generator import p1c2_shadow_params, source_uses_global_xg_avg


class _Match:
    def __init__(self, home: str, away: str, stage: str | None = None):
        self.home_team = home
        self.away_team = away
        self.stage = stage


def test_exactly_one_fcc_prototype():
    p = fcc_fixed_params()
    assert p.name == PROTOTYPE_NAME
    assert p.pre_registered_single_prototype == "PRE_REGISTERED_SINGLE_PROTOTYPE"


def test_no_grid_no_tuning_labels():
    p = fcc_fixed_params()
    assert p.no_grid == "NO_GRID"
    assert p.no_tuning == "NO_TUNING"


def test_fcc_shadow_only_labels():
    p = fcc_fixed_params()
    assert p.status == SHADOW_ONLY_LABEL
    assert p.not_activation_candidate == NOT_ACTIVATION


def test_default_config_leaves_fcc_disabled():
    assert Priority1Config.baseline().favorite_confidence_curve_params is None
    assert config.STRENGTH_BASED_XG_ENABLED is False
    assert not source_uses_global_xg_avg()


def test_fcc_triggers_on_eligible_structural_favorite():
    params = fcc_fixed_params()
    m = _Match("Brazil", "Chile")
    gov_h, gov_a, diag = apply_favorite_confidence_curve(
        1.45, 0.85, match=m, params=params, dataset="qualifiers2026"
    )
    assert diag["trigger_eligible"] is True
    assert diag["curve_triggered"] is True
    assert gov_h > 1.45
    assert gov_a < 0.85


def test_fcc_does_not_use_actual_result():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    _, _, diag = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params)
    assert "no_actual_result_used" in diag["warnings"]


def test_fcc_does_not_use_dataset_as_trigger():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    _, _, d1 = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params, dataset="wc2018")
    _, _, d2 = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params, dataset="wc2022")
    assert d1["curve_triggered"] == d2["curve_triggered"]


def test_fcc_does_not_require_stage():
    params = fcc_fixed_params()
    m1 = _Match("A", "B", stage="group")
    m2 = _Match("A", "B", stage=None)
    _, _, d1 = apply_favorite_confidence_curve(1.5, 0.9, match=m1, params=params)
    _, _, d2 = apply_favorite_confidence_curve(1.5, 0.9, match=m2, params=params)
    assert d1["stage_required"] is False
    assert d1["curve_triggered"] == d2["curve_triggered"]


def test_fcc_preserves_total_xg():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    h, a, diag = apply_favorite_confidence_curve(1.6, 0.8, match=m, params=params)
    assert abs((h + a) - 2.4) <= params.total_xg_tolerance
    assert diag["total_xg_preserved"] is True


def test_fcc_increases_favorite_share_monotonically():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    _, _, diag = apply_favorite_confidence_curve(1.6, 0.8, match=m, params=params)
    assert diag["favorite_share_delta"] >= 0
    assert diag["xg_diff_delta"] >= 0


def test_fcc_does_not_auto_flip_favorite():
    params = fcc_fixed_params()
    m = _Match("Home", "Away")
    _, _, diag = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params)
    assert diag["favorite_direction_changed"] is False
    assert diag["no_auto_flip_applied"] is True


def test_fcc_respects_favorite_share_cap():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    h, a, diag = apply_favorite_confidence_curve(1.55, 0.85, match=m, params=params)
    share = max(h, a) / max(h + a, 1e-9)
    assert share <= params.governed_favorite_share_cap + 0.001
    assert diag["curve_triggered"] in (True, False)


def test_fcc_respects_per_team_movement_cap():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    h, a, diag = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params)
    assert abs(h - 1.5) <= 0.031
    assert abs(a - 0.9) <= 0.031


def test_fcc_respects_xg_diff_increase_cap():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    _, _, diag = apply_favorite_confidence_curve(1.5, 0.9, match=m, params=params)
    assert diag["xg_diff_delta"] <= 0.061


def test_fcc_blocked_when_ineligible():
    params = fcc_fixed_params()
    m = _Match("A", "B")
    _, _, diag = apply_favorite_confidence_curve(1.05, 1.0, match=m, params=params)
    assert diag["curve_triggered"] is False


def test_probability_mass_sanity_check():
    s = run_pre_prototype_sanity_checks(1.5, 0.9, home_team="A", away_team="B")
    assert s["probability_sum_valid"] is True


def test_scoreline_mass_sanity_check():
    s = run_pre_prototype_sanity_checks(1.5, 0.9, home_team="A", away_team="B")
    assert s["scoreline_mass_valid"] is True


def test_favorite_side_sanity_check():
    s = run_pre_prototype_sanity_checks(1.5, 0.9, home_team="A", away_team="B")
    assert s["favorite_side_consistent"] is True


def test_build_fcc_stack_with_strength_params():
    stack = build_fcc_stack(p1c2_shadow_params())
    assert stack.favorite_confidence_curve_params is not None
    assert stack.favorite_confidence_curve_params.name == PROTOTYPE_NAME


def test_baseline_priority1_config_still_has_shadow_disabled():
    assert Priority1Config.baseline().nr3_fcc_shadow_enabled is False
