"""Primary score reason copy aligned with overlay warnings (display-only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AUDIT_ELO_BASELINE", "production")
os.environ.setdefault("NR3_FCC_SERVED_ENABLED", "true")

from api import main as api_main  # noqa: E402
from core.scoreline_decision import (  # noqa: E402
    CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS,
    ELITE_NON_CS_SELECTOR_APPLIED,
    NEAR_BALANCED_DRAW_MODAL_APPLIED,
    build_primary_score_reason,
    build_scoreline_decision,
)
from core.strength_result import StrengthResult  # noqa: E402

APP_PAYLOAD = dict(
    neutral_ground=True,
    include_diagnostics=True,
    fusion_blowout_enabled=False,
    odds_affect_prediction=False,
    use_match_context=True,
    auto_stadium_altitude=True,
    altitude=0,
    avg_goals=2.6,
    rho=-0.15,
    alpha=0.0,
    top_n=10,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


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


def _fra_col_matrix() -> dict[str, float]:
    return {
        "1-0": 16.18,
        "2-0": 12.56,
        "1-1": 12.50,
        "0-0": 12.26,
        "2-1": 8.67,
        "0-1": 7.12,
        "3-0": 6.20,
        "3-1": 4.50,
        "1-2": 4.04,
        "2-2": 3.50,
    }


def _predict(client: TestClient, home: str, away: str) -> dict:
    resp = client.post(
        "/api/predict",
        json={**APP_PAYLOAD, "home_team": home, "away_team": away},
    )
    resp.raise_for_status()
    return resp.json()


def test_france_colombia_draw_reason_not_favorite_win_pool() -> None:
    all_scores = _fra_col_matrix()
    top = [
        {"score": k, "probability": v}
        for k, v in sorted(all_scores.items(), key=lambda x: -x[1])[:10]
    ]
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 52.0, "draw": 24.9, "away_win": 23.1},
        top_scores=top,
        all_scores=all_scores,
        home_xg=1.48,
        away_xg=0.69,
        home_team="France",
        away_team="Colombia",
        strength=_strength(991.0, 890.0),
    )
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.score_label == "1-1"
    assert ELITE_NON_CS_SELECTOR_APPLIED in decision.warnings
    reason = decision.primary_score_reason
    assert "תרחישי הניצחון" not in reason
    assert "תיקו" in reason
    assert "מטריצת התוצאות" in reason


def test_argentina_brazil_draw_reason_via_api(client: TestClient) -> None:
    data = _predict(client, "Argentina", "Brazil")
    sd = data["scoreline_decision"]
    primary = sd["primary_predicted_score"]
    assert f"{primary['home_goals']}-{primary['away_goals']}" == "1-1"
    assert ELITE_NON_CS_SELECTOR_APPLIED in sd["warnings"]
    reason = sd["primary_score_reason"]
    assert "תרחישי הניצחון" not in reason
    assert "תיקו" in reason


def test_brazil_netherlands_balanced_draw_modal_reason(client: TestClient) -> None:
    data = _predict(client, "Brazil", "Netherlands")
    sd = data["scoreline_decision"]
    primary = sd["primary_predicted_score"]
    assert f"{primary['home_goals']}-{primary['away_goals']}" == "1-1"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED in sd["warnings"]
    reason = sd["primary_score_reason"]
    assert "תרחישי הניצחון" not in reason
    assert "מאוזן" in reason or "תיקו" in reason


def test_france_croatia_btts_guard_reason(client: TestClient) -> None:
    data = _predict(client, "France", "Croatia")
    sd = data["scoreline_decision"]
    primary = sd["primary_predicted_score"]
    assert f"{primary['home_goals']}-{primary['away_goals']}" == "2-1"
    assert CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS in sd["warnings"]
    reason = sd["primary_score_reason"]
    assert "שתי הקבוצות מבקיעות" in reason or "ליריבה" in reason
    assert primary["outcome"] == "home_win"


def test_germany_france_btts_guard_reason(client: TestClient) -> None:
    data = _predict(client, "Germany", "France")
    sd = data["scoreline_decision"]
    primary = sd["primary_predicted_score"]
    assert f"{primary['home_goals']}-{primary['away_goals']}" == "1-2"
    assert CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS in sd["warnings"]
    reason = sd["primary_score_reason"]
    assert "שתי הקבוצות מבקיעות" in reason or "ליריבה" in reason
    assert primary["outcome"] == "away_win"


def test_normal_no_overlay_keeps_favorite_win_wording() -> None:
    from core.scoreline_decision import ScorelineCandidate

    primary = ScorelineCandidate(1, 0, 12.0, "home_win")
    top = ScorelineCandidate(1, 1, 13.5, "draw")
    reason = build_primary_score_reason(
        primary=primary,
        top_exact=top,
        favorite_outcome="home_win",
        home_team="Canada",
        away_team="Qatar",
        balanced=False,
        differs=True,
        context_limited=False,
        prediction_invalid=False,
        completed=False,
        warnings=[],
    )
    assert "תרחישי הניצחון" in reason
    assert "תיקו סביר" not in reason
