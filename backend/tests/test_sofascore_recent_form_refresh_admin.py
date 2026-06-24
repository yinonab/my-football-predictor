"""Admin Sofascore recent-form refresh endpoint tests (offline only)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api import main as api_main
from data.football_data import FootballDataClient

ADMIN_TOKEN = "test-warmup-admin-token"
REFRESH_URL = "/api/admin/refresh-sofascore-recent-form"


def _no_football_data() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


@pytest.fixture
def client() -> TestClient:
    api_main._football_data_client = _no_football_data()
    return TestClient(api_main.app)


@pytest.fixture
def admin_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_WARMUP_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(config, "SOFASCORE_ENABLED", True)
    monkeypatch.setenv("SOFASCORE_RAPIDAPI_KEY", "test-sofascore-key")


def _post(client: TestClient, *, token: str | None = ADMIN_TOKEN, use_bearer: bool = True):
    headers: dict[str, str] = {}
    if token is not None:
        if use_bearer:
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["X-Admin-Token"] = token
    return client.post(REFRESH_URL, headers=headers)


def test_refresh_rejects_missing_token(client: TestClient, admin_configured: None) -> None:
    resp = _post(client, token=None)
    assert resp.status_code == 401


def test_refresh_rejects_invalid_token(client: TestClient, admin_configured: None) -> None:
    resp = _post(client, token="wrong-token")
    assert resp.status_code == 403


def test_refresh_accepts_x_admin_token_header(client: TestClient, admin_configured: None) -> None:
    summary = {
        "dry_run": False,
        "cache_written": True,
        "write_status": "ok",
        "cloud_persist_sync_status": "synced",
        "teams_total": 48,
        "teams_refreshed_with_sofascore_id": 48,
        "teams_with_10_plus_last10": 48,
        "teams_with_under_5_last10": 0,
        "sofascore_candidate_rows": 100,
        "finished_rows": 100,
        "rows_with_has_xg": 10,
        "missing_mappings": [],
        "cache_last_updated_utc": "2026-06-24T00:00:00+00:00",
        "errors": [],
        "warnings": [],
    }
    with patch(
        "api.main.run_sofascore_recent_form_refresh",
        return_value=summary,
    ):
        resp = _post(client, use_bearer=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data["teams_refreshed_with_sofascore_id"] == 48
    assert data["cloud_persist_sync_status"] == "synced"


@patch("api.main.config.sofascore_enabled", return_value=False)
def test_refresh_rejects_when_sofascore_disabled(
    _mock_disabled: MagicMock,
    client: TestClient,
    admin_configured: None,
) -> None:
    resp = _post(client)
    assert resp.status_code == 403


def test_refresh_calls_runner_and_returns_summary(client: TestClient, admin_configured: None) -> None:
    summary = {
        "dry_run": False,
        "cache_written": True,
        "write_status": "ok",
        "cloud_persist_sync_status": "synced",
        "teams_total": 48,
        "teams_refreshed_with_sofascore_id": 48,
        "teams_with_10_plus_last10": 48,
        "teams_with_under_5_last10": 0,
        "sofascore_candidate_rows": 1425,
        "finished_rows": 1425,
        "rows_with_has_xg": 207,
        "missing_mappings": [],
        "cache_last_updated_utc": "2026-06-24T12:00:00+00:00",
        "errors": [],
        "warnings": [],
    }
    with patch(
        "api.main.run_sofascore_recent_form_refresh",
        return_value=summary,
    ) as mock_run:
        resp = _post(client)
    assert resp.status_code == 200
    mock_run.assert_called_once_with()
    data = resp.json()
    assert data["sofascore_candidate_rows"] == 1425
    assert data["finished_rows"] == 1425
    assert data["rows_with_has_xg"] == 207


@patch("core.sofascore_recent_form_refresh.push_file", return_value=True)
@patch("core.sofascore_recent_form_refresh.cloud_persist_configured", return_value=True)
@patch("core.sofascore_recent_form_refresh.write_fusion_cache_safe")
@patch("core.sofascore_recent_form_refresh.build_team_fusion")
@patch("core.sofascore_recent_form_refresh.SofascoreClient")
def test_runner_syncs_cloud_persist_after_successful_write(
    _mock_client: MagicMock,
    mock_build: MagicMock,
    mock_write: MagicMock,
    _mock_cloud_cfg: MagicMock,
    mock_push: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from core.recent_form_fusion import TeamFusionResult

    cache_path = tmp_path / "recent_form_fusion_cache.json"
    monkeypatch.setattr("core.sofascore_recent_form_refresh.FUSION_CACHE_PATH", cache_path)
    monkeypatch.setattr("core.recent_form_fusion.FUSION_CACHE_PATH", cache_path)

    team_key = "Brazil (ברזיל)"
    mock_build.return_value = TeamFusionResult(
        team_registry_key=team_key,
        english_name="Brazil",
        candidate_count=10,
        coverage_count=10,
        coverage_quality="high",
        provider_ids={"sofascore": 4748},
        provider_availability={"sofascore": "ok"},
    )
    mock_write.return_value = (cache_path, "ok")
    cache_path.write_text(
        '{"last_updated_utc":"2026-06-24T00:00:00+00:00","teams":{}}',
        encoding="utf-8",
    )

    with patch("core.sofascore_recent_form_refresh.all_wc_registry_keys", return_value=[team_key]):
        with patch("core.sofascore_recent_form_refresh.config.sofascore_enabled", return_value=True):
            from core.sofascore_recent_form_refresh import run_sofascore_recent_form_refresh

            result = run_sofascore_recent_form_refresh(sofascore_sleep=0)

    assert result["cache_written"] is True
    assert result["cloud_persist_sync_status"] == "synced"
    mock_push.assert_called_once_with(cache_path)


@patch("core.sofascore_recent_form_refresh.push_file")
@patch("core.sofascore_recent_form_refresh.cloud_persist_configured", return_value=True)
@patch("core.sofascore_recent_form_refresh.write_fusion_cache_safe", return_value=(None, "rejected"))
@patch("core.sofascore_recent_form_refresh.build_team_fusion")
@patch("core.sofascore_recent_form_refresh.SofascoreClient")
def test_runner_skips_cloud_persist_after_failed_write(
    _mock_client: MagicMock,
    mock_build: MagicMock,
    _mock_write: MagicMock,
    _mock_cloud_cfg: MagicMock,
    mock_push: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.recent_form_fusion import TeamFusionResult

    team_key = "Brazil (ברזיל)"
    mock_build.return_value = TeamFusionResult(
        team_registry_key=team_key,
        english_name="Brazil",
        candidate_count=10,
        coverage_count=10,
        coverage_quality="high",
        provider_ids={"sofascore": 4748},
        provider_availability={"sofascore": "ok"},
    )

    with patch("core.sofascore_recent_form_refresh.all_wc_registry_keys", return_value=[team_key]):
        with patch("core.sofascore_recent_form_refresh.config.sofascore_enabled", return_value=True):
            from core.sofascore_recent_form_refresh import run_sofascore_recent_form_refresh

            result = run_sofascore_recent_form_refresh(sofascore_sleep=0)

    assert result["cache_written"] is False
    assert result["cloud_persist_sync_status"] == "not_attempted_write_failed"
    mock_push.assert_not_called()


def test_api_main_does_not_import_sofascore_live_client() -> None:
    import api.main as api_main

    source = open(api_main.__file__, encoding="utf-8").read()
    assert "data.sofascore" not in source


def test_github_workflow_uses_admin_token_secret_only() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "refresh-sofascore-recent-form.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "schedule:" in text
    assert "secrets.RECENT_FORM_WARMUP_ADMIN_TOKEN" in text
    assert "SOFASCORE_RAPIDAPI_KEY" not in text
    assert "/api/admin/refresh-sofascore-recent-form" in text


def test_extract_admin_token_bearer_and_header() -> None:
    from core.recent_form_warmup import extract_admin_token

    assert extract_admin_token(authorization="Bearer abc123") == "abc123"
    assert extract_admin_token(x_admin_token="xyz") == "xyz"
    assert extract_admin_token(authorization="Bearer abc", x_admin_token="xyz") == "xyz"
    assert extract_admin_token() is None
