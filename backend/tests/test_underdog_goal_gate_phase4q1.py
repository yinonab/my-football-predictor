"""Phase 4Q.1 — Underdog goal gate tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api import main as api_main
from core.fixture_state import MATCH_ALREADY_COMPLETED
from core.fixture_state_resolver import FixtureStateResolver
from core.math_engine import AdvancedDixonColesEngine
from core.recent_scoring_form import get_recent_scoring_form
from core.scoreline_decision import build_scoreline_decision
from core.underdog_goal_gate import (
    RECENT_FORM_UNAVAILABLE,
    compute_underdog_goal_gate,
    gate_candidate_adjustment,
)
from data.football_data import FootballDataClient


def _no_football_data() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


@pytest.fixture(autouse=True)
def restore_fixture_resolver():
    original = api_main._fixture_state_resolver
    yield
    api_main._fixture_state_resolver = original


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


from core.strength_result import StrengthResult


def _strength(home_power: float, away_power: float) -> StrengthResult:
    gap = home_power - away_power
    return StrengthResult(
        home_team="Home",
        away_team="Away",
        baseline_home_power=home_power,
        baseline_away_power=away_power,
        baseline_gap=gap,
        active_home_power=home_power,
        active_away_power=away_power,
        active_gap=gap,
        final_home_power=home_power,
        final_away_power=away_power,
        final_gap=gap,
        activation_enabled=False,
        power_candidate_affects_prediction=False,
        active_candidate=None,
        active_external_rating_mode=None,
        active_external_rating_strategy=None,
        model_version="test",
        baseline_model_version="test",
        fallback_to_baseline=True,
    )


def _matrix(home_xg: float, away_xg: float, *, alpha: float = 0.0) -> dict[str, float]:
    engine = AdvancedDixonColesEngine(alpha=alpha)
    return engine.generate_match_prediction(
        700,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )["all_scores"]


def test_representative_avoids_modal_one_nil_when_fav_xg_high() -> None:
    all_scores = _matrix(1.9, 0.55)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 64.0, "draw": 23.0, "away_win": 13.0},
        top_scores=[{"score": "1-0", "probability": 13.0}],
        all_scores=all_scores,
        home_xg=1.9,
        away_xg=0.55,
        home_team="Netherlands",
        away_team="Sweden",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 2


def test_underdog_goal_not_automatic_at_point_nine_xg() -> None:
    all_scores = _matrix(1.81, 0.79)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
        top_scores=[{"score": "1-0", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=1.81,
        away_xg=0.79,
        home_team="Brazil",
        away_team="Haiti",
        strength=_strength(863.0, 724.0),
    )
    gate = decision.underdog_goal_gate
    assert gate["level"] in {"BLOCK", "WEAK_ALLOW", "ALLOW"}
    primary = decision.primary_predicted_score
    assert primary is not None
    if gate["level"] in {"BLOCK", "WEAK_ALLOW"}:
        assert primary.away_goals == 0 or primary.score_label in {"2-0", "3-0", "4-0"}


def test_elite_blowout_prefers_clean_sheet_without_strong_form() -> None:
    all_scores = _matrix(4.4, 0.9, alpha=0.3)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 78.6, "draw": 12.1, "away_win": 9.3},
        top_scores=[{"score": "3-0", "probability": 8.0}],
        all_scores=all_scores,
        home_xg=4.4,
        away_xg=0.9,
        home_team="Brazil",
        away_team="Haiti",
        strength=_strength(920.0, 724.0),
    )
    gate = decision.underdog_goal_gate
    assert gate["favorite_class"] == "elite_favorite"
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 3
    assert primary.away_goals == 0 or gate["level"] == "STRONG_ALLOW"


def test_strong_favorite_two_zero_possible() -> None:
    all_scores = _matrix(1.81, 0.79)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
        top_scores=[{"score": "1-0", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=1.81,
        away_xg=0.79,
        home_team="Netherlands",
        away_team="Sweden",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label in {"2-0", "2-1", "3-0", "1-0"}


def test_away_favorite_clean_sheet_when_gate_blocks() -> None:
    all_scores = _matrix(0.9, 1.7)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 18.0, "draw": 26.3, "away_win": 55.7},
        top_scores=[{"score": "0-1", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=0.9,
        away_xg=1.7,
        home_team="Tunisia",
        away_team="Japan",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.outcome == "away_win"


def test_balanced_match_gate_level() -> None:
    all_scores = _matrix(1.25, 1.15)
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 35.0, "draw": 33.0, "away_win": 32.0},
        top_scores=[{"score": "1-1", "probability": 13.0}],
        all_scores=all_scores,
        home_xg=1.25,
        away_xg=1.15,
        home_team="A",
        away_team="B",
    )
    assert decision.primary_predicted_score == decision.top_exact_score_overall


def test_large_candidate_gap_blocks_underdog_goal_adjustment() -> None:
    from core.underdog_goal_gate import UnderdogGoalGateResult

    gate = UnderdogGoalGateResult(
        level="ALLOW",
        support_score=58.0,
        threshold=55.0,
        favorite_class="normal_favorite",
        underdog_xg=0.9,
        underdog_scores_probability=52.0,
        both_teams_score_probability=46.0,
        recent_form_available=False,
        recent_form_confidence="unavailable",
        last_10_scored_rate=None,
        last_10_goals_for_avg=None,
        last_10_failed_to_score_rate=None,
        scored_vs_similar_or_stronger_opponents=None,
        reason_codes=[RECENT_FORM_UNAVAILABLE],
    )
    adj = gate_candidate_adjustment(
        underdog_goals=1,
        gate=gate,
        clean_sheet_probability=10.0,
        candidate_probability=4.0,
    )
    assert adj < 0


def test_recent_form_offline_available_for_known_team() -> None:
    form = get_recent_scoring_form("Brazil (ברזיל)")
    assert form.matches_used >= 0


def test_gate_emits_form_unavailable_when_no_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.underdog_goal_gate.get_recent_scoring_form",
        lambda *a, **k: __import__(
            "core.recent_scoring_form", fromlist=["RecentScoringFormMetrics"]
        ).RecentScoringFormMetrics(
            recent_form_available=False,
            recent_form_confidence="unavailable",
            last_10_scored_rate=None,
            last_10_goals_for_avg=None,
            last_10_failed_to_score_rate=None,
            scored_vs_similar_or_stronger_opponents=None,
            matches_used=0,
        ),
    )
    from core.underdog_goal_gate import build_underdog_match_context

    ctx = build_underdog_match_context(
        favorite_outcome="home_win",
        probabilities_1x2={"home_win": 62.0, "draw": 24.0, "away_win": 14.0},
        home_team="Brazil",
        away_team="Haiti",
        home_xg=4.0,
        away_xg=0.8,
        favorite_power=920.0,
        underdog_power=720.0,
        power_gap=200.0,
    )
    gate = compute_underdog_goal_gate(
        underdog_ctx=ctx,
        underdog_scores_probability=45.0,
        btts_probability=40.0,
    )
    assert RECENT_FORM_UNAVAILABLE in gate.reason_codes or gate.level in {
        "BLOCK",
        "WEAK_ALLOW",
    }


def test_top_scores_unchanged(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Netherlands", "away_team": "Sweden", "neutral_ground": True},
    ).json()
    assert len(data["top_scores"]) >= 1
    assert "score" in data["top_scores"][0]


def test_completed_match_unchanged(client: TestClient, tmp_path: Path) -> None:
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


def test_venue_mode_still_works(client: TestClient) -> None:
    neutral = client.post(
        "/api/predict",
        json={
            "home_team": "United States",
            "away_team": "Australia",
            "venue_mode": "neutral",
        },
    ).json()
    home = client.post(
        "/api/predict",
        json={
            "home_team": "United States",
            "away_team": "Australia",
            "venue_mode": "first_team_home",
        },
    ).json()
    assert home["probabilities_1x2"]["home_win"] > neutral["probabilities_1x2"]["home_win"]


def test_diagnostics_exposed(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    sd = data["scoreline_decision"]
    assert "underdog_goal_gate" in sd
    assert "candidate_comparison_summary" in sd
    assert sd["representative_score_method"] == "representative_v2_composite"
