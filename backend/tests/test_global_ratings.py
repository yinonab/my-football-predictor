"""Tests for Global Rating Stack diagnostics (Phase 1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.global_ratings import (
    WARNING_FORM_INFLATED,
    WARNING_LOW_CONFIDENCE,
    WARNING_MISSING_EXTERNAL,
    WARNING_POWER_COMPRESSED,
    build_match_diagnostics,
    build_team_diagnostics,
    compute_global_strength_score,
    lookup_external_record,
    opponent_quality_factor,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


@pytest.fixture
def data_manager() -> LiveDataManager:
    return LiveDataManager()


@pytest.fixture
def power_eval(data_manager: LiveDataManager) -> TeamPowerEvaluator:
    return TeamPowerEvaluator(data_manager)


def _match_diag(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
    home_input: str,
    away_input: str,
):
    home_key, home_data = data_manager.resolve_team(home_input)
    away_key, away_data = data_manager.resolve_team(away_input)
    return build_match_diagnostics(
        home_key,
        away_key,
        home_power=power_eval.calculate_composite_power(home_key),
        away_power=power_eval.calculate_composite_power(away_key),
        home_internal_elo=float(home_data["elo"]),
        away_internal_elo=float(away_data["elo"]),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
    )


def test_missing_external_rating_falls_back_to_internal_elo(
    data_manager: LiveDataManager,
) -> None:
    key, data = data_manager.resolve_team("Netherlands")
    diag = build_team_diagnostics(
        key,
        internal_elo=float(data["elo"]),
        raw_form=float(data.get("form", 0.5)),
    )
    assert diag.world_elo == pytest.approx(diag.internal_elo)
    assert diag.external_source == "internal_fallback"
    assert lookup_external_record(key).source == "missing"


def test_opponent_quality_factor_bands() -> None:
    assert opponent_quality_factor(1750) == 1.0
    assert opponent_quality_factor(1650) == 0.85
    assert opponent_quality_factor(1550) == 0.70
    assert opponent_quality_factor(1450) == 0.55
    assert opponent_quality_factor(1300) == 0.40


def test_fifa_weight_redistributed_when_missing() -> None:
    with_fifa = compute_global_strength_score(
        world_elo=2000,
        internal_elo=1900,
        opponent_adjusted_form=0.6,
        fifa_points=1700,
        fifa_rank=None,
    )
    without_fifa = compute_global_strength_score(
        world_elo=2000,
        internal_elo=1900,
        opponent_adjusted_form=0.6,
        fifa_points=None,
        fifa_rank=None,
    )
    assert with_fifa != without_fifa
    assert 0.0 < without_fifa < 1.0


def test_portugal_dr_congo_gaps_and_warnings(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Portugal (פורטוגל)",
        "DR Congo (קונגו)",
    )
    assert diag.gaps.internal_elo_gap > 250
    assert diag.gaps.world_elo_gap > 300
    assert abs(diag.gaps.power_gap) < abs(diag.gaps.internal_elo_gap) * 0.55
    assert WARNING_POWER_COMPRESSED in diag.warnings
    assert diag.home.world_elo == pytest.approx(1989)
    assert diag.away.world_elo == pytest.approx(1652)


def test_portugal_dr_congo_predictions_unchanged_with_diagnostics_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    payload = {
        "home_team": "Portugal (פורטוגל)",
        "away_team": "DR Congo (קונגו)",
        "neutral_ground": True,
    }
    client = TestClient(app)

    monkeypatch.setattr(config, "GLOBAL_RATINGS_ENABLED", False)
    baseline = client.post("/api/predict", json=payload).json()

    monkeypatch.setattr(config, "GLOBAL_RATINGS_ENABLED", True)
    monkeypatch.setattr(config, "GLOBAL_RATINGS_AFFECT_PREDICTION", False)
    with_diag = client.post("/api/predict", json=payload).json()

    for key in ("home_win", "draw", "away_win"):
        assert with_diag["probabilities_1x2"][key] == pytest.approx(
            baseline["probabilities_1x2"][key], abs=0.01
        )
    assert with_diag["top_scores"][0]["score"] == baseline["top_scores"][0]["score"]
    assert with_diag["global_rating_diagnostics"] is not None
    assert with_diag["global_rating_diagnostics"]["warnings"]


def test_spain_cape_verde_large_global_gap_low_underdog_confidence(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Spain (ספרד)",
        "Cape Verde (כף ורד)",
    )
    assert abs(diag.gaps.world_elo_gap) > 600
    assert abs(diag.gaps.global_strength_gap) > 0.15
    assert diag.away.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD
    assert WARNING_LOW_CONFIDENCE in diag.warnings
    # Low confidence must not inflate away composite power vs raw components
    away_power = power_eval.calculate_composite_power(
        data_manager.resolve_team("Cape Verde")[0]
    )
    assert away_power < diag.home.world_elo * config.WEIGHT_ELO


def test_argentina_france_balanced_no_false_compression(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Argentina (ארגנטינה)",
        "France (צרפת)",
    )
    assert abs(diag.gaps.internal_elo_gap) < 80
    assert abs(diag.gaps.world_elo_gap) < 80
    assert abs(diag.gaps.global_strength_gap) < 0.08
    assert WARNING_POWER_COMPRESSED not in diag.warnings


def test_debug_global_ratings_endpoint() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.get(
        "/api/debug/global-ratings",
        params={"home_team": "Portugal (פורטוגל)", "away_team": "DR Congo (קונגו)"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["home_team"].startswith("Portugal")
    assert "global_rating_diagnostics" in body
    assert body["global_rating_diagnostics"]["gaps"]["world_elo_gap"] > 300


def test_form_inflation_warning_when_qualifier_form_high(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Portugal (פורטוגל)",
        "DR Congo (קונגו)",
    )
    if diag.away.raw_form >= config.FORM_INFLATED_RAW_MIN:
        if (
            diag.away.opponent_adjusted_form
            < diag.away.raw_form * config.FORM_INFLATED_ADJ_RATIO
        ):
            assert WARNING_FORM_INFLATED in diag.warnings


def test_netherlands_triggers_missing_external_warning(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Netherlands (הולנד)",
        "Japan (יפן)",
    )
    assert WARNING_MISSING_EXTERNAL in diag.warnings
