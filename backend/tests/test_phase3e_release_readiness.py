"""Phase 3E — Local/staging enablement smoke and release readiness tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.release_readiness import (
    MODEL_DIAGNOSTICS_CONTRACT_FIELDS,
    RELEASE_READY_FOR_STAGING,
    _client,
    _predict_payload,
    production_defaults_disabled,
    run_activation_rollback_smoke,
    run_local_activation_enabled_smoke,
)
from scripts.release_readiness_report import build_release_report

PYTHON = sys.executable


@pytest.fixture(autouse=True)
def _reset_activation_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MODEL_ACTIVATION_ENABLED", False)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", False)


def test_production_defaults_remain_disabled() -> None:
    ok, issues = production_defaults_disabled()
    assert ok is True
    assert issues == []
    assert config.MODEL_ACTIVATION_ENABLED is False
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False


def test_model_diagnostics_contract_disabled() -> None:
    client = _client()
    response = client.post(
        "/api/predict",
        json=_predict_payload("Brazil", "Morocco"),
    )
    assert response.status_code == 200
    md = response.json()["model_diagnostics"]
    for field in MODEL_DIAGNOSTICS_CONTRACT_FIELDS:
        assert field in md
    assert md["model_version"] == config.BASELINE_MODEL_VERSION
    assert md["activation_enabled"] is False
    assert md["active_candidate"] is None
    assert md["fallback_to_baseline"] is False
    assert isinstance(md["fallback_reasons"], list)


def test_model_diagnostics_contract_enabled_simulated() -> None:
    client = _client()
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        response = client.post(
            "/api/predict",
            json=_predict_payload("Portugal", "DR Congo"),
        )
    assert response.status_code == 200
    body = response.json()
    md = body["model_diagnostics"]
    for field in MODEL_DIAGNOSTICS_CONTRACT_FIELDS:
        assert field in md
    assert md["model_version"] == config.ACTIVE_MODEL_VERSION
    assert md["baseline_model_version"] == config.BASELINE_MODEL_VERSION
    assert md["activation_enabled"] is True
    assert md["active_candidate"] == config.ACTIVE_POWER_CANDIDATE
    assert md["active_external_rating_mode"] == config.ACTIVE_EXTERNAL_RATING_MODE
    assert md["active_external_rating_strategy"] == config.ACTIVE_EXTERNAL_RATING_STRATEGY
    assert md["fallback_to_baseline"] is False
    assert md["candidate_gate_status"] == "MODEL_ACTIVATION_PASS"


def test_local_activation_enabled_smoke_no_fallback() -> None:
    result = run_local_activation_enabled_smoke()
    assert result.passed is True
    assert result.details["matchups_checked"] == 8
    assert result.errors == []


def test_activation_rollback_smoke_returns_baseline() -> None:
    result = run_activation_rollback_smoke()
    assert result.passed is True
    assert result.details["enabled_model_version"] == config.ACTIVE_MODEL_VERSION
    assert result.details["disabled_model_version"] == config.BASELINE_MODEL_VERSION


def test_smoke_local_activation_enabled_cli_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/smoke_local_activation_enabled.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "PASS" in proc.stdout


def test_smoke_activation_rollback_cli_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/smoke_activation_rollback.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "PASS" in proc.stdout


def test_release_readiness_report_generates(tmp_path: Path) -> None:
    report = build_release_report()
    assert "release_status" in report
    assert "enabled_smoke_passed" in report
    assert "rollback_smoke_passed" in report
    out = tmp_path / "release.md"
    proc = subprocess.run(
        [PYTHON, "scripts/release_readiness_report.py", "--markdown", str(out)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Release readiness report" in text
    assert report["release_status"] in text or RELEASE_READY_FOR_STAGING in text
