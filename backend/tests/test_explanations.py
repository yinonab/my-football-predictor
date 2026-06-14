"""Tests for Hebrew prediction explanations."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.explanations import (
    build_match_summary,
    explain_exact_score,
    explain_outcome_1x2,
)


def test_exact_score_explanation_not_empty() -> None:
    text = explain_exact_score(
        "1-1",
        12.5,
        home_xg=1.3,
        away_xg=1.2,
        home_team="Argentina (ארגנטינה)",
        away_team="France (צרפת)",
        rank=1,
    )
    assert len(text) > 20
    assert "תיקו" in text or "מאוזן" in text


def test_outcome_explanation_home_favorite() -> None:
    text = explain_outcome_1x2(
        "home",
        55.0,
        home_power=900,
        away_power=750,
        home_xg=1.8,
        away_xg=1.0,
        home_team="Brazil (ברזיל)",
        away_team="Haiti (האיטי)",
    )
    assert "ברזיל" in text
    assert "55" in text


def test_match_summary() -> None:
    summary = build_match_summary(
        home_team="Argentina (ארגנטינה)",
        away_team="France (צרפת)",
        home_power=880,
        away_power=870,
        home_xg=1.5,
        away_xg=1.4,
        probs={"home_win": 38.0, "draw": 28.0, "away_win": 34.0},
    )
    assert "צפי מרכזי" in summary
