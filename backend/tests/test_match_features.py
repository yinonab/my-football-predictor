"""Tests for Phase 4B unified MatchFeatures skeleton."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api.main import app
from core.match_features import MatchFeatures, build_match_features
from data.database import FIFA_ELO_2026, LiveDataManager
from fastapi.testclient import TestClient

client = TestClient(app)

PARITY_MATCHUPS = [
    ("Brazil", "Morocco"),
    ("Germany", "Haiti"),
    ("Argentina", "France"),
    ("Portugal", "DR Congo"),
]


@pytest.fixture
def data_manager() -> LiveDataManager:
    return LiveDataManager()


def _manual_team_snapshot(
    data_manager: LiveDataManager,
    home_input: str,
    away_input: str,
    *,
    use_live: bool = False,
) -> tuple[str, str, dict, dict]:
    home_resolved, _ = data_manager.resolve_team(home_input)
    away_resolved, _ = data_manager.resolve_team(away_input)
    home_data = data_manager.get_team_data(home_resolved, use_live=use_live)
    away_data = data_manager.get_team_data(away_resolved, use_live=use_live)
    return home_resolved, away_resolved, home_data, away_data


def test_build_match_features_brazil_morocco(data_manager: LiveDataManager) -> None:
    features = build_match_features(
        home_team="Brazil",
        away_team="Morocco",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    assert features.home_team == "Brazil"
    assert features.away_team == "Morocco"
    assert "Brazil" in features.resolved_home_team
    assert "Morocco" in features.resolved_away_team


def test_resolved_names_match_data_manager(data_manager: LiveDataManager) -> None:
    for home, away in PARITY_MATCHUPS:
        features = build_match_features(
            home_team=home,
            away_team=away,
            neutral_ground=True,
            use_live_stats=False,
            data_manager=data_manager,
        )
        home_resolved, away_resolved, _, _ = _manual_team_snapshot(
            data_manager, home, away
        )
        assert features.resolved_home_team == home_resolved
        assert features.resolved_away_team == away_resolved


def test_rating_fields_match_team_data(data_manager: LiveDataManager) -> None:
    for home, away in PARITY_MATCHUPS:
        features = build_match_features(
            home_team=home,
            away_team=away,
            neutral_ground=True,
            use_live_stats=False,
            data_manager=data_manager,
        )
        _, _, home_data, away_data = _manual_team_snapshot(data_manager, home, away)
        assert features.home_internal_elo == float(home_data["elo"])
        assert features.away_internal_elo == float(away_data["elo"])
        assert features.home_attack_strength == float(home_data["attack"])
        assert features.away_attack_strength == float(away_data["attack"])
        assert features.home_defense_strength == float(home_data["defense"])
        assert features.away_defense_strength == float(away_data["defense"])
        assert features.home_raw_form == float(home_data["form"])
        assert features.away_raw_form == float(away_data["form"])


def test_fifa_points_populated_when_available(data_manager: LiveDataManager) -> None:
    features = build_match_features(
        home_team="Brazil",
        away_team="Morocco",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    assert features.home_fifa_points == float(
        FIFA_ELO_2026[features.resolved_home_team]
    )
    assert features.away_fifa_points == float(
        FIFA_ELO_2026[features.resolved_away_team]
    )
    assert features.external_rating_gap is not None
    assert features.external_rating_gap >= 0.0


def test_future_fields_none_or_empty(data_manager: LiveDataManager) -> None:
    features = build_match_features(
        home_team="Germany",
        away_team="Haiti",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    assert features.rating_disagreement is None
    assert features.h2h_signal is None
    assert features.context_signal is None
    assert features.rest_days is None
    assert features.weather_signal is None
    assert features.tournament_stage is None
    assert features.must_win_context is None
    assert features.odds_market_signal is None
    assert features.warnings == []


def test_data_quality_flags_default_structure(data_manager: LiveDataManager) -> None:
    features = build_match_features(
        home_team="Argentina",
        away_team="France",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    assert isinstance(features.data_quality_flags, list)
    assert isinstance(features.warnings, list)


def test_build_match_features_no_odds_dependency(
    data_manager: LiveDataManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_odds(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("odds should not be fetched in build_match_features")

    monkeypatch.setattr("core.odds_ensemble.OddsClient.fetch_match_odds", _fail_odds)
    build_match_features(
        home_team="Spain",
        away_team="Cape Verde",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )


def test_build_match_features_does_not_mutate_manager_data(
    data_manager: LiveDataManager,
) -> None:
    before_home = copy.deepcopy(
        data_manager.get_team_data("Brazil", use_live=False)
    )
    features = build_match_features(
        home_team="Brazil",
        away_team="Morocco",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    features.home_team_data["elo"] = -999.0
    after_home = data_manager.get_team_data("Brazil", use_live=False)
    assert after_home["elo"] == before_home["elo"]


def test_to_debug_dict_roundtrip_keys(data_manager: LiveDataManager) -> None:
    features = build_match_features(
        home_team="Portugal",
        away_team="DR Congo",
        neutral_ground=True,
        use_live_stats=False,
        data_manager=data_manager,
    )
    debug = features.to_debug_dict()
    assert debug["home_team"] == "Portugal"
    assert debug["resolved_away_team"] == features.resolved_away_team
    assert "home_team_data" in debug


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_response_backward_compatible(home: str, away: str) -> None:
    response = client.post(
        "/api/predict",
        json={"home_team": home, "away_team": away, "neutral_ground": True},
    )
    assert response.status_code == 200
    data = response.json()
    total = (
        data["probabilities_1x2"]["home_win"]
        + data["probabilities_1x2"]["draw"]
        + data["probabilities_1x2"]["away_win"]
    )
    assert 99.5 <= total <= 100.2
    assert data["home_xg"] > 0
    assert data["away_xg"] > 0
    assert len(data["top_scores"]) >= 1
    assert "model_diagnostics" in data
    assert "global_rating_diagnostics" in data


@pytest.mark.parametrize("home,away", PARITY_MATCHUPS)
def test_predict_probabilities_stable_across_calls(home: str, away: str) -> None:
    payload = {"home_team": home, "away_team": away, "neutral_ground": True}
    first = client.post("/api/predict", json=payload).json()
    second = client.post("/api/predict", json=payload).json()
    for key in ("home_win", "draw", "away_win"):
        assert first["probabilities_1x2"][key] == second["probabilities_1x2"][key]
    assert first["home_xg"] == second["home_xg"]
    assert first["away_xg"] == second["away_xg"]
    assert first["home_power"] == second["home_power"]
    assert first["away_power"] == second["away_power"]
    assert first["model_diagnostics"] == second["model_diagnostics"]
    for i, score in enumerate(first["top_scores"]):
        assert score["score"] == second["top_scores"][i]["score"]
        assert score["probability"] == second["top_scores"][i]["probability"]
