"""API integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_teams() -> None:
    response = client.get("/api/teams")
    assert response.status_code == 200
    teams = response.json()["teams"]
    assert len(teams) == 48
    assert "Canada (קנדה)" in teams


def test_predict_valid_match() -> None:
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Canada (קנדה)",
            "away_team": "Bosnia (בוסניה)",
            "neutral_ground": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    total = (
        data["probabilities_1x2"]["home_win"]
        + data["probabilities_1x2"]["draw"]
        + data["probabilities_1x2"]["away_win"]
    )
    assert 99.9 <= total <= 100.1


def test_predict_custom_team_name() -> None:
    response = client.post(
        "/api/predict",
        json={
            "home_team": "ארגנטינה",
            "away_team": "צרפת",
            "neutral_ground": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    total = (
        data["probabilities_1x2"]["home_win"]
        + data["probabilities_1x2"]["draw"]
        + data["probabilities_1x2"]["away_win"]
    )
    assert 99.9 <= total <= 100.1


def test_predict_hebrew_australia_turkey() -> None:
    response = client.post(
        "/api/predict",
        json={
            "home_team": "אוסטרליה",
            "away_team": "טורקיה",
            "neutral_ground": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    total = (
        data["probabilities_1x2"]["home_win"]
        + data["probabilities_1x2"]["draw"]
        + data["probabilities_1x2"]["away_win"]
    )
    assert 99.9 <= total <= 100.1
    assert data["home_team"] == "אוסטרליה"
    assert data["away_team"] == "טורקיה"
    assert data["away_power"] > data["home_power"]  # Turkey Elo 1635 > Australia 1595


def test_predict_unknown_team_uses_fallback() -> None:
    response = client.post(
        "/api/predict",
        json={
            "home_team": "נבחרת שלא קיימת",
            "away_team": "Canada (קנדה)",
            "neutral_ground": True,
        },
    )
    assert response.status_code == 200
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Canada (קנדה)",
            "away_team": "Canada (קנדה)",
        },
    )
    assert response.status_code == 400


def test_groups_endpoint() -> None:
    response = client.get("/api/groups")
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 12
    assert len(groups["J"]) == 4


def test_predict_returns_top3_and_coverage() -> None:
    response = client.post(
        "/api/predict",
        json={
            "home_team": "Argentina (ארגנטינה)",
            "away_team": "France (צרפת)",
            "top_n": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["top_scores"]) == 3
    assert len(data["score_coverage"]["scores"]) >= 1
    assert data["home_breakdown"]["group"] == "J"
    assert data["away_breakdown"]["group"] == "I"
    assert data["top_scores"][0]["explanation"]
    assert data["outcome_explanations"]["draw"]
    assert data["match_summary"]
    assert "h2h_summary" in data


def test_elo_update_endpoint(tmp_path, monkeypatch) -> None:
    from core import match_store

    monkeypatch.setattr(match_store, "LIVE_MATCHES_PATH", tmp_path / "live.json")

    response = client.post(
        "/api/elo/update",
        json={
            "home_team": "Haiti (האיטי)",
            "away_team": "Curacao (קוראסאו)",
            "home_goals": 2,
            "away_goals": 1,
            "record_match": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["home_elo_after"] != data["home_elo_before"]
    assert data["match_recorded"] is True
    assert data["ratings_rebuilt"] is True
    assert data["live_match_count"] >= 1


def test_refresh_history_without_api_key() -> None:
    response = client.post("/api/admin/refresh-history")
    assert response.status_code == 400


def test_simulate_group() -> None:
    response = client.post(
        "/api/simulate/group",
        json={"group": "C", "iterations": 100},
    )
    assert response.status_code == 200
    standings = response.json()["standings"]
    assert len(standings) == 4


def test_simulate_champion() -> None:
    response = client.post(
        "/api/simulate/champion",
        json={"iterations": 200},
    )
    assert response.status_code == 200
    odds = response.json()["champion_odds"]
    assert len(odds) >= 5
