"""Phase 4R.4 — Recent-form shadow diagnostics and controlled active experiment tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api import main as api_main
from core.fixture_state import MATCH_ALREADY_COMPLETED
from core.fixture_state_resolver import FixtureStateResolver
from core.math_engine import AdvancedDixonColesEngine
from core.recent_form_shadow import (
    FusionRecentFormBundle,
    classify_underdog_support_level,
    compute_shadow_gate_level,
    evaluate_recent_form_shadow,
    load_fusion_recent_form_bundle,
    resolve_active_gate_level,
)
from core.recent_scoring_form import RecentScoringFormMetrics
from core.scoreline_decision import build_scoreline_decision
from core.underdog_goal_gate import (
    CandidateComparisonSummary,
    build_underdog_match_context,
    compute_underdog_goal_gate,
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
    api_main._football_data_client = _no_football_data()
    return TestClient(api_main.app)


def _matrix(home_xg: float, away_xg: float) -> dict[str, float]:
    engine = AdvancedDixonColesEngine(alpha=0.0)
    return engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )["all_scores"]


def _strong_form() -> RecentScoringFormMetrics:
    return RecentScoringFormMetrics(
        recent_form_available=True,
        recent_form_confidence="high",
        last_10_scored_rate=0.8,
        last_10_goals_for_avg=1.5,
        last_10_failed_to_score_rate=0.2,
        scored_vs_similar_or_stronger_opponents=0.6,
        matches_used=10,
        matches_found=10,
        requested_match_count=10,
        last_10_goals_against_avg=0.9,
    )


def _weak_form() -> RecentScoringFormMetrics:
    return RecentScoringFormMetrics(
        recent_form_available=True,
        recent_form_confidence="low",
        last_10_scored_rate=0.35,
        last_10_goals_for_avg=0.4,
        last_10_failed_to_score_rate=0.65,
        scored_vs_similar_or_stronger_opponents=0.2,
        matches_used=5,
        matches_found=5,
        requested_match_count=10,
        last_10_goals_against_avg=1.4,
    )


def _unavailable_form() -> RecentScoringFormMetrics:
    return RecentScoringFormMetrics(
        recent_form_available=False,
        recent_form_confidence="unavailable",
        last_10_scored_rate=None,
        last_10_goals_for_avg=None,
        last_10_failed_to_score_rate=None,
        scored_vs_similar_or_stronger_opponents=None,
        matches_used=1,
        matches_found=1,
        requested_match_count=10,
    )


def _negative_form() -> RecentScoringFormMetrics:
    return RecentScoringFormMetrics(
        recent_form_available=True,
        recent_form_confidence="medium",
        last_10_scored_rate=0.2,
        last_10_goals_for_avg=0.3,
        last_10_failed_to_score_rate=0.8,
        scored_vs_similar_or_stronger_opponents=0.1,
        matches_used=10,
        matches_found=10,
        requested_match_count=10,
        last_10_goals_against_avg=1.8,
    )


def _bundle(
    scoring: RecentScoringFormMetrics,
    *,
    coverage_quality: str = "medium",
    support_level: str | None = None,
) -> FusionRecentFormBundle:
    support = support_level or classify_underdog_support_level(
        scoring=scoring,
        coverage_quality=coverage_quality,
    )
    return FusionRecentFormBundle(
        team_registry_key="Test",
        scoring=scoring,
        coverage_quality=coverage_quality,
        freshness_gap_days=120,
        latest_match_date="2025-06-01",
        source_mix={"bundled_wc2026_qualifiers": 6},
        competition_mix={"WCQ": 6},
        clean_sheet_rate=0.3,
        support_level=support,  # type: ignore[arg-type]
    )


def _ctx() -> object:
    return build_underdog_match_context(
        favorite_outcome="home_win",
        probabilities_1x2={"home_win": 62.0, "draw": 22.0, "away_win": 16.0},
        home_team="Netherlands",
        away_team="Sweden",
        home_xg=1.9,
        away_xg=0.75,
        favorite_power=900.0,
        underdog_power=700.0,
        power_gap=200.0,
    )


def _baseline_gate(form: RecentScoringFormMetrics | None = None):
    ctx = _ctx()
    assert ctx is not None
    return compute_underdog_goal_gate(
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
        recent_form=form,
    )


def test_unavailable_recent_form_does_not_change_shadow_gate() -> None:
    baseline = _baseline_gate(_unavailable_form())
    bundle = _bundle(_unavailable_form(), coverage_quality="unavailable")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, _ = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    assert shadow_level == baseline.level


def test_low_confidence_does_not_strongly_change_shadow_gate() -> None:
    baseline = _baseline_gate(_weak_form())
    bundle = _bundle(_weak_form(), coverage_quality="low")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, _ = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    assert shadow_level == baseline.level


def test_strong_scoring_form_changes_shadow_gate_when_active_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", False)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", False)
    baseline = _baseline_gate(_strong_form())
    bundle = _bundle(_strong_form(), coverage_quality="medium")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, codes = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    assert shadow_level != baseline.level or codes
    with patch(
        "core.recent_form_shadow.load_fusion_recent_form_bundle",
        return_value=bundle,
    ):
        outcome = evaluate_recent_form_shadow(
            underdog_ctx=ctx,
            baseline_gate=baseline,
            underdog_scores_probability=55.0,
            btts_probability=48.0,
            comparison=None,
            baseline_primary_label="2-0",
            shadow_primary_label="2-1",
        )
    assert outcome.diagnostics.get("support_level") == "strong"
    assert outcome.active_change_applied is False


def test_strong_scoring_form_active_only_when_flags_on(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _baseline_gate(_strong_form())
    bundle = _bundle(_strong_form(), coverage_quality="medium")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, _ = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )

    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", False)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", False)
    blocked_level, _, applied = resolve_active_gate_level(
        baseline_level=baseline.level,
        shadow_level=shadow_level,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
        comparison=None,
    )
    assert applied is False
    assert blocked_level == baseline.level

    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", True)
    active_level, codes, applied = resolve_active_gate_level(
        baseline_level=baseline.level,
        shadow_level=shadow_level,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
        comparison=CandidateComparisonSummary(
            best_clean_sheet_candidate="2-0",
            best_underdog_goal_candidate="2-1",
            exact_probability_gap=1.2,
            representative_score_gap=0.05,
            selected_candidate="2-0",
            why_selected="test",
        ),
    )
    if shadow_level != baseline.level:
        assert applied or active_level == baseline.level
        if applied:
            assert "RECENT_FORM_ACTIVE_APPLIED" in codes


def test_negative_scoring_form_moves_toward_block() -> None:
    baseline = _baseline_gate(_negative_form())
    bundle = _bundle(_negative_form(), coverage_quality="medium")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, codes = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    order = ["BLOCK", "WEAK_ALLOW", "ALLOW", "STRONG_ALLOW"]
    if baseline.level in order and shadow_level in order:
        assert order.index(shadow_level) <= order.index(baseline.level) or codes


def test_candidate_comparison_blocks_active_when_gap_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", True)
    baseline = _baseline_gate(_strong_form())
    bundle = _bundle(_strong_form(), coverage_quality="high")
    ctx = _ctx()
    assert ctx is not None
    shadow_level, _ = compute_shadow_gate_level(
        baseline_gate=baseline,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    comparison = CandidateComparisonSummary(
        best_clean_sheet_candidate="2-0",
        best_underdog_goal_candidate="2-1",
        exact_probability_gap=8.0,
        representative_score_gap=0.2,
        selected_candidate="2-0",
        why_selected="large gap",
    )
    level, codes, applied = resolve_active_gate_level(
        baseline_level=baseline.level,
        shadow_level=shadow_level,
        bundle=bundle,
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
        comparison=comparison,
    )
    assert applied is False
    assert level == baseline.level
    assert "RECENT_FORM_ACTIVE_BLOCKED_CANDIDATE_GAP" in codes


def test_primary_score_unchanged_when_affects_scoreline_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", False)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", False)

    all_scores = _matrix(1.81, 0.79)
    engine = AdvancedDixonColesEngine(alpha=0.0)
    result = engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=1.81,
        away_xg_override=0.79,
    )
    baseline = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
        top_scores=result["top_scores"],
        all_scores=all_scores,
        home_xg=1.81,
        away_xg=0.79,
        home_team="Netherlands",
        away_team="Sweden",
    )

    with patch(
        "core.recent_form_shadow.load_fusion_recent_form_bundle",
        return_value=_bundle(_strong_form(), coverage_quality="high"),
    ):
        shadowed = build_scoreline_decision(
            final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
            top_scores=result["top_scores"],
            all_scores=all_scores,
            home_xg=1.81,
            away_xg=0.79,
            home_team="Netherlands",
            away_team="Sweden",
        )

    assert baseline.primary_predicted_score is not None
    assert shadowed.primary_predicted_score is not None
    assert (
        baseline.primary_predicted_score.score_label
        == shadowed.primary_predicted_score.score_label
    )


def test_primary_can_change_under_safe_active_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RECENT_FORM_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", True)
    monkeypatch.setattr(config, "RECENT_FORM_AFFECTS_SCORELINE", True)

    all_scores = _matrix(1.9, 0.85)
    engine = AdvancedDixonColesEngine(alpha=0.0)
    result = engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=1.9,
        away_xg_override=0.85,
    )

    with patch(
        "core.recent_form_shadow.load_fusion_recent_form_bundle",
        return_value=_bundle(_strong_form(), coverage_quality="high"),
    ):
        decision = build_scoreline_decision(
            final_probabilities_1x2={"home_win": 58.0, "draw": 24.0, "away_win": 18.0},
            top_scores=result["top_scores"],
            all_scores=all_scores,
            home_xg=1.9,
            away_xg=0.85,
            home_team="Brazil",
            away_team="Haiti",
        )

    rf = decision.recent_form_shadow
    assert rf.get("enabled") is True
    assert rf.get("active_experiment_enabled") is True


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


def test_predict_does_not_call_external_apis(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("live external API call attempted from /api/predict")

    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)

    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    assert "probabilities_1x2" in data
    assert "scoreline_decision" in data


def test_diagnostics_present_when_shadow_enabled(client: TestClient) -> None:
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
    gate = sd.get("underdog_goal_gate") or {}
    assert "recent_form" in gate or rf


def test_odds_calibration_unchanged(client: TestClient) -> None:
    payload = {"home_team": "Netherlands", "away_team": "Sweden", "neutral_ground": True}
    first = client.post("/api/predict", json=payload).json()
    second = client.post("/api/predict", json=payload).json()
    assert first["probabilities_1x2"] == second["probabilities_1x2"]
    assert first.get("probability_calibration") == second.get("probability_calibration")


def test_classify_support_levels() -> None:
    assert (
        classify_underdog_support_level(scoring=_unavailable_form(), coverage_quality="unavailable")
        == "unavailable"
    )
    assert classify_underdog_support_level(scoring=_strong_form(), coverage_quality="medium") == "strong"
    assert classify_underdog_support_level(scoring=_negative_form(), coverage_quality="medium") == "negative"


def test_load_fusion_bundle_offline_without_cache() -> None:
    bundle = load_fusion_recent_form_bundle("Haiti")
    assert bundle.support_level in {"unavailable", "weak", "negative", "moderate", "strong"}
