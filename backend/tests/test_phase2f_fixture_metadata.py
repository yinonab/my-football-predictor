"""Phase 2F — Historical fixture metadata completion tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.fixture_metadata import (
    TOURNAMENT_STARTS,
    audit_dataset_coverage,
    classify_dataset_leakage,
    validate_dataset_overrides,
)
from core.temporal_match_data import (
    WARNING_PRIOR_AS_OF_AFTER_MATCH,
    apply_match_date_overrides,
    resolve_initial_elos,
)
from core.temporal_backtest import TemporalMatch, load_historical_matches

PYTHON = sys.executable


def test_override_validation_all_tournaments_ok() -> None:
    for ds in TOURNAMENT_STARTS:
        report = validate_dataset_overrides(ds)
        assert report.status == "ok", f"{ds}: {report.unmatched_pairs}"
        assert report.matched == report.matches
        # Rematches (e.g. Argentina vs Canada in Copa) may share a pair key.
        assert report.unmatched == 0


def test_duplicate_overrides_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = {
        "wc2022": [
            {
                "home_team": "Qatar",
                "away_team": "Ecuador",
                "date": "2022-11-20",
                "sequence_index": 1,
            },
            {
                "home_team": "Qatar",
                "away_team": "Ecuador",
                "date": "2022-11-21",
                "sequence_index": 1,
            },
        ]
    }
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(config, "TEMPORAL_MATCH_DATES_OVERRIDES_PATH", str(path))
    report = validate_dataset_overrides("wc2022")
    assert report.status == "fail"
    assert any("duplicate_sequence" in u for u in report.unmatched_pairs)


def test_unmatched_teams_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = {
        "wc2022": [
            {
                "home_team": "NotARealTeam",
                "away_team": "AlsoFake",
                "date": "2022-11-20",
                "sequence_index": 99,
            }
        ]
    }
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(config, "TEMPORAL_MATCH_DATES_OVERRIDES_PATH", str(path))
    report = validate_dataset_overrides("wc2022")
    assert report.unmatched > 0
    assert report.status != "ok"


def test_exact_dates_improve_data_quality_score() -> None:
    cov = audit_dataset_coverage("wc2022", prior_mode="tournament_prior_file")
    assert cov.estimated_order_count == 0
    assert cov.data_quality_score >= 0.85
    assert cov.override_coverage == 1.0


def test_complete_sequence_index_same_day_ordering() -> None:
    matches = load_historical_matches("wc2022", apply_overrides=True)
    by_day: dict[str, list[int]] = {}
    for m in matches:
        by_day.setdefault(m.date, []).append(m.sequence_index)
    for day, seqs in by_day.items():
        assert len(seqs) == len(set(seqs)), f"ambiguous order on {day}"


def test_priors_after_tournament_start_rejected() -> None:
    elos, quality, warnings = resolve_initial_elos(
        "wc2022",
        "2022-11-19",
        prior_mode="tournament_prior_file",
    )
    assert quality == "rejected_leakage"
    assert WARNING_PRIOR_AS_OF_AFTER_MATCH in warnings
    assert elos == {}


def test_low_leakage_only_when_requirements_met() -> None:
    good = load_historical_matches("wc2022", apply_overrides=True)
    label, ready, blockers = classify_dataset_leakage(
        good,
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        dataset_key="wc2022",
    )
    assert label == "low"
    assert ready is True
    assert blockers == []

    bad = [
        TemporalMatch(
            date="2022-11-20",
            competition="x",
            home_team="A",
            away_team="B",
            home_goals=0,
            away_goals=0,
            neutral_ground=True,
            source="wc2022",
            data_quality="estimated_order",
            date_estimated=True,
        )
    ]
    label2, ready2, blockers2 = classify_dataset_leakage(
        bad,
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        dataset_key="wc2022",
    )
    assert label2 == "medium"
    assert ready2 is False
    assert "MATCH_DATES_ESTIMATED" in blockers2


def test_current_static_world_elo_high_leakage() -> None:
    matches = load_historical_matches("wc2022", apply_overrides=True)
    label, ready, blockers = classify_dataset_leakage(
        matches,
        world_elo_mode="current_static",
        prior_mode="tournament_prior_file",
        dataset_key="wc2022",
    )
    assert label == "high"
    assert ready is False


def test_validate_script_runs() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/validate_match_date_overrides.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "wc2022" in proc.stdout


def test_coverage_report_runs() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/audit_walk_forward_data_quality.py",
            "--coverage",
            "--dataset",
            "wc2022",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "override" in proc.stdout.lower() or "ovr" in proc.stdout.lower()


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


def test_kickoff_override_exact_datetime() -> None:
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
