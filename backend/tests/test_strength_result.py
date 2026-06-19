"""Tests for Phase 4C StrengthResult layer."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from core.active_model_activation import (
    ActivePowerResult,
    build_model_diagnostics,
)
from core.match_features import build_match_features
from core.release_readiness import MODEL_DIAGNOSTICS_CONTRACT_FIELDS
from core.strength_result import StrengthResult, build_strength_result
from data.database import LiveDataManager
from fastapi.testclient import TestClient

client = TestClient(app)

PARITY_MATCHUPS = [
    ("Brazil", "Morocco"),
    ("Germany", "Haiti"),
    ("Argentina", "France"),
    ("Portugal", "DR Congo"),
]


@pytest.fixture
def data_manager() -> LiveDataManager:
    return LiveDataManager()


def _strength_from_values(
    data_manager: LiveDataManager,
    *,
    home: str,
    away: str,
    baseline_home: float,
    baseline_away: float,
    active_home: float,
    active_away: float,
    final_home: float,
    final_away: float,
    applied: bool,
    fallback_reasons: list[str] | None = None,
    force_active: bool = False,
) -> StrengthResult:
    features = build_match_features(
        home_team=home,
        away_team=away,
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    active = ActivePowerResult(
        applied=applied,
        home_power=active_home,
        away_power=active_away,
        home_elo=features.home_internal_elo,
        away_elo=features.away_internal_elo,
        fallback_reasons=list(fallback_reasons or []),
    )
    diag = build_model_diagnostics(
        activation_applied=applied,
        fallback_reasons=fallback_reasons,
        force_active=force_active,
    )
    return build_strength_result(
        match_features=features,
        baseline_home_power=baseline_home,
        baseline_away_power=baseline_away,
        active_power=active,
        model_diag=diag,
        final_home_power=final_home,
        final_away_power=final_away,
    )


def test_strength_activation_disabled(data_manager: LiveDataManager) -> None:
    with patch("config.MODEL_ACTIVATION_ENABLED", False), patch(
        "config.POWER_CANDIDATE_AFFECTS_PREDICTION", False
    ):
        strength = _strength_from_values(
            data_manager,
            home="Brazil",
            away="Morocco",
            baseline_home=1200.0,
            baseline_away=1100.0,
            active_home=1200.0,
            active_away=1100.0,
            final_home=1200.0,
            final_away=1100.0,
            applied=False,
        )
    assert strength.final_home_power == strength.baseline_home_power
    assert strength.final_away_power == strength.baseline_away_power
    assert strength.uses_active_candidate is False
    assert strength.model_version == config.BASELINE_MODEL_VERSION
    assert strength.gap_delta == 0.0


def test_strength_activation_enabled_no_fallback(data_manager: LiveDataManager) -> None:
    with patch("config.MODEL_ACTIVATION_ENABLED", True), patch(
        "config.POWER_CANDIDATE_AFFECTS_PREDICTION", True
    ):
        strength = _strength_from_values(
            data_manager,
            home="Germany",
            away="Haiti",
            baseline_home=1000.0,
            baseline_away=900.0,
            active_home=1150.0,
            active_away=850.0,
            final_home=1150.0,
            final_away=850.0,
            applied=True,
            force_active=True,
        )
    assert strength.final_home_power == strength.active_home_power
    assert strength.final_away_power == strength.active_away_power
    assert strength.uses_active_candidate is True
    assert strength.model_version == config.ACTIVE_MODEL_VERSION
    assert strength.power_delta_home == 150.0
    assert strength.gap_delta == pytest.approx(200.0)


def test_strength_fallback_uses_baseline(data_manager: LiveDataManager) -> None:
    with patch("config.MODEL_ACTIVATION_ENABLED", True), patch(
        "config.POWER_CANDIDATE_AFFECTS_PREDICTION", True
    ):
        strength = _strength_from_values(
            data_manager,
            home="Spain",
            away="Cape Verde",
            baseline_home=1050.0,
            baseline_away=950.0,
            active_home=1050.0,
            active_away=950.0,
            final_home=1050.0,
            final_away=950.0,
            applied=False,
            fallback_reasons=["MODEL_ACTIVATION_ENABLED=false"],
            force_active=True,
        )
    assert strength.fallback_to_baseline is True
    assert strength.final_home_power == strength.baseline_home_power
    assert strength.uses_active_candidate is False
    assert strength.fallback_reasons


def test_to_model_diagnostics_dict_contract(data_manager: LiveDataManager) -> None:
    strength = _strength_from_values(
        data_manager,
        home="Argentina",
        away="France",
        baseline_home=1000.0,
        baseline_away=1000.0,
        active_home=1000.0,
        active_away=1000.0,
        final_home=1000.0,
        final_away=1000.0,
        applied=False,
    )
    diag = strength.to_model_diagnostics_dict()
    for field in MODEL_DIAGNOSTICS_CONTRACT_FIELDS:
        assert field in diag
    assert diag["baseline_home_power"] == 1000.0
    assert diag["final_home_power"] == 1000.0
    assert diag["gap_delta"] == 0.0


def test_enrich_breakdown_active_note(data_manager: LiveDataManager) -> None:
    with patch("config.MODEL_ACTIVATION_ENABLED", True), patch(
        "config.POWER_CANDIDATE_AFFECTS_PREDICTION", True
    ):
        strength = _strength_from_values(
            data_manager,
            home="Germany",
            away="Haiti",
            baseline_home=1000.0,
            baseline_away=900.0,
            active_home=1150.0,
            active_away=850.0,
            final_home=1150.0,
            final_away=850.0,
            applied=True,
            force_active=True,
        )
    text = strength.enrich_breakdown_text("home", "התקפה: 0.5")
    assert "מועמד פעיל" in text
    assert "1150" in text


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_numeric_parity(home: str, away: str) -> None:
    payload = {"home_team": home, "away_team": away, "neutral_ground": True}
    first = client.post("/api/predict", json=payload).json()
    second = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert first["probabilities_1x2"][key] == second["probabilities_1x2"][key]
    assert first["home_xg"] == second["home_xg"]
    assert first["away_xg"] == second["away_xg"]
    assert first["home_power"] == second["home_power"]
    assert first["away_power"] == second["away_power"]
    for i, score in enumerate(first["top_scores"]):
        assert score["score"] == second["top_scores"][i]["score"]
        assert score["probability"] == second["top_scores"][i]["probability"]


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_model_diagnostics_power_fields(home: str, away: str) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": home, "away_team": away, "neutral_ground": True},
    ).json()
    md = data["model_diagnostics"]
    for field in MODEL_DIAGNOSTICS_CONTRACT_FIELDS:
        assert field in md
    assert md["final_home_power"] == data["home_power"]
    assert md["final_away_power"] == data["away_power"]
    assert md["baseline_home_power"] is not None
    assert md["gap_delta"] is not None


def test_breakdown_power_score_matches_final_power() -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    assert data["home_breakdown"]["power_score"] == data["home_power"]
    assert data["away_breakdown"]["power_score"] == data["away_power"]
