"""Phase 3B — Production FIFA snapshot coverage and activation readiness tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.active_model_activation import (
    SAMPLE_PRODUCTION_MATCHUPS,
    resolve_fifa_snapshot_dataset,
    resolve_historical_fifa_snapshot_dataset,
    resolve_production_fifa_snapshot_dataset,
    run_prediction_with_active_candidate,
    try_apply_active_candidate_powers,
    validate_activation_configuration,
)
from core.external_rating_snapshots import (
    PRODUCTION_SNAPSHOT_KEYS,
    WARNING_SNAPSHOT_AS_OF_APPROXIMATE,
    WARNING_SNAPSHOT_PRODUCTION_CURRENT,
    build_full_snapshot_document,
    build_wc2026_current_snapshot_block,
    external_fifa_points_production_ready,
    get_team_fifa_points,
    list_production_team_names,
    load_external_rating_snapshots,
    validate_external_rating_snapshot,
    write_external_rating_snapshots_file,
)
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

PYTHON = sys.executable


@pytest.fixture(scope="module", autouse=True)
def ensure_production_snapshot_file() -> None:
    write_external_rating_snapshots_file()


def test_production_snapshot_separate_from_historical() -> None:
    doc = build_full_snapshot_document()
    assert "wc2022" in doc
    assert config.PRODUCTION_FIFA_SNAPSHOT_DATASET in doc
    prod = doc[config.PRODUCTION_FIFA_SNAPSHOT_DATASET]
    hist = doc["wc2022"]
    assert prod["rating_type"] == "fifa_ranking_points_current"
    assert hist["rating_type"] == "fifa_ranking_points"
    assert prod["source"] == "repo_FIFA_ELO_2026"
    assert len(prod["teams"]) == len(FIFA_ELO_2026)


def test_fifa_elo_2026_populates_fifa_points_not_world_elo() -> None:
    block = build_wc2026_current_snapshot_block()
    for _name, entry in block["teams"].items():
        assert entry["fifa_points"] is not None
        assert entry["world_elo"] is None
    brazil = block["teams"]["Brazil"]
    assert brazil["fifa_points"] == int(FIFA_ELO_2026["Brazil (ברזיל)"])


def test_production_validator_reports_coverage() -> None:
    report = validate_external_rating_snapshot(
        config.PRODUCTION_FIFA_SNAPSHOT_DATASET,
        external_rating_mode="fifa_points_snapshot",
    )
    assert report.teams == len(FIFA_ELO_2026)
    assert report.fifa_points_coverage == 1.0
    assert report.status == "ok"
    assert WARNING_SNAPSHOT_PRODUCTION_CURRENT in report.warnings
    assert WARNING_SNAPSHOT_AS_OF_APPROXIMATE in report.warnings


def test_external_fifa_points_production_ready() -> None:
    ready, report = external_fifa_points_production_ready()
    assert ready is True
    assert report.missing == 0


def test_production_snapshot_loads_from_file() -> None:
    snaps = load_external_rating_snapshots()
    key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    assert key in snaps
    assert snaps[key]["rating_type"] == "fifa_ranking_points_current"


def test_resolve_production_vs_historical_snapshot() -> None:
    prod_key, prod_reasons = resolve_production_fifa_snapshot_dataset("Portugal", "DR Congo")
    assert prod_key == config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    assert prod_reasons == []

    hist_key, _ = resolve_historical_fifa_snapshot_dataset("Brazil", "Morocco")
    assert hist_key in ("wc2018", "wc2022", "euro2024", "copa2024")

    live_key, live_reasons = resolve_fifa_snapshot_dataset(
        "Portugal", "DR Congo", for_production=True
    )
    assert live_key == config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    assert live_reasons == []


def test_portugal_dr_congo_no_fallback_when_enabled() -> None:
    dm = LiveDataManager()
    opp = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    home_key, _ = dm.resolve_team("Portugal")
    away_key, _ = dm.resolve_team("DR Congo")
    result = try_apply_active_candidate_powers(
        home_key,
        away_key,
        baseline_home_power=100.0,
        baseline_away_power=90.0,
        baseline_home_elo=1500.0,
        baseline_away_elo=1480.0,
        data_manager=dm,
        force_enable=True,
    )
    assert result.applied is True
    assert result.fallback_reasons == []


def test_missing_production_fifa_points_causes_safe_fallback() -> None:
    dm = LiveDataManager()
    home_key, _ = dm.resolve_team("Brazil")
    away_key, _ = dm.resolve_team("Morocco")
    with patch(
        "core.active_model_activation.resolve_production_fifa_snapshot_dataset",
        return_value=(None, ["fifa_points_missing_for_Brazil"]),
    ):
        result = try_apply_active_candidate_powers(
            home_key,
            away_key,
            baseline_home_power=100.0,
            baseline_away_power=90.0,
            baseline_home_elo=1500.0,
            baseline_away_elo=1480.0,
            data_manager=dm,
            force_enable=True,
        )
    assert result.applied is False
    assert "fifa_points_missing" in result.fallback_reasons[0]


def test_disabled_state_remains_baseline() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r1 = client.post(
        "/api/predict",
        json={"home_team": "Portugal", "away_team": "DR Congo", "neutral_ground": True},
    )
    r2 = client.post(
        "/api/predict",
        json={"home_team": "Portugal", "away_team": "DR Congo", "neutral_ground": True},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    body2 = r2.json()
    assert body1["probabilities_1x2"] == body2["probabilities_1x2"]
    md = body1.get("model_diagnostics") or {}
    assert md.get("activation_enabled") is False


def test_activation_enabled_uses_production_snapshot() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        r = client.post(
            "/api/predict",
            json={"home_team": "Portugal", "away_team": "DR Congo", "neutral_ground": True},
        )
    assert r.status_code == 200
    md = r.json()["model_diagnostics"]
    assert md["activation_enabled"] is True
    assert md["fallback_to_baseline"] is False


def test_sample_production_matchups_have_fifa_points() -> None:
    key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    for home, away in SAMPLE_PRODUCTION_MATCHUPS:
        _, home_ok = get_team_fifa_points(key, home)
        _, away_ok = get_team_fifa_points(key, away)
        assert home_ok, home
        assert away_ok, away


def test_check_activation_readiness_not_ready_when_coverage_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import check_activation_readiness as readiness

    monkeypatch.setattr(
        config,
        "PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE",
        1.01,
    )
    coverage_ok, issues, _info = readiness._check_production_coverage()
    assert coverage_ok is False
    assert any("coverage" in issue.lower() for issue in issues)
    status = readiness.determine_readiness(
        defaults_ok=True,
        winner_ok=True,
        coverage_ok=False,
        coverage_warnings=[],
        gate_ok=True,
        sample_ok=True,
    )
    assert status == readiness.READINESS_NOT_READY


def test_check_activation_readiness_ready_when_coverage_complete() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/check_activation_readiness.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "READY_FOR_LOCAL_ENABLEMENT" in proc.stdout or "READY_WITH_WARNINGS" in proc.stdout


def test_validate_cli_wc2026_current() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/validate_external_rating_snapshots.py",
            "--dataset",
            "wc2026_current",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "wc2026_current" in proc.stdout
    assert "1.00" in proc.stdout or "100" in proc.stdout


def test_activation_dry_run_sample_production_no_fallbacks_when_enabled() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/activation_dry_run.py",
            "--enable-candidate",
            "--sample-production",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0
    assert "fallbacks: 0" in proc.stdout


def test_list_production_teams_count() -> None:
    assert len(list_production_team_names()) == len(FIFA_ELO_2026)


def test_production_keys_frozenset() -> None:
    assert config.PRODUCTION_FIFA_SNAPSHOT_DATASET in PRODUCTION_SNAPSHOT_KEYS
