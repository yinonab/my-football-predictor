"""Phase 3A — Controlled activation wiring tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.active_model_activation import (
    GOLDEN_PARITY_MATCHUPS,
    build_model_diagnostics,
    model_activation_should_apply,
    run_prediction_with_active_candidate,
    try_apply_active_candidate_powers,
    validate_activation_configuration,
)
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

PYTHON = sys.executable
PAYLOAD = {"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True}


def _client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


def _predict_payload(home: str, away: str) -> dict:
    return {"home_team": home, "away_team": away, "neutral_ground": True}


@pytest.fixture
def golden_baseline_responses() -> dict[str, dict]:
    client = _client()
    out: dict[str, dict] = {}
    for home, away in GOLDEN_PARITY_MATCHUPS:
        key = f"{home}|{away}"
        r = client.post("/api/predict", json=_predict_payload(home, away))
        assert r.status_code == 200
        out[key] = r.json()
    return out


def test_production_defaults_disabled() -> None:
    assert config.MODEL_ACTIVATION_ENABLED is False
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False
    assert model_activation_should_apply() is False


def test_disabled_state_parity(golden_baseline_responses: dict[str, dict]) -> None:
    client = _client()
    for home, away in GOLDEN_PARITY_MATCHUPS:
        key = f"{home}|{away}"
        baseline = golden_baseline_responses[key]
        r = client.post("/api/predict", json=_predict_payload(home, away))
        assert r.status_code == 200
        body = r.json()
        assert body["probabilities_1x2"] == baseline["probabilities_1x2"]
        assert body["home_xg"] == baseline["home_xg"]
        assert body["away_xg"] == baseline["away_xg"]
        assert [s["score"] for s in body["top_scores"]] == [
            s["score"] for s in baseline["top_scores"]
        ]
        md = body.get("model_diagnostics") or {}
        assert md.get("model_version") == config.BASELINE_MODEL_VERSION
        assert md.get("activation_enabled") is False
        assert md.get("active_candidate") is None
        assert md.get("fallback_to_baseline") is False


def test_enabled_state_model_version_and_candidate() -> None:
    client = _client()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        r = client.post("/api/predict", json=PAYLOAD)
    assert r.status_code == 200
    md = r.json()["model_diagnostics"]
    assert md["model_version"] == config.ACTIVE_MODEL_VERSION
    assert md["active_candidate"] == config.ACTIVE_POWER_CANDIDATE
    assert md["active_external_rating_strategy"] == config.ACTIVE_EXTERNAL_RATING_STRATEGY
    assert md["activation_enabled"] is True


def test_enabled_brazil_morocco_applies_without_fallback() -> None:
    client = _client()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        active = client.post("/api/predict", json=PAYLOAD).json()
    md = active["model_diagnostics"]
    assert md["activation_enabled"] is True
    assert md["fallback_to_baseline"] is False
    assert md["model_version"] == config.ACTIVE_MODEL_VERSION


def test_enabled_argentina_france_stable() -> None:
    client = _client()
    payload = _predict_payload("Argentina", "France")
    base = client.post("/api/predict", json=payload).json()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        active = client.post("/api/predict", json=payload).json()
    delta = abs(
        active["probabilities_1x2"]["home_win"]
        - base["probabilities_1x2"]["home_win"]
    )
    assert delta <= config.BALANCED_MATCH_MAX_SHIFT_PP


def test_missing_fifa_points_fallback() -> None:
    dm = LiveDataManager()
    home_key, _ = dm.resolve_team("Brazil")
    away_key, _ = dm.resolve_team("Morocco")
    with patch(
        "core.active_model_activation.resolve_fifa_snapshot_dataset",
        return_value=(None, ["fifa_points_missing"]),
    ):
        result = try_apply_active_candidate_powers(
            home_key,
            away_key,
            baseline_home_power=100.0,
            baseline_away_power=90.0,
            baseline_home_elo=1500.0,
            baseline_away_elo=1480.0,
            data_manager=dm,
            force_enable=True,
        )
    assert result.applied is False
    assert result.home_power == 100.0
    assert "fifa_points_missing" in result.fallback_reasons[0]


def test_invalid_strategy_fallback() -> None:
    client = _client()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
        patch.object(config, "ACTIVE_EXTERNAL_RATING_STRATEGY", "not_a_real_strategy"),
    ):
        r = client.post("/api/predict", json=PAYLOAD)
    assert r.status_code == 200
    md = r.json()["model_diagnostics"]
    assert md["fallback_to_baseline"] is True
    assert md["activation_enabled"] is False
    assert any("invalid" in reason.lower() for reason in md["fallback_reasons"])


def test_validate_activation_configuration_disabled() -> None:
    ok, reasons = validate_activation_configuration()
    assert ok is False
    assert any("MODEL_ACTIVATION_ENABLED" in r for r in reasons)


def test_enabled_top_scores_consistent_with_probs() -> None:
    client = _client()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        body = client.post("/api/predict", json=PAYLOAD).json()
    probs = body["probabilities_1x2"]
    assert abs(probs["home_win"] + probs["draw"] + probs["away_win"] - 100.0) < 0.2
    assert len(body["top_scores"]) >= 1
    assert body["top_scores"][0]["probability"] > 0


def test_activation_dry_run_cli_disabled() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/activation_dry_run.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "Brazil" in proc.stdout
    assert "disabled" in proc.stdout.lower()


def test_activation_dry_run_cli_enabled() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/activation_dry_run.py", "--enable-candidate"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert config.ACTIVE_MODEL_VERSION in proc.stdout or "+6" in proc.stdout


def test_build_model_diagnostics_shape() -> None:
    diag = build_model_diagnostics(activation_applied=False)
    data = diag.to_dict()
    assert data["baseline_model_version"] == config.BASELINE_MODEL_VERSION
    assert data["candidate_gate_status"] == "MODEL_ACTIVATION_PASS"


def test_run_prediction_with_active_candidate_isolated() -> None:
    dm = LiveDataManager()
    opp = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    home_key, _ = dm.resolve_team("Brazil")
    away_key, _ = dm.resolve_team("Morocco")
    out = run_prediction_with_active_candidate(
        home_key,
        away_key,
        data_manager=dm,
        opponent_index=opp,
        force_enable=True,
    )
    assert "baseline" in out and "active" in out
    assert out["activation_applied"] is True
    assert out["fallback_reasons"] == []
