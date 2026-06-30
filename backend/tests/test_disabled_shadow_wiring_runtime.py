"""Tests for P1.7B.23 disabled-by-default shadow wiring runtime."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from pathlib import Path

from core.disabled_shadow_wiring_runtime import (
    FLAG_NAME,
    attach_shadow_sidecar_if_enabled,
    build_nr3_fcc_shadow_priority1_config,
    build_shadow_artifact,
    create_disabled_shadow_result,
    extract_served_snapshot,
    should_run_nr3_fcc_shadow,
    verify_served_output_unchanged,
)
from core.priority1_options import Priority1Config


def _sample_result(**overrides) -> dict:
    base = {
        "probabilities_1x2": {"home_win": 0.50, "draw": 0.25, "away_win": 0.25},
        "expected_home_goals": 1.5,
        "expected_away_goals": 1.2,
        "top_scores": [{"score": "1-1", "prob": 0.11}, {"score": "1-0", "prob": 0.10}],
        "all_scores": {"1-1": 0.11, "1-0": 0.10, "0-1": 0.09},
    }
    base.update(overrides)
    return base


def test_default_flag_is_false():
    assert Priority1Config.baseline().nr3_fcc_shadow_enabled is False


def test_shadow_mode_disabled_by_default():
    assert should_run_nr3_fcc_shadow(Priority1Config.baseline()) is False


def test_should_run_false_by_default():
    cfg = Priority1Config()
    assert cfg.nr3_fcc_shadow_enabled is False
    assert should_run_nr3_fcc_shadow(cfg) is False


def test_disabled_shadow_result_fields():
    r = create_disabled_shadow_result()
    assert r.decision.shadow_enabled is False
    assert r.decision.shadow_executed is False
    assert r.artifact is not None
    assert r.artifact.activation_allowed is False


def test_activation_flags_false():
    r = create_disabled_shadow_result()
    assert r.decision.direct_activation_allowed is False
    assert r.decision.production_activation_allowed is False
    assert r.decision.served_output_change_allowed is False


def test_served_output_unchanged_when_disabled():
    before = extract_served_snapshot(_sample_result())
    result = _sample_result()
    attach_shadow_sidecar_if_enabled(
        result,
        match=None,
        prior=[],
        snapshot=None,
        dataset_key="wc2022",
        p1=Priority1Config.baseline(),
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda *a, **k: _sample_result(),
    )
    after = extract_served_snapshot(result)
    assert verify_served_output_unchanged(before, after)


def test_no_shadow_execution_when_disabled():
    calls = {"n": 0}

    def _run(**_):
        calls["n"] += 1
        return _sample_result()

    result = _sample_result()
    attach_shadow_sidecar_if_enabled(
        result,
        match=None,
        prior=[],
        snapshot=None,
        dataset_key="wc2022",
        p1=Priority1Config.baseline(),
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=_run,
    )
    assert calls["n"] == 0
    assert "_internal_diagnostics" not in result


def test_flag_true_keeps_activation_allowed_false_in_artifact():
    baseline = _sample_result()
    shadow = _sample_result(expected_home_goals=1.7, expected_away_goals=1.0)
    result = deepcopy(baseline)
    p1 = Priority1Config(nr3_fcc_shadow_enabled=True)
    attach_shadow_sidecar_if_enabled(
        result,
        match=object(),
        prior=[],
        snapshot=object(),
        dataset_key="wc2022",
        p1=p1,
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda *a, **k: shadow,
    )
    artifact = result["_internal_diagnostics"]["nr3_fcc_shadow"]
    assert artifact["activation_allowed"] is False


def test_flag_true_shadow_artifact_separate():
    baseline = _sample_result()
    shadow = _sample_result(expected_home_goals=1.8)
    result = deepcopy(baseline)
    p1 = Priority1Config(nr3_fcc_shadow_enabled=True)
    attach_shadow_sidecar_if_enabled(
        result,
        match=object(),
        prior=[],
        snapshot=object(),
        dataset_key="wc2022",
        p1=p1,
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda *a, **k: shadow,
    )
    assert result["expected_home_goals"] == 1.5
    assert result["_internal_diagnostics"]["nr3_fcc_shadow"]["shadow_executed"] is True


def test_baseline_remains_served_output():
    baseline = _sample_result()
    result = deepcopy(baseline)
    served_before = extract_served_snapshot(result)
    p1 = Priority1Config(nr3_fcc_shadow_enabled=True)
    attach_shadow_sidecar_if_enabled(
        result,
        match=object(),
        prior=[],
        snapshot=object(),
        dataset_key="wc2022",
        p1=p1,
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda *a, **k: _sample_result(expected_home_goals=2.0),
    )
    assert verify_served_output_unchanged(served_before, extract_served_snapshot(result))


def test_helper_does_not_mutate_baseline_probs():
    baseline = _sample_result()
    original_probs = deepcopy(baseline["probabilities_1x2"])
    result = deepcopy(baseline)
    p1 = Priority1Config(nr3_fcc_shadow_enabled=True)
    attach_shadow_sidecar_if_enabled(
        result,
        match=object(),
        prior=[],
        snapshot=object(),
        dataset_key="wc2022",
        p1=p1,
        candidate="baseline",
        elo_strategy="x",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda *a, **k: _sample_result(
            probabilities_1x2={"home_win": 0.1, "draw": 0.1, "away_win": 0.8}
        ),
    )
    assert result["probabilities_1x2"] == original_probs


def test_shadow_artifact_required_fields():
    artifact = build_shadow_artifact(
        baseline_result=_sample_result(),
        shadow_result=_sample_result(expected_home_goals=1.7),
        shadow_enabled=True,
        shadow_executed=True,
    ).to_dict()
    for key in (
        "shadow_enabled",
        "served_output_unchanged",
        "served_stack",
        "shadow_stack",
        "rollback_available",
        "activation_allowed",
    ):
        assert key in artifact
    assert artifact["activation_allowed"] is False


def test_missing_metrics_marked_unavailable():
    artifact = build_shadow_artifact(
        baseline_result={"probabilities_1x2": {"home_win": 0.4, "draw": 0.3, "away_win": 0.3}},
        shadow_result=None,
        shadow_enabled=True,
        shadow_executed=False,
    )
    assert "xg_baseline_from_result" in artifact.comparison.unavailable_fields


def test_shadow_config_disables_recursion():
    cfg = build_nr3_fcc_shadow_priority1_config(dataset_key="wc2022")
    assert cfg.nr3_fcc_shadow_enabled is False
    assert cfg.favorite_confidence_curve_params is not None


def test_no_config_import_in_runtime():
    src = Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py"
    text = src.read_text(encoding="utf-8")
    assert "import config" not in text
    assert "from config" not in text


def test_favorite_confidence_curve_default_none():
    assert Priority1Config.baseline().favorite_confidence_curve_params is None


def test_field_present_on_dataclass():
    names = {f.name for f in fields(Priority1Config)}
    assert "nr3_fcc_shadow_enabled" in names


def test_no_public_api_dependency_in_runtime():
    src = Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py"
    text = src.read_text(encoding="utf-8")
    assert "api.main" not in text
    assert "api.schemas" not in text


def test_no_market_odds_in_runtime():
    src = Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py"
    assert "market_odds" not in src.read_text(encoding="utf-8").lower()


def test_flag_true_still_not_activation():
    artifact = build_shadow_artifact(
        baseline_result=_sample_result(),
        shadow_result=_sample_result(),
        shadow_enabled=True,
        shadow_executed=True,
    )
    assert artifact.activation_allowed is False


def test_served_output_change_allowed_false_on_decision():
    r = create_disabled_shadow_result()
    assert r.decision.served_output_change_allowed is False
