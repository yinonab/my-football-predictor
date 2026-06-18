"""Phase 1.6 Power Component Audit tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.power_component_audit import (
    WARNING_DEFENSE_SIGN,
    WARNING_FORM_OVERPOWERING_ELO,
    WARNING_POWER_COMPONENTS_CANCEL_ELO,
    audit_matchup_power,
    audit_sample_matchup_power,
    build_power_path_diagnostics,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager

PYTHON = sys.executable


@pytest.fixture
def data_manager() -> LiveDataManager:
    return LiveDataManager()


@pytest.fixture
def power_eval(data_manager: LiveDataManager) -> TeamPowerEvaluator:
    return TeamPowerEvaluator(data_manager)


def test_audit_power_components_script_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_power_components.py", "--only-warnings"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "team" in result.stdout
    assert "elo_c" in result.stdout


def test_audit_power_matchups_sample_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_power_matchups.py", "--sample"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Portugal" in result.stdout
    assert "driver" in result.stdout


def test_portugal_dr_congo_component_breakdown(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    home_key, _ = data_manager.resolve_team("Portugal")
    away_key, _ = data_manager.resolve_team("DR Congo")
    path = build_power_path_diagnostics(home_key, away_key, power_eval)
    gb = path["gap_breakdown"]
    assert gb["elo_component_gap"] > 100
    assert abs(gb["total_power_gap"]) < abs(gb["elo_component_gap"])
    assert gb["top_compression_driver"] != "none"


def test_brazil_morocco_form_cancels_elo(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    row = audit_matchup_power(
        "Brazil (ברזיל)",
        "Morocco (מרוקו)",
        data_manager=data_manager,
        power_eval=power_eval,
    )
    assert abs(row.power_gap) < 15
    assert row.elo_component_gap > 20
    assert row.top_compression_driver == "form_component"
    assert WARNING_FORM_OVERPOWERING_ELO in row.warnings or row.form_component_gap < 0


def test_argentina_france_no_high_severity_compression() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Argentina (ארגנטינה)",
            "away_team": "France (צרפת)",
            "neutral_ground": True,
            "use_match_context": False,
        },
    )
    assert response.status_code == 200
    grd = response.json()["global_rating_diagnostics"]
    pcd = grd["power_component_diagnostics"]
    assert pcd is not None
    high_cancel = [
        w
        for w in grd["warning_details"]
        if w["code"] == WARNING_POWER_COMPONENTS_CANCEL_ELO and w["severity"] == "high"
    ]
    assert not high_cancel
    assert abs(pcd["gap_breakdown"]["total_power_gap"]) < 50


def test_predictions_unchanged_phase16(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    payload = {
        "home_team": "Brazil (ברזיל)",
        "away_team": "Morocco (מרוקו)",
        "neutral_ground": True,
        "use_match_context": False,
    }
    client = TestClient(app)
    monkeypatch.setattr(config, "GLOBAL_RATINGS_ENABLED", False)
    monkeypatch.setattr(config, "POWER_COMPONENT_DIAGNOSTICS_ENABLED", False)
    baseline = client.post("/api/predict", json=payload).json()
    monkeypatch.setattr(config, "GLOBAL_RATINGS_ENABLED", True)
    monkeypatch.setattr(config, "POWER_COMPONENT_DIAGNOSTICS_ENABLED", True)
    monkeypatch.setattr(config, "GLOBAL_RATINGS_AFFECT_PREDICTION", False)
    with_diag = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert with_diag["probabilities_1x2"][key] == pytest.approx(
            baseline["probabilities_1x2"][key], abs=0.01
        )
    assert with_diag["global_rating_diagnostics"]["power_component_diagnostics"]


def test_defense_diagnostics_missing_gf_ga_no_crash(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = power_eval.get_power_component_diagnostics(
        data_manager.resolve_team("Curacao")[0]
    )
    assert diag["raw_inputs"]["gf"] is None or isinstance(
        diag["raw_inputs"]["gf"], (int, float)
    )
    from core.power_component_audit import assess_defense_semantics

    assert isinstance(assess_defense_semantics(diag["raw_inputs"]), list)


def test_api_includes_power_component_diagnostics() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Portugal",
            "away_team": "DR Congo",
            "neutral_ground": True,
            "use_match_context": False,
        },
    )
    grd = response.json()["global_rating_diagnostics"]
    pcd = grd["power_component_diagnostics"]
    assert pcd["gap_breakdown"]["top_compression_driver"]
    cancel = [w for w in grd["warning_details"] if w["code"] == WARNING_POWER_COMPONENTS_CANCEL_ELO]
    assert cancel
    assert cancel[0]["severity"] in ("medium", "high")


def test_portugal_dr_congo_high_severity_power_cancel(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    row = audit_matchup_power(
        "Portugal",
        "DR Congo",
        data_manager=data_manager,
        power_eval=power_eval,
    )
    assert WARNING_POWER_COMPONENTS_CANCEL_ELO in row.warnings
    assert row.compression_ratio < 0.5
