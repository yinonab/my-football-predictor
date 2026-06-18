"""Phase 2D — Temporal / walk-forward backtest tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.elo_updater import update_elo_pair
from core.model_activation_gate import evaluate_activation_gate
from core.temporal_backtest import (
    TemporalMatch,
    build_rating_snapshot,
    leakage_label_for_mode,
    load_historical_matches,
    matches_before_target,
    resolve_world_elo,
    run_walk_forward_backtest,
)
from data.tournament_data import resolve_dataset_key

PYTHON = sys.executable


def test_historical_matches_sorted_by_date() -> None:
    matches = load_historical_matches("all")
    dates = [m.date for m in matches]
    assert dates == sorted(dates)
    assert all(m.date for m in matches)
    assert all(
        m.data_quality in ("exact_date", "exact_datetime") for m in matches
    )


def test_snapshot_excludes_target_and_future_matches() -> None:
    history = [
        TemporalMatch(
            "2020-01-01", "test", "A", "B", 1, 0, True, "wc2018", sequence_index=1
        ),
        TemporalMatch(
            "2020-02-01", "test", "A", "C", 2, 1, True, "wc2018", sequence_index=1
        ),
        TemporalMatch(
            "2020-03-01", "test", "A", "D", 0, 0, True, "wc2018", sequence_index=1
        ),
    ]
    target = history[-1]
    prior = matches_before_target(history, target)
    assert len(prior) == 2
    snap = build_rating_snapshot(target.date, prior)
    assert "A" in snap.teams
    assert snap.teams["A"].match_count == 2


def test_elo_updates_are_deterministic() -> None:
    a, b, _ = update_elo_pair(1600, 1500, 2, 0, k=40.0, home_advantage=0.0)
    a2, b2, _ = update_elo_pair(1600, 1500, 2, 0, k=40.0, home_advantage=0.0)
    assert a == a2 and b == b2


def test_walk_forward_backtest_runs_small_dataset() -> None:
    row = run_walk_forward_backtest(
        "wc2022",
        candidate="baseline",
        world_elo_mode="none",
    )
    assert row.matches > 0
    assert row.leakage_label == "low"
    assert row.outcome_accuracy > 0


def test_world_elo_mode_current_static_high_leakage() -> None:
    assert leakage_label_for_mode("current_static") == "high"


def test_world_elo_mode_none_does_not_use_global_ratings() -> None:
    world, avail = resolve_world_elo(
        "Brazil",
        1800.0,
        mode="none",
        rating_confidence=0.8,
    )
    assert world == 1800.0
    assert avail is False
    with patch("core.global_ratings.lookup_external_record") as mock_lookup:
        resolve_world_elo("Brazil", 1800.0, mode="none", rating_confidence=0.8)
        mock_lookup.assert_not_called()


def test_activation_gate_refuses_high_leakage_only_static() -> None:
    result = evaluate_activation_gate(run_backtests=True, run_walk_forward=False)
    assert result.status == "FAIL_HIGH_LEAKAGE"
    assert result.recommended_candidate is None


def test_activation_gate_needs_walk_forward_without_rows() -> None:
    result = evaluate_activation_gate(run_backtests=False, run_walk_forward=False)
    assert result.overall_status == "NEEDS_MORE_DATA"


def test_walk_forward_gate_can_pass_with_synthetic_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.temporal_backtest import WalkForwardBacktestRow

    monkeypatch.setattr(
        "core.model_activation_gate._external_snapshot_activation_ready",
        lambda: (True, []),
    )

    baseline = WalkForwardBacktestRow(
        dataset="WC 2022",
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
    cand = WalkForwardBacktestRow(
        dataset="WC 2022",
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
    euro_b = WalkForwardBacktestRow(
        dataset="Euro 2024",
        matches=40,
        candidate="baseline",
        elo_strategy="internal_only",
        world_elo_mode="none",
        leakage_label="low",
        outcome_accuracy=54.0,
        exact_score_accuracy=12.0,
        top3_score_hit_rate=28.0,
        mean_log_loss=0.99,
        mean_brier=0.59,
    )
    euro_c = WalkForwardBacktestRow(
        dataset="Euro 2024",
        matches=40,
        candidate="effective_elo_current_formula",
        elo_strategy="blended_confidence_weighted",
        world_elo_mode="none",
        leakage_label="low",
        outcome_accuracy=55.0,
        exact_score_accuracy=13.0,
        top3_score_hit_rate=29.0,
        mean_log_loss=0.97,
        mean_brier=0.575,
    )
    result = evaluate_activation_gate(
        walk_forward_rows=[baseline, cand, euro_b, euro_c],
        run_backtests=False,
    )
    assert result.overall_status == "MODEL_ACTIVATION_PASS"
    assert result.walk_forward_used is True


def test_backtest_walk_forward_script_runs() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/backtest_walk_forward.py",
            "--dataset",
            "wc2022",
            "--candidate",
            "baseline",
            "--world-elo-mode",
            "none",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "walk-forward" in proc.stdout.lower() or "Walk-forward" in proc.stdout


def test_compare_static_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/compare_static_vs_walk_forward.py", "--dataset", "wc2022"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0
    assert "static" in proc.stdout.lower()
    assert "walk_forward" in proc.stdout.lower()


def test_production_predictions_unchanged_by_default() -> None:
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


def test_load_historical_matches_dataset_keys() -> None:
    assert resolve_dataset_key("wc22") == "wc2022"
    m = load_historical_matches("qualifiers2026")
    assert all(not x.date_estimated for x in m)
