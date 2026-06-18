"""Phase 2I — FIFA points external snapshot mode tests."""

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
from core.external_rating_mode import (
    NORMALIZATION_METHOD,
    normalize_fifa_points_to_elo_like,
    resolve_external_rating_mode,
)
from core.external_rating_snapshots import (
    WARNING_SNAPSHOT_PARTIAL_FIFA_COVERAGE,
    WARNING_SNAPSHOT_WORLD_ELO_MISSING,
    build_fifa_points_snapshot_document,
    validate_external_rating_snapshot,
    write_external_rating_snapshots_file,
)
from core.model_activation_gate import evaluate_activation_gate
from core.temporal_backtest import (
    WalkForwardBacktestRow,
    compute_temporal_external_anchor,
    run_walk_forward_backtest,
)

PYTHON = sys.executable


def test_fifa_points_populated_from_repo_constants() -> None:
    doc = build_fifa_points_snapshot_document()
    wc2022 = doc["wc2022"]
    assert wc2022["rating_type"] == "fifa_ranking_points"
    assert wc2022["source"] == "repo_pre_tournament_fifa_points"
    brazil = wc2022["teams"]["Brazil"]
    assert brazil["world_elo"] is None
    assert brazil["fifa_points"] is not None
    assert "WC2022" in brazil["notes"]


def test_validator_reports_separate_coverages() -> None:
    report = validate_external_rating_snapshot("wc2022")
    assert report.world_elo_coverage == 0.0
    assert report.fifa_points_coverage == 1.0
    assert report.any_external_rating_coverage == 1.0
    assert WARNING_SNAPSHOT_WORLD_ELO_MISSING in report.warnings


def test_fifa_mode_does_not_require_world_elo() -> None:
    report = validate_external_rating_snapshot(
        "wc2022", external_rating_mode="fifa_points_snapshot"
    )
    assert report.leakage == "low"
    assert report.status == "ok"


def test_fifa_normalization_is_deterministic() -> None:
    first = normalize_fifa_points_to_elo_like(1841.0, "wc2022")
    second = normalize_fifa_points_to_elo_like(1841.0, "wc2022")
    assert first == second
    assert first["normalization_method"] == NORMALIZATION_METHOD
    assert first["normalized_external_rating"] is not None


def test_euro2024_poland_partial_fifa_coverage(tmp_path: Path) -> None:
    doc = build_fifa_points_snapshot_document()
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with patch.object(config, "EXTERNAL_RATING_SNAPSHOTS_PATH", str(path)):
        report = validate_external_rating_snapshot(
            "euro2024", external_rating_mode="fifa_points_snapshot"
        )
    assert report.teams == 24
    assert report.fifa_points_coverage == pytest.approx(23 / 24, abs=0.01)
    assert WARNING_SNAPSHOT_PARTIAL_FIFA_COVERAGE in report.warnings
    assert "Poland" not in doc["euro2024"]["teams"] or (
        doc["euro2024"]["teams"].get("Poland", {}).get("fifa_points") is None
    )


def test_world_elo_snapshot_blocked_with_zero_world_elo() -> None:
    report = validate_external_rating_snapshot(
        "wc2022", external_rating_mode="world_elo_snapshot"
    )
    assert report.world_elo_coverage == 0.0
    assert report.leakage == "high"


def test_fifa_points_snapshot_walk_forward_runs() -> None:
    row = run_walk_forward_backtest(
        "wc2022",
        candidate="effective_external_current_formula",
        elo_strategy="fifa_points_snapshot_static",
        external_rating_mode="fifa_points_snapshot",
        prior_mode="tournament_prior_file",
    )
    assert row.matches > 0
    assert row.external_rating_mode == "fifa_points_snapshot"
    assert row.external_rating_type == "fifa_points"
    assert row.external_coverage == 1.0
    assert row.normalization_method == NORMALIZATION_METHOD


def test_legacy_world_elo_mode_maps_to_external_mode() -> None:
    assert resolve_external_rating_mode(world_elo_mode="snapshot_file") == "world_elo_snapshot"
    assert resolve_external_rating_mode(world_elo_mode="none") == "none"


def test_activation_gate_fifa_without_meaningful_improvement() -> None:
    rows: list[WalkForwardBacktestRow] = []
    for ds in ("WC 2022",):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=1.0,
                normalization_method=NORMALIZATION_METHOD,
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
                candidate="effective_external_current_formula",
                elo_strategy="fifa_points_confidence_weighted",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=1.0,
                normalization_method=NORMALIZATION_METHOD,
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
    assert result.recommended_candidate is None
    assert result.overall_status == "DATA_READY_MODEL_NEUTRAL"


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


def test_written_snapshot_file_has_fifa_not_world_elo(tmp_path: Path) -> None:
    target = write_external_rating_snapshots_file(tmp_path / "external.json")
    data = json.loads(target.read_text(encoding="utf-8"))
    for key in ("wc2018", "wc2022", "euro2024", "copa2024"):
        block = data[key]
        assert block["rating_type"] == "fifa_ranking_points"
        for entry in block["teams"].values():
            assert entry["world_elo"] is None


def test_validate_snapshot_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/validate_external_rating_snapshots.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "fifa" in proc.stdout.lower() or "w_elo" in proc.stdout
