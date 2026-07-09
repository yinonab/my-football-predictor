"""Tests for shadow market evaluation harness (Phase 3C)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core.market_shadow_evaluation import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_REVIEW,
    compute_shadow_verdict,
    evaluate_shadow_case,
    load_evaluation_cases,
    run_shadow_evaluation,
)

CASES_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_shadow_eval_cases.json"

NORWAY_MATRIX = {
    "0-0": 7.5,
    "1-0": 9.5,
    "0-1": 10.5,
    "1-1": 12.0,
    "2-0": 7.0,
    "0-2": 8.5,
    "2-1": 9.0,
    "1-2": 10.0,
    "2-2": 7.5,
    "3-1": 5.0,
    "1-3": 5.5,
    "3-0": 3.5,
    "0-3": 4.0,
}


@pytest.fixture
def eval_cases() -> list[dict]:
    return load_evaluation_cases(CASES_FIXTURE)


def test_evaluation_report_green_norway_england(eval_cases) -> None:
    green = next(c for c in eval_cases if c["name"] == "norway_england_green")
    report = evaluate_shadow_case(green)

    assert report.fixture == "norway_england_green"
    assert report.quality_band == "GREEN"
    assert report.market_favorite == "England"
    assert report.model_primary_score == "1-1"
    assert report.requested_shadow_weight_pct in (50, 60)
    assert report.effective_movement["favorite_side"] is not None
    assert report.shadow_top_scores_after
    assert report.effective_movement["btts"] is not None


def test_pass_verdict_coherent_green_fixture(eval_cases) -> None:
    green = next(c for c in eval_cases if c["name"] == "norway_england_green")
    report = evaluate_shadow_case(green)
    assert report.verdict == VERDICT_PASS
    assert report.shadow_direction_reasonable is True
    assert "coherent_green_fixture_shadow_behavior" in report.verdict_reasons


def test_review_verdict_weak_incomplete_market(eval_cases) -> None:
    review = next(c for c in eval_cases if c["name"] == "h2h_only_red_review")
    report = evaluate_shadow_case(review)
    assert report.quality_band == "RED"
    assert report.verdict == VERDICT_REVIEW
    assert any("limited_market_quality" in r for r in report.verdict_reasons)


def test_fail_verdict_incoherent_movement() -> None:
    verdict, reasons = compute_shadow_verdict(
        matrix_sum=100.0,
        input_mutated=False,
        direction_reasonable=False,
        quality_band="GREEN",
        warnings=[],
        effective_favorite=10.0,
        opposite_movement=True,
    )
    assert verdict == VERDICT_FAIL
    assert "shadow_direction_opposite_or_incoherent" in reasons


def test_fail_verdict_non_normalized_matrix() -> None:
    verdict, reasons = compute_shadow_verdict(
        matrix_sum=88.0,
        input_mutated=False,
        direction_reasonable=True,
        quality_band="GREEN",
        warnings=[],
        effective_favorite=40.0,
    )
    assert verdict == VERDICT_FAIL
    assert "probabilities_not_normalized" in reasons


def test_no_model_mutation_during_evaluation(eval_cases) -> None:
    green = copy.deepcopy(next(c for c in eval_cases if c["name"] == "norway_england_green"))
    matrix_before = copy.deepcopy(green["model_score_matrix"])
    tops_before = copy.deepcopy(green["model_top_scores"])
    primary_before = green["model_primary_score"]

    report = evaluate_shadow_case(green)

    assert green["model_score_matrix"] == matrix_before
    assert green["model_top_scores"] == tops_before
    assert green["model_primary_score"] == primary_before
    assert report.model_primary_score == primary_before


def test_no_production_predict_imports() -> None:
    import core.market_shadow_evaluation as mse

    source = Path(mse.__file__).read_text(encoding="utf-8")
    assert "api.main" not in source
    assert "scoreline_decision" not in source
    assert "probability_pipeline" not in source
    assert "odds_ensemble" not in source


def test_batch_evaluation_run(eval_cases) -> None:
    reports = run_shadow_evaluation(eval_cases)
    assert len(reports) == 2
    by_name = {r.fixture: r.verdict for r in reports}
    assert by_name["norway_england_green"] == VERDICT_PASS
    assert by_name["h2h_only_red_review"] == VERDICT_REVIEW
