"""Phase 2B — Effective Elo anchor + full-pipeline shadow tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.opponent_maher import build_opponent_index
from core.power_effective_elo import (
    WARNING_INTERNAL_WORLD_DIVERGENCE,
    WARNING_WORLD_ELO_MISSING,
    blend_weights_for_strategy,
    build_effective_elo_anchor_matchup,
    build_team_effective_elo_diagnostics,
    compute_effective_elo,
    run_full_shadow_pipeline,
)
from core.team_power import TeamPowerEvaluator
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

PYTHON = sys.executable


@pytest.fixture
def data_manager() -> LiveDataManager:
    return LiveDataManager()


@pytest.fixture
def opponent_index() -> dict:
    return build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))


def test_world_elo_missing_falls_back_to_internal(data_manager: LiveDataManager) -> None:
    key, _ = data_manager.resolve_team("Netherlands")
    internal = float(data_manager.get_team_data(key)["elo"])
    eff, meta = compute_effective_elo(key, "world_only", data_manager=data_manager)
    assert eff == pytest.approx(internal, abs=1.0)
    assert meta["world_available"] is False
    diag = build_team_effective_elo_diagnostics(key, data_manager=data_manager)
    assert WARNING_WORLD_ELO_MISSING in diag["warnings"]


def test_blended_static_weighted_value(data_manager: LiveDataManager) -> None:
    key, _ = data_manager.resolve_team("Portugal")
    internal = float(data_manager.get_team_data(key)["elo"])
    eff, meta = compute_effective_elo(key, "blended_static", data_manager=data_manager)
    expected = (
        config.EFFECTIVE_ELO_INTERNAL_WEIGHT_STATIC * internal
        + config.EFFECTIVE_ELO_WORLD_WEIGHT_STATIC * meta["world_elo"]
    )
    assert eff == pytest.approx(expected, abs=0.5)


def test_confidence_weighted_increases_world_for_low_confidence(
    data_manager: LiveDataManager,
) -> None:
    key, _ = data_manager.resolve_team("DR Congo")
    _, low = compute_effective_elo(
        key, "blended_confidence_weighted", data_manager=data_manager
    )
    _, high_meta = compute_effective_elo(
        key, "blended_static", data_manager=data_manager
    )
    wi, ww = blend_weights_for_strategy(
        "blended_confidence_weighted",
        internal_elo=high_meta["internal_elo"],
        world_elo=high_meta["world_elo"],
        rating_confidence=0.55,
        world_available=True,
    )
    assert ww >= config.EFFECTIVE_ELO_CONF_MID_WORLD
    assert low != high_meta["internal_elo"]


def test_disagreement_weighted_increases_world_for_large_delta(
    data_manager: LiveDataManager,
) -> None:
    key, _ = data_manager.resolve_team("Brazil")
    _, meta = compute_effective_elo(
        key, "blended_disagreement_weighted", data_manager=data_manager
    )
    if abs(meta["elo_delta"]) >= config.EFFECTIVE_ELO_DISAGREE_MID_DELTA:
        assert meta["world_weight"] >= config.EFFECTIVE_ELO_DISAGREE_LARGE_WORLD


def test_brazil_morocco_effective_elo_gap_larger_than_internal(
    data_manager: LiveDataManager,
) -> None:
    anchor = build_effective_elo_anchor_matchup(
        "Brazil",
        "Morocco",
        data_manager=data_manager,
    )
    gc = anchor["gap_comparison"]
    assert abs(gc["world_elo_gap"]) > abs(gc["internal_elo_gap"]) + 100
    assert abs(gc["effective_elo_gaps"]["world_only"]) > abs(gc["internal_elo_gap"]) + 100
    assert WARNING_INTERNAL_WORLD_DIVERGENCE in anchor["home"]["warnings"] or (
        WARNING_INTERNAL_WORLD_DIVERGENCE in anchor["away"]["warnings"]
    )


def test_portugal_dr_congo_remains_strong_favorite_under_effective_elo(
    data_manager: LiveDataManager,
    opponent_index: dict,
) -> None:
    from core.power_effective_elo import _BASELINE_SENTINEL

    home_key, _ = data_manager.resolve_team("Portugal")
    away_key, _ = data_manager.resolve_team("DR Congo")
    pred = run_full_shadow_pipeline(
        home_key,
        away_key,
        power_variant="effective_elo_adjusted_form",
        effective_elo_strategy="blended_disagreement_weighted",
        data_manager=data_manager,
        opponent_index=opponent_index,
        current_baseline=_BASELINE_SENTINEL,
    )
    assert pred.power_gap > 80
    assert pred.probabilities_1x2["home_win"] > 55


def test_argentina_france_reasonably_balanced(
    data_manager: LiveDataManager,
    opponent_index: dict,
) -> None:
    from core.power_effective_elo import _BASELINE_SENTINEL

    home_key, _ = data_manager.resolve_team("Argentina")
    away_key, _ = data_manager.resolve_team("France")
    pred = run_full_shadow_pipeline(
        home_key,
        away_key,
        power_variant="effective_elo_current_formula",
        effective_elo_strategy="blended_static",
        data_manager=data_manager,
        opponent_index=opponent_index,
        current_baseline=_BASELINE_SENTINEL,
    )
    assert abs(pred.power_gap) < 80
    assert 20 < pred.probabilities_1x2["home_win"] < 70


def test_full_pipeline_shadow_does_not_alter_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    payload = {
        "home_team": "Brazil",
        "away_team": "Morocco",
        "neutral_ground": True,
        "use_match_context": False,
    }
    client = TestClient(app)
    baseline = client.post("/api/predict", json=payload).json()
    with_shadow = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert with_shadow["probabilities_1x2"][key] == pytest.approx(
            baseline["probabilities_1x2"][key], abs=0.01
        )
    assert with_shadow["home_power"] == pytest.approx(baseline["home_power"], abs=0.01)


def test_api_includes_effective_elo_anchor() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Brazil",
            "away_team": "Morocco",
            "neutral_ground": True,
            "use_match_context": False,
        },
    )
    shadow = response.json()["global_rating_diagnostics"]["power_shadow_calibration"]
    anchor = shadow["effective_elo_anchor"]
    assert anchor is not None
    assert anchor["home"]["effective_elo_by_strategy"]
    assert len(anchor["shadow_predictions"]) <= config.POWER_SHADOW_API_TOP_VARIANTS


def test_audit_effective_elo_anchor_script_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_effective_elo_anchor.py", "--sample"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Brazil" in result.stdout


def test_current_candidate_still_matches_production(
    data_manager: LiveDataManager,
) -> None:
    pe = TeamPowerEvaluator(data_manager)
    key, _ = data_manager.resolve_team("Brazil")
    from core.power_shadow_calibration import calculate_candidate_power

    assert calculate_candidate_power(key, "current", data_manager=data_manager).total_power == pytest.approx(
        pe.calculate_composite_power(key), abs=0.02
    )


def test_full_pipeline_backtest_runs_one_variant() -> None:
    from core.power_effective_elo import run_full_pipeline_backtest

    row = run_full_pipeline_backtest("current", "internal_only")
    assert row.outcome_accuracy > 40
