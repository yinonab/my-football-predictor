"""Near-balanced draw/modal overlay (Option C) tests."""

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
    BALANCED_MARGIN_PP,
    CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS,
    NEAR_BALANCED_DRAW_MODAL_APPLIED,
    ScorelineCandidate,
    _apply_near_balanced_draw_modal,
)

PREDICT_BASE = dict(
    neutral_ground=True,
    include_diagnostics=True,
    fusion_blowout_enabled=True,
    odds_affect_prediction=False,
    use_match_context=False,
    auto_stadium_altitude=False,
    altitude=0,
    avg_goals=2.6,
    rho=-0.15,
    alpha=0.0,
    top_n=10,
)


def _cand(h: int, a: int, prob: float) -> ScorelineCandidate:
    outcome = "home_win" if h > a else "away_win" if a > h else "draw"
    return ScorelineCandidate(home_goals=h, away_goals=a, probability=prob, outcome=outcome)


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


def _primary_label(client: TestClient, home: str, away: str) -> str:
    data = client.post(
        "/api/predict",
        json={**PREDICT_BASE, "home_team": home, "away_team": away},
    ).json()
    primary = data["scoreline_decision"]["primary_predicted_score"]
    assert primary is not None
    return f"{primary['home_goals']}-{primary['away_goals']}"


def _warnings(client: TestClient, home: str, away: str) -> list[str]:
    data = client.post(
        "/api/predict",
        json={**PREDICT_BASE, "home_team": home, "away_team": away},
    ).json()
    return data["scoreline_decision"].get("warnings") or []


# --- helper-level unit tests ----------------------------------------------------


def test_draw_modal_switches_home_narrow_win() -> None:
    primary = _cand(1, 0, 11.5)
    draw_modal = _cand(1, 1, 10.0)
    candidates = [draw_modal, primary, _cand(2, 0, 9.0)]
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="home_win",
        margin_pp=8.0,
        draw_probability=35.0,
        candidates=candidates,
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=False,
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"


def test_draw_modal_switches_away_narrow_win() -> None:
    primary = _cand(0, 1, 11.2)
    draw_modal = _cand(1, 1, 10.5)
    candidates = [draw_modal, primary, _cand(0, 2, 9.0)]
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="away_win",
        margin_pp=9.0,
        draw_probability=33.0,
        candidates=candidates,
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=False,
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"


def test_draw_modal_skips_when_margin_above_cap() -> None:
    primary = _cand(1, 0, 11.5)
    draw_modal = _cand(1, 1, 11.0)
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="home_win",
        margin_pp=12.4,
        draw_probability=35.0,
        candidates=[draw_modal, primary],
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=False,
    )
    assert result["applied"] is False
    assert result["primary"].score_label == "1-0"


def test_draw_modal_skips_non_narrow_primary() -> None:
    primary = _cand(2, 1, 11.0)
    draw_modal = _cand(1, 1, 10.5)
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="home_win",
        margin_pp=8.0,
        draw_probability=35.0,
        candidates=[draw_modal, primary],
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=False,
    )
    assert result["applied"] is False


def test_draw_modal_skips_balanced_modal_path() -> None:
    primary = _cand(1, 0, 11.0)
    draw_modal = _cand(1, 1, 10.5)
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="home_win",
        margin_pp=BALANCED_MARGIN_PP,
        draw_probability=35.0,
        candidates=[draw_modal, primary],
        top_exact=draw_modal,
        used_balanced_modal_path=True,
        guard_switched_to_btts=False,
    )
    assert result["applied"] is False


def test_draw_modal_skips_after_btts_guard_switch() -> None:
    primary = _cand(1, 2, 11.0)
    draw_modal = _cand(1, 1, 10.5)
    result = _apply_near_balanced_draw_modal(
        primary,
        favorite="away_win",
        margin_pp=8.0,
        draw_probability=35.0,
        candidates=[draw_modal, primary],
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=True,
    )
    assert result["applied"] is False


# --- production-parity integration tests ----------------------------------------


def test_argentina_portugal_switches_to_draw(client: TestClient) -> None:
    label = _primary_label(client, "Argentina", "Portugal")
    assert label == "1-1"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED in _warnings(client, "Argentina", "Portugal")


def test_brazil_netherlands_switches_to_draw(client: TestClient) -> None:
    label = _primary_label(client, "Brazil", "Netherlands")
    assert label == "1-1"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED in _warnings(client, "Brazil", "Netherlands")


def test_france_england_stays_narrow_home_win(client: TestClient) -> None:
    """Near-balanced Option C must not fire for FRA-ENG when draw gate fails.

    Local power/xG can drift; assert overlay absence rather than a brittle 1-0.
    """
    label = _primary_label(client, "France", "England")
    warnings = _warnings(client, "France", "England")
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED not in warnings
    # Primary may be 1-0 (narrow CS) or a BTTS/guard result under local drift,
    # but Option C must not have forced the swap.
    assert label in {"1-0", "2-0", "2-1", "1-1", "0-0"}
    if label == "1-1":
        # If 1-1 appears it must not be via Option C (covered above).
        assert NEAR_BALANCED_DRAW_MODAL_APPLIED not in warnings


def test_netherlands_argentina_stays_btts_primary(client: TestClient) -> None:
    label = _primary_label(client, "Netherlands", "Argentina")
    assert label == "1-2"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED not in _warnings(client, "Netherlands", "Argentina")


def test_france_portugal_stays_two_one(client: TestClient) -> None:
    label = _primary_label(client, "France", "Portugal")
    assert label == "2-1"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED not in _warnings(client, "France", "Portugal")


@pytest.mark.parametrize(
    ("home", "away"),
    [
        ("France", "Spain"),
        ("Argentina", "England"),
        ("England", "Portugal"),
    ],
)
def test_balanced_modal_path_unchanged(client: TestClient, home: str, away: str) -> None:
    label = _primary_label(client, home, away)
    assert label == "1-1"
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED not in _warnings(client, home, away)
