"""Tests for shadow market evaluation harness (Phase 3C/3D)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core.market_matrix_shadow import calibrate_market_matrix_shadow
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
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


@pytest.fixture
def eval_cases() -> list[dict]:
    return load_evaluation_cases(CASES_FIXTURE)


def _case_by_name(cases: list[dict], name: str) -> dict:
    return next(c for c in cases if c["name"] == name)


def _btts_yes_mass(matrix: dict[str, float]) -> float:
    return sum(
        p for s, p in matrix.items() if "-" in s and all(int(x) > 0 for x in s.split("-", 1))
    )


def _high_total_mass(matrix: dict[str, float]) -> float:
    return sum(p for s, p in matrix.items() if sum(int(x) for x in s.split("-", 1)) >= 4)


def _low_total_mass(matrix: dict[str, float]) -> float:
    return sum(p for s, p in matrix.items() if sum(int(x) for x in s.split("-", 1)) <= 2)


def test_evaluation_report_green_norway_england(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "norway_england_green"))
    assert report.quality_band == "GREEN"
    assert report.market_favorite == "England"
    assert report.effective_movement["favorite_side"] is not None
    assert report.effective_movement["favorite_side"]["status"] in ("ok", "overshoot", "small_gap")
    assert report.totals_pressure is not None
    assert report.btts_pressure is not None


def test_pass_verdict_coherent_green_fixture(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "norway_england_green"))
    assert report.verdict == VERDICT_PASS


def test_review_verdict_weak_incomplete_market(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "h2h_only_red_review"))
    assert report.quality_band == "RED"
    assert report.verdict == VERDICT_REVIEW


def test_all_cases_match_expected_verdict(eval_cases) -> None:
    reports = run_shadow_evaluation(eval_cases)
    by_name = {r.fixture: r for r in reports}
    for case in eval_cases:
        expected = case.get("expected_verdict")
        if expected:
            assert by_name[case["name"]].verdict == expected, case["name"]


def test_strong_favorite_under_btts_no_reduces_btts_and_high_totals(eval_cases) -> None:
    case = _case_by_name(eval_cases, "strong_favorite_under_btts_no")
    before = copy.deepcopy(case["model_score_matrix"])
    report = evaluate_shadow_case(case)
    snap = parse_rapidapi_odds_feed_audit(case["inline_market"])
    consensus, quality = build_snapshot_pipeline(snap)
    matrix = calibrate_market_matrix_shadow(before, consensus, quality)

    assert report.market_favorite == "City"
    assert report.totals_pressure and report.totals_pressure["direction"] == "under"
    assert report.btts_pressure and report.btts_pressure["direction"] == "no"
    assert matrix.implied_btts_after < matrix.implied_btts_before
    assert _high_total_mass(matrix.shadow_calibrated_matrix) <= _high_total_mass(
        matrix.original_model_matrix
    )
    top = [r["score"] for r in report.shadow_top_scores_after[:5]]
    assert any(s in top for s in ("1-0", "2-0", "3-0", "2-1"))


def test_strong_favorite_over_btts_yes_boosts_attacking_scores(eval_cases) -> None:
    case = _case_by_name(eval_cases, "strong_favorite_over_btts_yes")
    report = evaluate_shadow_case(case)
    snap = parse_rapidapi_odds_feed_audit(case["inline_market"])
    consensus, quality = build_snapshot_pipeline(snap)
    matrix = calibrate_market_matrix_shadow(case["model_score_matrix"], consensus, quality)

    assert report.totals_pressure and report.totals_pressure["direction"] == "over"
    assert report.btts_pressure and report.btts_pressure["direction"] == "yes"
    assert matrix.implied_btts_after > matrix.implied_btts_before
    top = [r["score"] for r in report.shadow_top_scores_after[:5]]
    assert any(s in top for s in ("2-1", "3-1", "1-2", "2-2"))


def test_balanced_match_does_not_overforce_favorite(eval_cases) -> None:
    case = _case_by_name(eval_cases, "balanced_match_over_btts_yes")
    report = evaluate_shadow_case(case)
    assert report.quality_band == "GREEN"
    snap = parse_rapidapi_odds_feed_audit(case["inline_market"])
    consensus, quality = build_snapshot_pipeline(snap)
    matrix = calibrate_market_matrix_shadow(case["model_score_matrix"], consensus, quality)
    spread = abs(matrix.implied_1x2_after["home"] - matrix.implied_1x2_after["away"])
    assert spread < 15.0
    top = [r["score"] for r in report.shadow_top_scores_after[:5]]
    assert any(s in top for s in ("1-1", "2-1", "1-2", "2-2"))


def test_balanced_under_btts_no_reduces_high_scoring_lines(eval_cases) -> None:
    case = _case_by_name(eval_cases, "balanced_match_under_btts_no")
    report = evaluate_shadow_case(case)
    snap = parse_rapidapi_odds_feed_audit(case["inline_market"])
    consensus, quality = build_snapshot_pipeline(snap)
    matrix = calibrate_market_matrix_shadow(case["model_score_matrix"], consensus, quality)

    assert report.totals_pressure and report.totals_pressure["direction"] == "under"
    assert report.btts_pressure and report.btts_pressure["direction"] == "no"
    assert _low_total_mass(matrix.shadow_calibrated_matrix) >= _low_total_mass(
        matrix.original_model_matrix
    )
    assert matrix.shadow_calibrated_matrix.get("2-2", 0) <= matrix.original_model_matrix.get(
        "2-2", 0
    ) + 0.5


def test_underdog_btts_yes_increases_btts_vs_clean_sheet_model(eval_cases) -> None:
    case = _case_by_name(eval_cases, "underdog_btts_yes_review")
    report = evaluate_shadow_case(case)
    snap = parse_rapidapi_odds_feed_audit(case["inline_market"])
    consensus, quality = build_snapshot_pipeline(snap)
    matrix = calibrate_market_matrix_shadow(case["model_score_matrix"], consensus, quality)

    assert report.verdict == VERDICT_REVIEW
    assert matrix.implied_btts_after > matrix.implied_btts_before
    assert report.shadow_top_scores_after[0]["score"] != "2-0"


def test_yellow_no_btts_is_review(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "yellow_no_btts_review"))
    assert report.quality_band == "YELLOW"
    assert report.verdict == VERDICT_REVIEW
    assert report.btts_pressure is None


def test_incoherent_market_fail_verdict(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "incoherent_market_fail"))
    assert report.verdict == VERDICT_FAIL
    assert "synthetic_incoherent_opposite_direction_injected" in report.direction_notes


def test_weak_effective_movement_review_verdict(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "weak_effective_movement_review"))
    assert report.quality_band == "GREEN"
    assert report.verdict == VERDICT_REVIEW
    assert any("effective_movement" in r for r in report.verdict_reasons)


def test_strong_favorite_effective_movement_not_misleading_in_table(eval_cases) -> None:
    report = evaluate_shadow_case(_case_by_name(eval_cases, "strong_favorite_under_btts_no"))
    fav = report.effective_movement["favorite_side"]
    assert fav is not None
    assert fav["display"] == "n/a-small-gap"
    assert fav["status"] == "small_gap"
    assert report.verdict == VERDICT_PASS
    assert report.market_h2h["home"] >= 60.0
    assert "effective_movement_below_threshold" not in " ".join(report.verdict_reasons)


def test_effective_movement_metric_small_gap_and_overshoot() -> None:
    from core.market_matrix_shadow import EffectiveMovementMetric

    small = EffectiveMovementMetric.compute(60.0, 63.0, 62.5)
    assert small.status == "small_gap"
    assert small.display == "n/a-small-gap"
    assert small.weak_check_value() is None

    overshoot = EffectiveMovementMetric.compute(50.0, 58.0, 55.0)
    assert overshoot.status == "overshoot"
    assert overshoot.display.startswith("overshoot")
    assert overshoot.weak_check_value() is None

    ok = EffectiveMovementMetric.compute(38.0, 43.0, 51.0)
    assert ok.status == "ok"
    assert ok.weak_check_value() == ok.raw_pct


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


def test_no_model_mutation_during_evaluation(eval_cases) -> None:
    case = copy.deepcopy(_case_by_name(eval_cases, "norway_england_green"))
    matrix_before = copy.deepcopy(case["model_score_matrix"])
    evaluate_shadow_case(case)
    assert case["model_score_matrix"] == matrix_before


def test_no_production_predict_imports() -> None:
    import core.market_shadow_evaluation as mse

    source = Path(mse.__file__).read_text(encoding="utf-8")
    assert "api.main" not in source
    assert "scoreline_decision" not in source


def test_batch_evaluation_run(eval_cases) -> None:
    reports = run_shadow_evaluation(eval_cases)
    assert len(reports) == len(eval_cases)
    assert sum(1 for r in reports if r.verdict == VERDICT_PASS) >= 3
