"""Phase 2A Shadow Power calibration tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.power_shadow_calibration import (
    WARNING_ADJ_FORM_HELPFUL,
    build_matchup_shadow_comparison,
    calculate_candidate_power,
    run_all_shadow_backtests,
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


def test_current_candidate_matches_production_power(
    power_eval: TeamPowerEvaluator,
    data_manager: LiveDataManager,
) -> None:
    for team in ("Portugal (פורטוגל)", "Brazil (ברזיל)", "DR Congo (קונגו)"):
        prod = power_eval.calculate_composite_power(team)
        shadow = calculate_candidate_power(team, "current", data_manager=data_manager)
        assert shadow.total_power == pytest.approx(prod, abs=0.02)


def test_defense_flipped_increases_power_for_high_defense(
    data_manager: LiveDataManager,
) -> None:
    key, data = data_manager.resolve_team("Brazil")
    if float(data.get("defense", 0.5)) < 0.55:
        pytest.skip("Brazil defense below threshold in current data")
    current = calculate_candidate_power(key, "current", data_manager=data_manager)
    flipped = calculate_candidate_power(key, "defense_flipped", data_manager=data_manager)
    assert flipped.total_power > current.total_power


def test_adjusted_form_reduces_inflated_form_teams(
    data_manager: LiveDataManager,
) -> None:
    key, _ = data_manager.resolve_team("DR Congo")
    current = calculate_candidate_power(key, "current", data_manager=data_manager)
    adjusted = calculate_candidate_power(key, "adjusted_form", data_manager=data_manager)
    if current.raw_form > current.opponent_adjusted_form + 0.05:
        assert adjusted.total_power < current.total_power


def test_defense_flipped_adjusted_form_dr_congo_norway_algeria(
    data_manager: LiveDataManager,
) -> None:
    for name in ("DR Congo", "Norway", "Algeria"):
        key, _ = data_manager.resolve_team(name)
        both = calculate_candidate_power(
            key, "defense_flipped_adjusted_form", data_manager=data_manager
        )
        current = calculate_candidate_power(key, "current", data_manager=data_manager)
        assert both.components["defense_component"] > 0
        assert both.total_power != current.total_power


def test_brazil_morocco_improves_under_candidate(
    data_manager: LiveDataManager,
) -> None:
    comp = build_matchup_shadow_comparison(
        "Brazil (ברזיל)",
        "Morocco (מרוקו)",
        data_manager=data_manager,
    )
    current_gap = abs(comp["variants"]["current"]["power_gap"])
    adj_gap = abs(comp["variants"]["adjusted_form"]["power_gap"])
    assert adj_gap > current_gap + 5


def test_portugal_dr_congo_compression_improves(
    data_manager: LiveDataManager,
) -> None:
    comp = build_matchup_shadow_comparison(
        "Portugal",
        "DR Congo",
        data_manager=data_manager,
    )
    cur_ratio = comp["variants"]["current"]["compression_ratio"]
    best = comp["matchup_comparison"]["best_alignment_variant"]
    best_ratio = comp["variants"][best]["compression_ratio"]
    assert best_ratio < cur_ratio or comp["variants"][best]["power_gap"] > comp["variants"]["current"]["power_gap"]


def test_argentina_france_not_extreme_mismatch(
    data_manager: LiveDataManager,
) -> None:
    comp = build_matchup_shadow_comparison(
        "Argentina (ארגנטינה)",
        "France (צרפת)",
        data_manager=data_manager,
    )
    for variant in config.POWER_SHADOW_VARIANTS:
        gap = abs(comp["variants"][variant]["power_gap"])
        assert gap < 120


def test_api_includes_power_shadow_calibration() -> None:
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
    assert response.status_code == 200
    shadow = response.json()["global_rating_diagnostics"]["power_shadow_calibration"]
    assert shadow is not None
    assert shadow["enabled"] is True
    assert shadow["affects_prediction"] is False
    assert "current" in shadow["variants"]
    assert shadow["matchup_comparison"]["best_alignment_variant"]


def test_predictions_unchanged_when_candidate_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    payload = {
        "home_team": "Portugal",
        "away_team": "DR Congo",
        "neutral_ground": True,
        "use_match_context": False,
    }
    client = TestClient(app)
    monkeypatch.setattr(config, "POWER_SHADOW_CALIBRATION_ENABLED", False)
    baseline = client.post("/api/predict", json=payload).json()
    monkeypatch.setattr(config, "POWER_SHADOW_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", False)
    with_shadow = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert with_shadow["probabilities_1x2"][key] == pytest.approx(
            baseline["probabilities_1x2"][key], abs=0.01
        )
    assert with_shadow["home_power"] == pytest.approx(baseline["home_power"], abs=0.01)
    assert with_shadow["global_rating_diagnostics"]["power_shadow_calibration"]


def test_audit_power_shadow_script_runs() -> None:
    result = subprocess.run(
        [PYTHON, "scripts/audit_power_shadow.py", "--sample"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Brazil" in result.stdout


def test_backtest_power_shadow_runs() -> None:
    rows = run_all_shadow_backtests()
    assert len(rows) == len(config.POWER_SHADOW_VARIANTS)
    current = next(r for r in rows if r.variant == "current")
    assert current.outcome_accuracy > 40


def test_defense_diagnostics_missing_data_no_crash(
    data_manager: LiveDataManager,
) -> None:
    key, _ = data_manager.resolve_team("Curacao")
    result = calculate_candidate_power(key, "current", data_manager=data_manager)
    assert result.components["defense_component"] is not None


def test_portugal_dr_congo_shadow_warnings(
    data_manager: LiveDataManager,
) -> None:
    comp = build_matchup_shadow_comparison(
        "Portugal",
        "DR Congo",
        data_manager=data_manager,
    )
    warnings = comp["matchup_comparison"]["warnings"]
    assert comp["variants"]["adjusted_form"]["power_gap"] > comp["variants"]["current"]["power_gap"]
    assert WARNING_ADJ_FORM_HELPFUL in warnings or any(
        "REDUCES_COMPRESSION" in w for w in warnings
    )
