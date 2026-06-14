"""Pytest validation — Negative Binomial matrix must sum to 100%."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.math_engine import AdvancedDixonColesEngine
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager


def test_probabilities_sum_to_100_on_negative_binomial() -> None:
    engine = AdvancedDixonColesEngine(rho=-0.07, global_avg=2.6, alpha=0.12)
    result = engine.generate_match_prediction(1600.0, 1500.0, 55.0)
    total = sum(result["probabilities_1x2"].values())
    assert 99.9 <= total <= 100.1


def test_neutral_ground_no_advantage() -> None:
    engine = AdvancedDixonColesEngine()
    with_adv = engine.generate_match_prediction(1600.0, 1500.0, 55.0)
    neutral = engine.generate_match_prediction(1600.0, 1500.0, 0.0)
    assert with_adv["probabilities_1x2"]["home_win"] >= neutral["probabilities_1x2"]["home_win"]


def test_environmental_modifiers_reduce_power() -> None:
    dm = LiveDataManager()
    evaluator = TeamPowerEvaluator(dm)
    base = evaluator.calculate_composite_power("Canada (קנדה)")
    modified = evaluator.apply_environmental_modifiers(
        base, altitude=2000, star_absent=True
    )
    assert modified < base


def test_extreme_rating_difference() -> None:
    engine = AdvancedDixonColesEngine()
    result = engine.generate_match_prediction(2000.0, 1200.0, 55.0)
    total = sum(result["probabilities_1x2"].values())
    assert 99.9 <= total <= 100.1
    assert result["probabilities_1x2"]["home_win"] > 50.0


def test_alpha_zero_falls_back_to_poisson_like() -> None:
    engine = AdvancedDixonColesEngine(alpha=0.0)
    result = engine.generate_match_prediction(1600.0, 1500.0, 55.0)
    total = sum(result["probabilities_1x2"].values())
    assert 99.9 <= total <= 100.1


def test_top_n_and_score_coverage() -> None:
    engine = AdvancedDixonColesEngine()
    result = engine.generate_match_prediction(1600.0, 1500.0, 0.0, top_n=10)
    assert len(result["top_scores"]) == 10
    coverage = result["score_coverage"]
    assert coverage["achieved_percent"] >= 50.0
    assert len(coverage["scores"]) >= 1


def test_sample_match_score_in_range() -> None:
    engine = AdvancedDixonColesEngine()
    h, a = engine.sample_match_score(1700.0, 1400.0, 0.0)
    assert 0 <= h < 6
    assert 0 <= a < 6
