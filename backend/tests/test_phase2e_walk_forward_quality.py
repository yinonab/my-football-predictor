"""Phase 2E — Walk-forward data quality hardening tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.model_activation_gate import evaluate_activation_gate
from core.fixture_metadata import audit_dataset_coverage
from core.temporal_match_data import (
    WARNING_PRIOR_AS_OF_AFTER_MATCH,
    apply_match_date_overrides,
    audit_dataset_data_quality,
    load_match_date_overrides,
    resolve_initial_elos,
    serious_walk_forward_candidates,
)
from core.temporal_backtest import (
    TemporalMatch,
    load_historical_matches,
    matches_before_target,
    run_walk_forward_backtest,
)
from data.tournament_data import resolve_dataset_key

PYTHON = sys.executable


def test_match_date_overrides_applied() -> None:
    matches = [
        TemporalMatch(
            date="2022-11-20",
            competition="FIFA World Cup",
            home_team="Qatar",
            away_team="Ecuador",
            home_goals=0,
            away_goals=2,
            neutral_ground=False,
            source="wc2022",
            data_quality="estimated_order",
            date_estimated=True,
        )
    ]
    updated = apply_match_date_overrides(matches, "wc2022")
    assert updated[0].kickoff_time == "19:00"
    assert updated[0].data_quality == "exact_datetime"
    assert updated[0].date_estimated is False


def test_complete_fixture_metadata_low_leakage() -> None:
    report = audit_dataset_data_quality(
        "wc2022",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
    )
    assert report.estimated_order_count == 0
    assert report.exact_date_count + report.exact_datetime_count == report.matches
    assert report.leakage_label == "low"


def test_qualifiers_exact_dates_lower_leakage() -> None:
    report = audit_dataset_data_quality("qualifiers2026", world_elo_mode="none")
    assert report.exact_date_count == report.matches
    assert report.leakage_label == "low"


def test_prior_as_of_after_match_rejected() -> None:
    elos, quality, warnings = resolve_initial_elos(
        "wc2022",
        "2022-01-01",
        prior_mode="tournament_prior_file",
    )
    assert quality == "rejected_leakage"
    assert WARNING_PRIOR_AS_OF_AFTER_MATCH in warnings
    assert elos == {}


def test_missing_priors_fallback() -> None:
    elos, quality, warnings = resolve_initial_elos(
        "qualifiers2026",
        "2025-06-01",
        prior_mode="tournament_prior_file",
    )
    assert quality == "default_internal"
    assert elos == {}


def test_matches_before_target_excludes_same_day_later_sequence() -> None:
    early = TemporalMatch(
        date="2022-11-20",
        competition="x",
        home_team="A",
        away_team="B",
        home_goals=1,
        away_goals=0,
        neutral_ground=True,
        source="wc2022",
        sequence_index=1,
    )
    late = TemporalMatch(
        date="2022-11-20",
        competition="x",
        home_team="C",
        away_team="D",
        home_goals=0,
        away_goals=0,
        neutral_ground=True,
        source="wc2022",
        sequence_index=2,
    )
    prior = matches_before_target([early, late], late)
    assert len(prior) == 1
    assert prior[0].home_team == "A"


def test_serious_candidates_exclude_defense_flip() -> None:
    serious = serious_walk_forward_candidates(include_defense_flip=False)
    assert all("defense_flipped" not in c for c, _ in serious)
    with_flip = serious_walk_forward_candidates(include_defense_flip=True)
    assert len(with_flip) > len(serious)


def test_walk_forward_candidate_comparison_runs() -> None:
    row = run_walk_forward_backtest(
        "wc2022",
        candidate="effective_elo_current_formula",
        elo_strategy="blended_confidence_weighted",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
    )
    assert row.matches > 0
    assert row.prior_mode == "tournament_prior_file"
    assert row.data_quality in ("mixed", "estimated_order", "exact_date", "exact_datetime")


def test_activation_gate_refuses_medium_only_for_pass() -> None:
    from core.temporal_backtest import WalkForwardBacktestRow

    rows = [
        WalkForwardBacktestRow(
            dataset="WC 2022",
            matches=64,
            candidate="baseline",
            elo_strategy="internal_only",
            prior_mode="default_internal",
            world_elo_mode="none",
            leakage_label="medium",
            data_quality="estimated_order",
            outcome_accuracy=42.0,
            exact_score_accuracy=8.0,
            top3_score_hit_rate=25.0,
            mean_log_loss=1.09,
            mean_brier=0.66,
        ),
        WalkForwardBacktestRow(
            dataset="WC 2022",
            matches=64,
            candidate="effective_elo_current_formula",
            elo_strategy="blended_confidence_weighted",
            prior_mode="default_internal",
            world_elo_mode="none",
            leakage_label="medium",
            data_quality="estimated_order",
            outcome_accuracy=43.0,
            exact_score_accuracy=9.0,
            top3_score_hit_rate=26.0,
            mean_log_loss=1.05,
            mean_brier=0.64,
        ),
    ]
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status != "MODEL_ACTIVATION_PASS"


def test_world_elo_current_static_blocked() -> None:
    from core.temporal_backtest import WalkForwardBacktestRow

    rows = [
        WalkForwardBacktestRow(
            dataset="WC 2022",
            matches=10,
            candidate="baseline",
            elo_strategy="internal_only",
            prior_mode="default_internal",
            world_elo_mode="current_static",
            leakage_label="high",
            data_quality="estimated_order",
            outcome_accuracy=50.0,
            exact_score_accuracy=10.0,
            top3_score_hit_rate=20.0,
            mean_log_loss=1.0,
            mean_brier=0.6,
        )
    ]
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "FAIL_HIGH_LEAKAGE"


def test_audit_data_quality_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/audit_walk_forward_data_quality.py", "--dataset", "wc2022"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "wc2022" in proc.stdout.lower() or "WC 2022" in proc.stdout


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


def test_load_overrides_file_exists() -> None:
    overrides = load_match_date_overrides("wc2022")
    assert len(overrides) >= 1
    assert overrides[0]["home_team"] == "Qatar"
