"""Phase 1.5 Global Rating Stack audit tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.global_ratings import (
    WARNING_POWER_COMPRESSED,
    build_match_diagnostics,
    global_strength_gap_label,
)
from core.global_ratings_audit import (
    audit_all_teams,
    audit_sample_matchups,
    build_matchup_audit_row,
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


def _match_diag(power_eval, data_manager, home_input, away_input):
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


def test_global_strength_gap_label_buckets() -> None:
    assert global_strength_gap_label(0.02) == "tiny"
    assert global_strength_gap_label(0.08) == "small"
    assert global_strength_gap_label(0.15) == "medium"
    assert global_strength_gap_label(0.30) == "large"
    assert global_strength_gap_label(0.40) == "extreme"


def test_gap_labels_present_in_diagnostics(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Portugal (פורטוגל)",
        "DR Congo (קונגו)",
    )
    gaps = diag.gaps
    assert gaps.global_strength_gap_raw >= 0
    assert gaps.global_strength_gap_label in {
        "tiny",
        "small",
        "medium",
        "large",
        "extreme",
    }
    assert gaps.power_compression_ratio == pytest.approx(
        abs(gaps.power_gap) / max(abs(gaps.internal_elo_gap), 1.0),
        rel=0.01,
    )
    assert gaps.power_vs_elo_gap_delta == pytest.approx(
        abs(gaps.power_gap) - abs(gaps.internal_elo_gap), abs=0.1
    )


def test_portugal_dr_congo_high_severity_power_compressed(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Portugal (פורטוגל)",
        "DR Congo (קונגו)",
    )
    power_warnings = [
        w for w in diag.warning_details if w.code == WARNING_POWER_COMPRESSED
    ]
    assert power_warnings
    assert power_warnings[0].severity == "high"
    assert power_warnings[0].metrics["compression_ratio"] <= 0.50
    assert abs(diag.gaps.internal_elo_gap) >= 200


def test_argentina_france_no_high_severity_compression(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    diag = _match_diag(
        power_eval,
        data_manager,
        "Argentina (ארגנטינה)",
        "France (צרפת)",
    )
    power_warnings = [
        w for w in diag.warning_details if w.code == WARNING_POWER_COMPRESSED
    ]
    assert not any(w.severity == "high" for w in power_warnings)
    assert abs(diag.gaps.global_strength_gap) < config.GLOBAL_STRENGTH_GAP_SMALL_MAX


def test_warning_details_in_predict_response() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Portugal (פורטוגל)",
            "away_team": "DR Congo (קונגו)",
            "neutral_ground": True,
            "use_match_context": False,
        },
    )
    assert response.status_code == 200
    grd = response.json()["global_rating_diagnostics"]
    assert grd["gaps"]["global_strength_gap_label"]
    assert grd["warning_details"]
    codes = {item["code"] for item in grd["warning_details"]}
    assert WARNING_POWER_COMPRESSED in codes
    high = [
        item
        for item in grd["warning_details"]
        if item["code"] == WARNING_POWER_COMPRESSED and item["severity"] == "high"
    ]
    assert high


def test_audit_global_ratings_script_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_global_ratings.py", "--only-warnings"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "team" in result.stdout
    assert "warnings" in result.stdout


def test_audit_matchup_divergence_sample_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_matchup_divergence.py", "--sample"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Portugal" in result.stdout
    assert "POWER_COMPRESSED_VS_ELO" in result.stdout


def test_matchup_audit_portugal_dr_congo_high_severity(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    row = build_matchup_audit_row(
        "Portugal (פורטוגל)",
        "DR Congo (קונגו)",
        data_manager=data_manager,
        power_eval=power_eval,
    )
    assert row.max_warning_severity == "high"
    assert WARNING_POWER_COMPRESSED in row.warnings


def test_team_audit_missing_external_fallback(
    data_manager: LiveDataManager,
    power_eval: TeamPowerEvaluator,
) -> None:
    rows = audit_all_teams(data_manager, power_eval)
    netherlands = next(r for r in rows if r.team == "Netherlands")
    assert netherlands.missing_external_rating is True
    assert netherlands.internal_elo == netherlands.world_elo


def test_predictions_unchanged_phase15(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    payload = {
        "home_team": "Spain (ספרד)",
        "away_team": "Cape Verde (כף ורד)",
        "neutral_ground": True,
        "use_match_context": False,
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
    assert with_diag["global_rating_diagnostics"]["warning_details"]
