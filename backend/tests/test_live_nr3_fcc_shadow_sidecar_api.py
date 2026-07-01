"""Tests for live NR3+FCC production shadow sidecar (log-only; served output unchanged)."""

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
from core.live_nr3_fcc_shadow_runner import (
    SHADOW_SCORELINE_WARNING,
    run_live_nr3_fcc_shadow_sidecar,
)

client = TestClient(app)

SERVED_KEYS = (
    "home_xg",
    "away_xg",
    "probabilities_1x2",
    "scoreline_decision",
    "top_scores",
)

PREDICT_PAYLOAD = {"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True}


def _predict(payload: dict) -> dict:
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _served_snapshot(data: dict) -> dict:
    return {
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "probabilities_1x2": dict(data["probabilities_1x2"]),
        "scoreline_decision": dict(data["scoreline_decision"]),
        "top_scores": [
            {"score": s["score"], "probability": s["probability"]} for s in data["top_scores"]
        ],
    }


def _combined_log_output(caplog, capsys) -> str:
    captured = capsys.readouterr()
    return caplog.text + captured.out + captured.err


def test_flag_false_no_observability_markers(monkeypatch, caplog, capsys):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    baseline = _served_snapshot(_predict(PREDICT_PAYLOAD))
    repeat = _served_snapshot(_predict(PREDICT_PAYLOAD))
    assert baseline == repeat
    output = _combined_log_output(caplog, capsys)
    assert "nr3_fcc_shadow_flag_seen" not in output
    assert "nr3_fcc_shadow_sidecar" not in output
    assert "nr3_fcc_shadow_sidecar_failed" not in output


def test_flag_true_emits_observability_markers(monkeypatch, caplog, capsys):
    caplog.set_level(logging.WARNING)
    fake_diag = {
        "shadow_executed": True,
        "activation_allowed": False,
        "home_advantage_applied": 0.0,
        "warnings": [SHADOW_SCORELINE_WARNING],
        "delta_vs_baseline": {"home_xg_delta": 0.1, "away_xg_delta": -0.05},
    }
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        return_value=fake_diag,
    ):
        baseline = _served_snapshot(_predict(PREDICT_PAYLOAD))
    output = _combined_log_output(caplog, capsys)
    assert "nr3_fcc_shadow_flag_seen" in output
    assert "nr3_fcc_shadow_sidecar" in output
    assert "nr3_fcc_shadow_sidecar_failed" not in output
    assert baseline["home_xg"] != 9.99


def test_sidecar_failure_emits_failed_marker(monkeypatch, caplog, capsys):
    caplog.set_level(logging.WARNING)
    payload = {"home_team": "France", "away_team": "Sweden", "neutral_ground": True}
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    baseline = _served_snapshot(_predict(payload))

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=RuntimeError("shadow boom"),
    ):
        data = _predict(payload)

    assert _served_snapshot(data) == baseline
    output = _combined_log_output(caplog, capsys)
    assert "nr3_fcc_shadow_flag_seen" in output
    assert "nr3_fcc_shadow_sidecar_failed" in output
    assert "nr3_fcc_shadow" not in data


def test_startup_import_with_shadow_flag_true(monkeypatch):
    monkeypatch.setenv("NR3_FCC_SHADOW_ENABLED", "true")
    importlib.reload(config)
    assert config.nr3_fcc_shadow_enabled() is True
    import api.main as main_module

    importlib.reload(main_module)
    assert main_module.app is not None


def test_nr3_fcc_shadow_flag_default_false(monkeypatch):
    monkeypatch.delenv("NR3_FCC_SHADOW_ENABLED", raising=False)
    import importlib

    importlib.reload(config)
    assert config.NR3_FCC_SHADOW_ENABLED is False
    assert config.nr3_fcc_shadow_enabled() is False


def test_predict_response_unchanged_when_shadow_flag_false(monkeypatch):
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    payload = {"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True}
    first = _served_snapshot(_predict(payload))
    second = _served_snapshot(_predict(payload))
    assert first == second


def test_shadow_flag_true_served_fields_unchanged(monkeypatch):
    payload = {"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True}

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    baseline = _served_snapshot(_predict(payload))

    fake_diag = {
        "shadow_executed": True,
        "activation_allowed": False,
        "model": "nr3_fcc_shadow",
        "shadow_home_xg": 9.99,
        "shadow_away_xg": 0.01,
        "warnings": [SHADOW_SCORELINE_WARNING],
    }

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        return_value=fake_diag,
    ):
        after = _served_snapshot(_predict(payload))

    assert baseline == after
    assert after["home_xg"] != 9.99
    assert after["away_xg"] != 0.01


def test_shadow_error_isolated(monkeypatch):
    payload = {"home_team": "France", "away_team": "Sweden", "neutral_ground": True}

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    baseline = _served_snapshot(_predict(payload))

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=RuntimeError("shadow boom"),
    ):
        data = _predict(payload)

    assert _served_snapshot(data) == baseline
    assert "nr3_fcc_shadow" not in data


def test_shadow_runner_receives_home_advantage(monkeypatch):
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {
            "shadow_executed": True,
            "activation_allowed": False,
            "home_advantage_applied": kwargs.get("home_advantage", 0.0),
            "warnings": [SHADOW_SCORELINE_WARNING],
        }

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=_capture,
    ):
        _predict({"home_team": "Mexico", "away_team": "Ecuador", "neutral_ground": False})

    assert captured.get("neutral_ground") is False
    assert float(captured.get("home_advantage", 0.0)) != 0.0


def test_shadow_runner_neutral_advantage_zero(monkeypatch):
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {
            "shadow_executed": True,
            "activation_allowed": False,
            "home_advantage_applied": 0.0,
            "warnings": [SHADOW_SCORELINE_WARNING],
        }

    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=_capture,
    ):
        _predict({"home_team": "France", "away_team": "Sweden", "neutral_ground": True})

    assert captured.get("neutral_ground") is True

    diag = run_live_nr3_fcc_shadow_sidecar(
        home_team="France",
        away_team="Sweden",
        neutral_ground=True,
        home_power=900.0,
        away_power=880.0,
        home_elo=2000.0,
        away_elo=1980.0,
        baseline_home_xg=1.4,
        baseline_away_xg=1.2,
        baseline_probabilities_1x2={"home_win": 45.0, "draw": 25.0, "away_win": 30.0},
        baseline_top_scores=[],
        home_advantage=35.0,
    )
    assert diag["home_advantage_applied"] == 0.0


def test_no_public_schema_break():
    payload = {"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True}
    data = _predict(payload)
    parsed = PredictResponse.model_validate(data)
    assert parsed.home_xg == data["home_xg"]
    assert parsed.scoreline_decision is not None
    assert not hasattr(parsed, "nr3_fcc_shadow_diagnostics")


def test_shadow_runner_emits_scoreline_warning():
    diag = run_live_nr3_fcc_shadow_sidecar(
        home_team="Brazil",
        away_team="Chile",
        neutral_ground=False,
        home_power=920.0,
        away_power=850.0,
        home_elo=2100.0,
        away_elo=2000.0,
        baseline_home_xg=1.5,
        baseline_away_xg=1.0,
        baseline_probabilities_1x2={"home_win": 55.0, "draw": 22.0, "away_win": 23.0},
        baseline_top_scores=[{"score": "1-0", "probability": 12.0}],
        home_advantage=35.0,
    )
    assert diag["shadow_executed"] is True
    assert diag["activation_allowed"] is False
    assert SHADOW_SCORELINE_WARNING in diag["warnings"]
