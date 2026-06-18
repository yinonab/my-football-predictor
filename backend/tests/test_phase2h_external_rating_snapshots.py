"""Phase 2H — Historical external rating snapshot tests."""

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
from core.external_rating_snapshots import (
    WARNING_SNAPSHOT_AFTER_TOURNAMENT_START,
    WARNING_SNAPSHOT_EMPTY,
    WARNING_SNAPSHOT_PARTIAL_COVERAGE,
    validate_external_rating_snapshot,
)
from core.model_activation_gate import evaluate_activation_gate
from core.temporal_backtest import (
    WalkForwardBacktestRow,
    resolve_world_elo,
    run_walk_forward_backtest,
)

PYTHON = sys.executable


def test_empty_snapshot_validates_with_snapshot_empty(tmp_path: Path) -> None:
    doc = {
        "wc2022": {
            "as_of": "2022-11-19",
            "source": "manual_pre_tournament_snapshot",
            "rating_type": "world_elo_or_external",
            "teams": {},
        }
    }
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with patch.object(config, "EXTERNAL_RATING_SNAPSHOTS_PATH", str(path)):
        report = validate_external_rating_snapshot("wc2022")
    assert WARNING_SNAPSHOT_EMPTY in report.warnings
    assert report.coverage == 0.0
    assert report.status in ("incomplete", "fail")


def test_snapshot_as_of_after_first_match_high_leakage(tmp_path: Path) -> None:
    doc = {
        "wc2022": {
            "as_of": "2022-12-01",
            "teams": {"Brazil": {"world_elo": 2000}},
        }
    }
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with patch.object(config, "EXTERNAL_RATING_SNAPSHOTS_PATH", str(path)):
        report = validate_external_rating_snapshot("wc2022")
    assert WARNING_SNAPSHOT_AFTER_TOURNAMENT_START in report.warnings
    assert report.leakage == "high"


def test_partial_coverage_reports_warning() -> None:
    report = validate_external_rating_snapshot(
        "wc2022", external_rating_mode="world_elo_snapshot"
    )
    assert report.world_elo_coverage < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION
    assert WARNING_SNAPSHOT_PARTIAL_COVERAGE in report.warnings


def test_snapshot_file_does_not_use_current_static() -> None:
    world, avail = resolve_world_elo(
        "Brazil",
        1600.0,
        mode="snapshot_file",
        rating_confidence=0.8,
        dataset_key="wc2022",
    )
    assert world == 1600.0
    assert avail is False


def test_snapshot_file_with_rating_uses_snapshot(tmp_path: Path) -> None:
    doc = {
        "wc2022": {
            "as_of": "2022-11-19",
            "teams": {"Brazil": {"world_elo": 1841}},
        }
    }
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with patch.object(config, "EXTERNAL_RATING_SNAPSHOTS_PATH", str(path)):
        world, avail = resolve_world_elo(
            "Brazil",
            1600.0,
            mode="snapshot_file",
            rating_confidence=0.8,
            dataset_key="wc2022",
            match_date="2022-11-20",
        )
    assert avail is True
    assert world == 1841.0


def test_activation_gate_needs_external_snapshot_for_effective_elo() -> None:
    rows: list[WalkForwardBacktestRow] = []
    for ds in ("WC 2018", "WC 2022", "Euro 2024", "Copa America 2024"):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=55.0,
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
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=55.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=0.98,
                mean_brier=0.58,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.temporal_data_status == "PASS"
    assert result.model_candidate_status == "NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA"
    assert result.recommended_candidate is None
    assert result.overall_status == "DATA_READY_MODEL_NEUTRAL"


def test_baseline_walk_forward_runs_with_world_elo_none() -> None:
    row = run_walk_forward_backtest(
        "wc2022",
        candidate="baseline",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
    )
    assert row.matches > 0
    assert row.world_elo_mode == "none"


def test_snapshot_file_walk_forward_runs_with_notes() -> None:
    row = run_walk_forward_backtest(
        "wc2022",
        candidate="effective_elo_current_formula",
        elo_strategy="blended_confidence_weighted",
        world_elo_mode="snapshot_file",
        prior_mode="tournament_prior_file",
    )
    assert row.matches > 0
    assert "world_elo_snapshot" in row.notes
    assert row.leakage_label in ("medium", "high")


def test_validate_snapshot_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/validate_external_rating_snapshots.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "wc2022" in proc.stdout


def test_production_predictions_unchanged() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    )
    assert r.status_code == 200
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False
    assert config.GLOBAL_RATINGS_AFFECT_PREDICTION is False
