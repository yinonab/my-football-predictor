"""Tests for NR3+FCC controlled served activation (default off)."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from api.schemas import PredictResponse
from core.live_nr3_fcc_shadow_runner import NR3_FCC_SERVED_MODEL_VERSION

client = TestClient(app)


@pytest.fixture(autouse=True)
def _default_nr3_shadow_off(monkeypatch):
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: False)


FRANCE_SWEDEN = {
    "home_team": "France",
    "away_team": "Sweden",
    "neutral_ground": True,
    "include_diagnostics": True,
}


@pytest.fixture
def production_model_activation(monkeypatch):
    """Match Render production v2.2.0-fifa-points-anchor baseline."""
    monkeypatch.setattr(config, "MODEL_ACTIVATION_ENABLED", True)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True)


def _predict(payload: dict) -> dict:
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _disable_served(monkeypatch) -> None:
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: False)


def _disable_shadow(monkeypatch) -> None:
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)


def _enable_served(monkeypatch) -> None:
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: True)


def _combined_log_output(caplog, capsys) -> str:
    captured = capsys.readouterr()
    return caplog.text + captured.out + captured.err


def test_served_flag_false_france_sweden_baseline_parity(monkeypatch, production_model_activation):
    _disable_served(monkeypatch)
    _disable_shadow(monkeypatch)
    data = _predict(FRANCE_SWEDEN)
    assert data["home_xg"] == 2.85
    assert data["away_xg"] == 0.77
    assert data["probabilities_1x2"]["home_win"] == 74.0
    assert data["probabilities_1x2"]["draw"] == 15.9
    assert data["probabilities_1x2"]["away_win"] == 10.1
    assert data["model_diagnostics"]["model_version"] == "v2.2.0-fifa-points-anchor"
    assert data["scoreline_decision"]["favorite_outcome"] == "home_win"
    assert data["scoreline_decision"]["favorite_outcome_probability"] == 74.0


def test_served_flag_true_uses_nr3_fcc_output(monkeypatch, production_model_activation):
    _disable_shadow(monkeypatch)
    _disable_served(monkeypatch)
    baseline = _predict(FRANCE_SWEDEN)

    _enable_served(monkeypatch)
    served = _predict(FRANCE_SWEDEN)

    PredictResponse.model_validate(served)
    assert served["model_diagnostics"]["model_version"] == NR3_FCC_SERVED_MODEL_VERSION
    assert served["home_xg"] < baseline["home_xg"]
    assert served["home_xg"] != baseline["home_xg"]
    assert served["probabilities_1x2"] != baseline["probabilities_1x2"]


def test_served_failure_falls_back_to_baseline(monkeypatch, caplog, capsys, production_model_activation):
    caplog.set_level(logging.WARNING)
    _disable_shadow(monkeypatch)
    _disable_served(monkeypatch)
    baseline = _predict(FRANCE_SWEDEN)

    _enable_served(monkeypatch)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=RuntimeError("served boom"),
    ):
        data = _predict(FRANCE_SWEDEN)

    assert data["home_xg"] == baseline["home_xg"]
    assert data["away_xg"] == baseline["away_xg"]
    assert data["probabilities_1x2"] == baseline["probabilities_1x2"]
    assert data["model_diagnostics"]["model_version"] == baseline["model_diagnostics"]["model_version"]
    output = _combined_log_output(caplog, capsys)
    assert "nr3_fcc_served_failed_fallback" in output


def test_shadow_alone_does_not_activate_served(monkeypatch, production_model_activation):
    _disable_served(monkeypatch)
    _disable_shadow(monkeypatch)
    baseline = _predict(FRANCE_SWEDEN)

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        return_value={
            "shadow_executed": True,
            "activation_allowed": False,
            "shadow_home_xg": 9.99,
            "shadow_away_xg": 0.01,
            "shadow_probabilities_1x2": {"home_win": 99.0, "draw": 0.5, "away_win": 0.5},
            "shadow_top_scores": [{"score": "9-0", "probability": 50.0}],
            "warnings": [],
            "delta_vs_baseline": {},
        },
    ):
        shadow_only = _predict(FRANCE_SWEDEN)

    assert shadow_only["home_xg"] == baseline["home_xg"]
    assert shadow_only["away_xg"] == baseline["away_xg"]
    assert shadow_only["probabilities_1x2"] == baseline["probabilities_1x2"]
    assert shadow_only["model_diagnostics"]["model_version"] == baseline["model_diagnostics"]["model_version"]


def test_served_true_without_shadow_flag(monkeypatch, production_model_activation):
    _disable_shadow(monkeypatch)
    _enable_served(monkeypatch)
    data = _predict(FRANCE_SWEDEN)
    assert data["model_diagnostics"]["model_version"] == NR3_FCC_SERVED_MODEL_VERSION


def test_startup_import_with_served_flag_true(monkeypatch):
    monkeypatch.setenv("NR3_FCC_SERVED_ENABLED", "true")
    importlib.reload(config)
    assert config.nr3_fcc_served_enabled() is True
    import api.main as main_module

    importlib.reload(main_module)
    assert main_module.app is not None
