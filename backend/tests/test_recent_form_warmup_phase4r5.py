"""Phase 4R.5 — Admin-only recent-form fusion warmup endpoint tests (offline only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api import main as api_main
from core.api_football_recent_form import APIF_ACCOUNT_SUSPENDED, ApiFootballRequestError
from core.fixture_state import MATCH_ALREADY_COMPLETED
from core.fixture_state_resolver import FixtureStateResolver
from core.recent_form_fusion import (
    FUSION_CACHE_PATH,
    TeamFusionResult,
    load_fusion_cache,
    write_fusion_cache_safe,
)
from core.recent_form_warmup import RequestBudget, run_recent_form_warmup
from data.football_data import FootballDataClient

HAITI_REGISTRY = "Haiti (האיטי)"
ADMIN_TOKEN = "test-warmup-admin-token"


def _no_football_data() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


@pytest.fixture(autouse=True)
def restore_fixture_resolver():
    original = api_main._fixture_state_resolver
    yield
    api_main._fixture_state_resolver = original


@pytest.fixture
def client() -> TestClient:
    api_main._football_data_client = _no_football_data()
    return TestClient(api_main.app)


@pytest.fixture
def warmup_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_MAX_TEAMS", 3)
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_SLEEP_SECONDS", 0.0)


@pytest.fixture
def cache_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "recent_form_fusion_cache.json"
    monkeypatch.setattr("core.recent_form_fusion.FUSION_CACHE_PATH", path)
    monkeypatch.setattr("core.recent_form_warmup.FUSION_CACHE_PATH", path)
    return path


def _fusion_result(
    team_key: str = HAITI_REGISTRY,
    *,
    coverage_count: int = 7,
    quality: str = "medium",
) -> TeamFusionResult:
    return TeamFusionResult(
        team_registry_key=team_key,
        english_name=team_key.split(" (")[0],
        coverage_count=coverage_count,
        coverage_quality=quality,  # type: ignore[arg-type]
        source_mix={"api_football_recent_form": coverage_count},
        last_10_finished=[{"date": "2025-01-01"}] * min(coverage_count, 10),
    )


def _fresh_cache_payload(team_key: str = HAITI_REGISTRY) -> dict:
    result = _fusion_result(team_key, coverage_count=8, quality="high")
    return {
        "schema_version": 1,
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "teams": {team_key: result.to_cache_entry()},
    }


def _warmup_post(client: TestClient, body: dict, token: str | None = ADMIN_TOKEN):
    headers = {"X-Admin-Token": token} if token is not None else {}
    return client.post("/api/recent-form/warmup", json=body, headers=headers)


def test_warmup_rejects_missing_admin_token(client: TestClient, warmup_enabled: None) -> None:
    resp = _warmup_post(client, {"teams": ["Haiti"]}, token=None)
    assert resp.status_code == 401


def test_warmup_rejects_invalid_admin_token(client: TestClient, warmup_enabled: None) -> None:
    resp = _warmup_post(client, {"teams": ["Haiti"]}, token="wrong-token")
    assert resp.status_code == 403


def test_warmup_rejects_too_many_teams(client: TestClient, warmup_enabled: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_MAX_TEAMS", 2)
    resp = _warmup_post(
        client,
        {"teams": ["Haiti", "Brazil", "New Zealand"]},
    )
    assert resp.status_code == 400
    assert "TOO_MANY_TEAMS" in resp.json()["detail"]


def test_warmup_skips_fresh_cache_when_force_false(
    cache_path: Path,
    warmup_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fresh_cache_payload()
    write_fusion_cache_safe(payload, force=True)

    with patch("core.recent_form_warmup.build_team_fusion") as mock_build:
        result = run_recent_form_warmup(teams=["Haiti"], force=False, dry_run=True)
        mock_build.assert_not_called()

    assert result["skipped_teams"] == ["Haiti"]
    assert result["teams"]["Haiti"]["status"] == "skipped_fresh"
    assert result["refreshed_teams"] == []


def test_warmup_refreshes_stale_team_when_provider_mocked_ok(
    cache_path: Path,
    warmup_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _fresh_cache_payload()
    stale["last_updated_utc"] = "2020-01-01T00:00:00+00:00"
    write_fusion_cache_safe(stale, force=True)

    refreshed = _fusion_result(coverage_count=8, quality="medium")

    with patch("core.recent_form_warmup.build_team_fusion", return_value=refreshed):
        with patch("core.recent_form_warmup.discover_football_data_team_ids", return_value=({}, [], [])):
            with patch("core.recent_form_warmup.config.api_football_recent_form_enabled", return_value=False):
                with patch("core.recent_form_warmup.config.recent_form_api_enabled", return_value=False):
                    result = run_recent_form_warmup(teams=["Haiti"], force=False, dry_run=False)

    assert "Haiti" in result["refreshed_teams"]
    assert result["teams"]["Haiti"]["status"] == "refreshed"
    assert result["teams"]["Haiti"]["matches_after"] == 8
    assert result["cache_written"] is True
    loaded, err = load_fusion_cache(cache_path)
    assert err is None
    assert loaded is not None
    assert loaded["teams"][HAITI_REGISTRY]["fusion"]["coverage_count"] == 8


def test_warmup_stops_on_account_suspended_preserves_cache(
    cache_path: Path,
    warmup_enabled: None,
) -> None:
    prior = _fusion_result(coverage_count=5, quality="low")
    payload = {
        "schema_version": 1,
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "teams": {HAITI_REGISTRY: prior.to_cache_entry()},
    }
    write_fusion_cache_safe(payload, force=True)

    empty = _fusion_result(coverage_count=0, quality="unavailable")

    def _build_with_suspend(team_key, *, apif_client=None, **kwargs):
        if apif_client is not None:
            apif_client.stop_reason = APIF_ACCOUNT_SUSPENDED
            apif_client.last_error = ApiFootballRequestError(APIF_ACCOUNT_SUSPENDED, "account suspended")
        return empty

    with patch("core.recent_form_warmup.config.api_football_recent_form_enabled", return_value=True):
        with patch("core.recent_form_warmup.build_team_fusion", side_effect=_build_with_suspend):
            with patch("core.recent_form_warmup.discover_football_data_team_ids", return_value=({}, [], [])):
                with patch("core.recent_form_warmup.config.recent_form_api_enabled", return_value=False):
                    result = run_recent_form_warmup(teams=["Haiti"], force=True, dry_run=False)

    assert result["provider_status"]["api_football"] == "suspended"
    team = result["teams"]["Haiti"]
    assert team["status"] in {"partial", "failed"}
    assert team["matches_after"] >= 5
    loaded, _ = load_fusion_cache(cache_path)
    assert loaded is not None
    assert loaded["teams"][HAITI_REGISTRY]["fusion"]["coverage_count"] == 5


def test_warmup_respects_max_requests_budget(warmup_enabled: None) -> None:
    budget = RequestBudget(max_requests=1)
    assert budget.consume(1) is True
    assert budget.consume(1) is False
    assert budget.stopped_due_to_budget is True

    exhausted = RequestBudget(max_requests=2)
    exhausted.used = 2
    exhausted.stopped_due_to_budget = True

    with patch("core.recent_form_warmup.RequestBudget", return_value=exhausted):
        with patch("core.recent_form_warmup.config.api_football_recent_form_enabled", return_value=True):
            with patch("core.recent_form_warmup.discover_football_data_team_ids", return_value=({}, [], [])):
                with patch("core.recent_form_warmup.config.recent_form_api_enabled", return_value=False):
                    result = run_recent_form_warmup(
                        teams=["Haiti"],
                        force=True,
                        dry_run=True,
                        max_requests=2,
                    )

    assert result["request_budget"]["stopped_due_to_budget"] is True
    assert result["teams"]["Haiti"]["status"] == "failed"
    assert "WARMUP_BUDGET_EXHAUSTED" in result["teams"]["Haiti"]["reason_codes"]


def test_status_endpoint_does_not_call_external_apis(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("external API call from status endpoint")

    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)
    resp = client.get("/api/recent-form/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "cache_exists" in data
    assert "flags" in data
    assert "RECENT_FORM_WARMUP_ENABLED" in data["flags"]


def test_team_endpoint_does_not_call_external_apis(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("external API call from team endpoint")

    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)
    resp = client.get("/api/recent-form/team/Haiti")
    assert resp.status_code == 200
    data = resp.json()
    assert data["team"] == "Haiti"
    assert "coverage_quality" in data


def test_predict_does_not_call_external_apis_for_recent_form(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("live external API call attempted from /api/predict")

    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)

    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    assert "probabilities_1x2" in data


def test_completed_match_behavior_unchanged(client: TestClient, tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "home_team": "Canada",
                        "away_team": "Qatar",
                        "fixture_status": "completed",
                        "actual_home_goals": 6,
                        "actual_away_goals": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False),
        overrides_path=overrides,
        football_data=_no_football_data(),
    )
    data = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    ).json()
    assert data["match_context_diagnostics"]["prediction_valid"] is False
    assert MATCH_ALREADY_COMPLETED in data["match_context_diagnostics"]["warnings"]


def test_shadow_diagnostics_still_present(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    sd = data["scoreline_decision"]
    assert "recent_form_shadow" in sd
    rf = sd["recent_form_shadow"]
    assert rf.get("enabled") is True
    assert "current_gate_level" in rf
    assert "shadow_gate_level" in rf


def test_warmup_works_without_local_gitignored_cache(
    cache_path: Path,
    warmup_enabled: None,
) -> None:
    assert not cache_path.exists()
    refreshed = _fusion_result(coverage_count=6, quality="medium")
    with patch("core.recent_form_warmup.build_team_fusion", return_value=refreshed):
        with patch("core.recent_form_warmup.discover_football_data_team_ids", return_value=({}, [], [])):
            with patch("core.recent_form_warmup.config.api_football_recent_form_enabled", return_value=False):
                with patch("core.recent_form_warmup.config.recent_form_api_enabled", return_value=False):
                    result = run_recent_form_warmup(teams=["Haiti"], force=True, dry_run=False)
    assert result["cache_written"] is True
    assert cache_path.exists()
