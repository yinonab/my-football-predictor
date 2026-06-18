"""Phase 2C — Multi-tournament backtest, leakage audit, activation gate tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.backtest_leakage_audit import audit_backtest_leakage
from core.model_activation_gate import (
    WARNING_BALANCED_SHIFT,
    ActivationGateResult,
    activation_candidate_status,
    check_balanced_match_shift,
    evaluate_activation_gate,
)
from core.power_multitournament_backtest import (
    MultiTournamentBacktestRow,
    run_dataset_backtests,
    serious_backtest_candidates,
)
from data.tournament_data import get_dataset, list_dataset_keys, resolve_dataset_key

PYTHON = sys.executable


def test_dataset_registry_keys() -> None:
    keys = list_dataset_keys()
    assert "wc2018" in keys
    assert "wc2022" in keys
    assert "euro2024" in keys
    assert resolve_dataset_key("wc22") == "wc2022"


def test_serious_candidates_exclude_defense_flip_by_default() -> None:
    serious = serious_backtest_candidates(include_defense_flip=False)
    assert all("defense_flipped" not in v for v, _ in serious)
    assert len(serious) == 7
    with_flip = serious_backtest_candidates(include_defense_flip=True)
    assert len(with_flip) > len(serious)
    assert any("defense_flipped" in v for v, _ in with_flip)


def test_run_dataset_backtest_wc2022() -> None:
    rows = run_dataset_backtests("wc2022", include_defense_flip=False)
    assert len(rows) == 7
    baseline = next(r for r in rows if r.variant == "current")
    assert baseline.matches > 0
    assert baseline.outcome_accuracy > 0


def test_dataset_all_does_not_crash() -> None:
    rows = run_dataset_backtests("all", include_defense_flip=False)
    assert len(rows) > 0
    datasets = {r.dataset for r in rows}
    assert "All Combined" in datasets
    assert "WC 2022" in datasets


def test_leakage_audit_produces_risk_level() -> None:
    report = audit_backtest_leakage()
    assert report.leakage_risk_level in ("low", "medium", "high")
    assert len(report.findings) >= 3
    assert len(report.recommendations) >= 2


def test_balanced_match_shift_warning() -> None:
    baseline = {"home_win": 33.0, "draw": 34.0, "away_win": 33.0}
    shifted = {"home_win": 41.0, "draw": 30.0, "away_win": 29.0}
    assert check_balanced_match_shift(baseline, shifted) == WARNING_BALANCED_SHIFT
    stable = {"home_win": 35.0, "draw": 33.0, "away_win": 32.0}
    assert check_balanced_match_shift(baseline, stable) is None


def _sample_rows(
    *,
    cand_log: float = 0.95,
    cand_brier: float = 0.56,
    cand_1x2: float = 57.0,
    baseline_log: float = 0.98,
    baseline_brier: float = 0.58,
    baseline_1x2: float = 57.8,
) -> list[MultiTournamentBacktestRow]:
    datasets = ["WC 2018", "WC 2022", "Euro 2024"]
    rows: list[MultiTournamentBacktestRow] = []
    for ds in datasets:
        rows.append(
            MultiTournamentBacktestRow(
                dataset=ds,
                matches=50,
                variant="current",
                elo_strategy="internal_only",
                outcome_accuracy=baseline_1x2,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=baseline_log,
                mean_brier=baseline_brier,
                favorite_calibration_error=0.45,
                underdog_overconfidence_error=0.5,
                avg_home_win_delta_vs_current=0.0,
                avg_draw_delta_vs_current=0.0,
                avg_away_win_delta_vs_current=0.0,
            )
        )
        rows.append(
            MultiTournamentBacktestRow(
                dataset=ds,
                matches=50,
                variant="effective_elo_current_formula",
                elo_strategy="blended_confidence_weighted",
                outcome_accuracy=cand_1x2,
                exact_score_accuracy=11.0,
                top3_score_hit_rate=26.0,
                mean_log_loss=cand_log,
                mean_brier=cand_brier,
                favorite_calibration_error=0.43,
                underdog_overconfidence_error=0.48,
                avg_home_win_delta_vs_current=0.5,
                avg_draw_delta_vs_current=-0.2,
                avg_away_win_delta_vs_current=-0.3,
            )
        )
    return rows


def test_activation_gate_fail_when_1x2_drop_exceeds_threshold() -> None:
    from core.temporal_backtest import WalkForwardBacktestRow

    rows = []
    for ds in ("WC 2018", "WC 2022"):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="baseline",
                elo_strategy="internal_only",
                world_elo_mode="none",
                leakage_label="low",
                outcome_accuracy=57.8,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=0.98,
                mean_brier=0.58,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="effective_elo_current_formula",
                elo_strategy="blended_confidence_weighted",
                world_elo_mode="none",
                leakage_label="low",
                outcome_accuracy=55.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=0.97,
                mean_brier=0.57,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "FAIL_MODEL_METRICS"
    assert result.recommended_candidate is None


def test_activation_gate_pass_when_conditions_met(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.temporal_backtest import WalkForwardBacktestRow

    monkeypatch.setattr(
        "core.model_activation_gate._external_snapshot_activation_ready",
        lambda: (True, []),
    )

    rows = []
    for ds in ("WC 2018", "WC 2022", "Euro 2024"):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="baseline",
                elo_strategy="internal_only",
                world_elo_mode="none",
                leakage_label="low",
                outcome_accuracy=57.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=0.98,
                mean_brier=0.58,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="effective_elo_current_formula",
                elo_strategy="blended_confidence_weighted",
                world_elo_mode="none",
                leakage_label="low",
                outcome_accuracy=57.5,
                exact_score_accuracy=11.0,
                top3_score_hit_rate=26.0,
                mean_log_loss=0.96,
                mean_brier=0.565,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "MODEL_ACTIVATION_PASS"
    assert result.recommended_candidate is not None
    assert result.recommended_candidate["variant"] == "effective_elo_current_formula"


def test_activation_candidate_status_shadow_only_by_default() -> None:
    assert activation_candidate_status() == "shadow_only"
    assert activation_candidate_status(
        ActivationGateResult(
            recommended_candidate=None,
            status="FAIL_HIGH_LEAKAGE",
            temporal_data_status="FAIL_HIGH_LEAKAGE",
            model_candidate_status="NOT_EVALUATED",
            overall_status="FAIL_HIGH_LEAKAGE",
            reasons=[],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level="high",
            balanced_match_warnings=[],
        )
    ) == "gate_failed"


def test_backtest_script_supports_dataset_argument() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/backtest_power_shadow.py", "--list-datasets"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "wc2018" in proc.stdout


def test_leakage_audit_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/audit_backtest_leakage.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "Leakage risk level" in proc.stdout


def test_regression_diagnostic_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/regression_diagnostic_matchups.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "Brazil" in proc.stdout


def test_production_predictions_unchanged_by_default() -> None:
    """Default predict response must not use candidate power."""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r1 = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    )
    assert r1.status_code == 200
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False
    assert config.GLOBAL_RATINGS_AFFECT_PREDICTION is False
    body = r1.json()
    assert "probabilities_1x2" in body
    if body.get("global_rating_diagnostics", {}).get("power_shadow_calibration"):
        psc = body["global_rating_diagnostics"]["power_shadow_calibration"]
        assert psc.get("affects_prediction") is False
        assert psc.get("activation_candidate_status") in (
            "shadow_only",
            "not_evaluated",
            "gate_failed",
            "gate_passed",
            "data_ready_model_neutral",
        )


def test_api_activation_status_when_shadow_enabled() -> None:
    if not config.POWER_SHADOW_CALIBRATION_ENABLED:
        pytest.skip("shadow calibration disabled")
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r = client.post(
        "/api/predict",
        json={"home_team": "Argentina", "away_team": "France", "neutral_ground": True},
    )
    assert r.status_code == 200
    psc = r.json().get("global_rating_diagnostics", {}).get("power_shadow_calibration")
    if psc:
        assert psc.get("activation_candidate_status") == "shadow_only"
