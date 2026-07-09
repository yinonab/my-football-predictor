"""Tests for market shadow diagnostics (Phase 3A — no predict mutation)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core.market_consensus import build_market_consensus
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW, score_market_quality
from core.market_shadow import build_market_shadow_report

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rapidapi_odds_feed_norway_england.json"

NORWAY_ENGLAND_MODEL = {
    "primary_score": "1-1",
    "top_scores": [
        {"score": "1-1", "probability": 11.2},
        {"score": "0-1", "probability": 10.5},
        {"score": "1-2", "probability": 9.8},
    ],
}


def _h2h_only_snapshot():
    report = {
        "selected_event": {"event_id": "1", "label": "A vs B", "tournament": "T"},
        "market_coverage_table": [
            {
                "provider_market_name": "1X2",
                "mapped_family": "h2h",
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 2.0, "outcome_1": 3.2, "outcome_2": 3.5}
                ],
            }
        ],
    }
    return parse_rapidapi_odds_feed_audit(report)


def _yellow_snapshot():
    report = {
        "selected_event": {"event_id": "2", "label": "A vs B", "tournament": "T"},
        "market_coverage_table": [
            {
                "provider_market_name": "1X2",
                "mapped_family": "h2h",
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 2.0, "outcome_1": 3.2, "outcome_2": 3.5}
                ],
            },
            {
                "provider_market_name": "OVER_UNDER",
                "mapped_family": "totals",
                "line_point": 2.5,
                "sample_odds": [{"book": "BET365", "outcome_0": 1.8, "outcome_1": 2.0}],
            },
            {
                "provider_market_name": "ASIAN_HANDICAP",
                "mapped_family": "spreads",
                "line_point": 0.5,
                "sample_odds": [{"book": "BET365", "outcome_0": 1.9, "outcome_1": 1.9}],
            },
        ],
    }
    return parse_rapidapi_odds_feed_audit(report)


@pytest.fixture
def green_market():
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap = parse_rapidapi_odds_feed_audit(report)
    consensus, quality = build_snapshot_pipeline(snap)
    return snap, consensus, quality


def test_shadow_report_green_norway_england(green_market) -> None:
    snap, consensus, quality = green_market
    model = copy.deepcopy(NORWAY_ENGLAND_MODEL)

    report = build_market_shadow_report(model, consensus, quality, snapshot=snap)

    assert report.quality_band == BAND_GREEN
    assert report.market_favorite == "England"
    assert report.market_favorite_side == "away"
    assert 50.0 <= report.market_favorite_pct <= 53.0
    assert abs(report.market_h2h["away"] - 51.28) < 1.0
    assert report.totals_pressure is not None
    assert 52.0 <= report.totals_pressure.value_pct <= 56.0
    assert report.totals_pressure.direction == "over"
    assert report.btts_pressure is not None
    assert report.btts_pressure.direction == "yes"
    assert 55.0 <= report.btts_pressure.value_pct <= 58.0
    assert report.spread_pressure is not None
    assert "home handicap 0.5" in report.spread_pressure.detail
    assert report.favorite_win_pressure is not None
    assert abs(report.favorite_win_pressure.value_pct - report.market_h2h["away"]) < 3.0
    assert 50.0 <= report.favorite_win_pressure.value_pct <= 54.0
    assert report.favorite_non_loss_pressure is not None
    assert report.favorite_non_loss_pressure.value_pct > 70.0
    assert abs(
        report.favorite_non_loss_pressure.value_pct
        - (report.market_h2h["away"] + report.market_h2h["draw"])
    ) < 5.0
    assert "England" in report.shadow_tendency or "edge" in report.shadow_tendency
    assert "BTTS" in report.shadow_tendency
    assert report.recommended_market_weight_pct in (50, 60)
    assert report.model_primary_score == "1-1"
    assert len(report.candidate_score_tendencies) >= 3


def test_red_h2h_only_low_weight_recommendation() -> None:
    snap = _h2h_only_snapshot()
    consensus = build_market_consensus(snap)
    quality = score_market_quality(snap, consensus)
    assert quality.band == BAND_RED

    report = build_market_shadow_report(NORWAY_ENGLAND_MODEL, consensus, quality, snapshot=snap)
    assert report.recommended_market_weight_pct == 30
    assert report.totals_pressure is None
    assert report.btts_pressure is None


def test_yellow_medium_weight_without_btts() -> None:
    snap = _yellow_snapshot()
    consensus = build_market_consensus(snap)
    quality = score_market_quality(snap, consensus)
    assert quality.band == BAND_YELLOW

    report = build_market_shadow_report(NORWAY_ENGLAND_MODEL, consensus, quality, snapshot=snap)
    assert report.recommended_market_weight_pct == 40
    assert report.btts_pressure is None
    assert report.totals_pressure is not None
    assert report.spread_pressure is not None


def test_btts_yes_pressure_influences_diagnostic_text_only(green_market) -> None:
    snap, consensus, quality = green_market
    model = copy.deepcopy(NORWAY_ENGLAND_MODEL)

    report_yes = build_market_shadow_report(model, consensus, quality, snapshot=snap)
    btts_no_consensus = copy.deepcopy(consensus)
    btts_no_consensus.btts = {"yes": 40.0, "no": 60.0}
    report_no = build_market_shadow_report(model, btts_no_consensus, quality, snapshot=snap)

    assert "BTTS" in report_yes.shadow_tendency
    assert "clean-sheet" in report_no.shadow_tendency.lower() or "under" in report_no.shadow_tendency
    assert model["primary_score"] == "1-1"
    assert model["top_scores"][0]["score"] == "1-1"


def test_under_pressure_influences_diagnostic_text_only(green_market) -> None:
    snap, consensus, quality = green_market
    model = copy.deepcopy(NORWAY_ENGLAND_MODEL)

    under_consensus = copy.deepcopy(consensus)
    under_consensus.totals_by_line = {"2.5": {"over": 42.0, "under": 58.0}}
    report = build_market_shadow_report(model, under_consensus, quality, snapshot=snap)

    assert report.totals_pressure is not None
    assert report.totals_pressure.direction == "under"
    assert "under" in report.shadow_tendency
    assert model["primary_score"] == "1-1"
    assert model["top_scores"] == NORWAY_ENGLAND_MODEL["top_scores"]


def test_no_prediction_output_mutation(green_market) -> None:
    snap, consensus, quality = green_market
    before = copy.deepcopy(NORWAY_ENGLAND_MODEL)
    after_input = copy.deepcopy(NORWAY_ENGLAND_MODEL)

    build_market_shadow_report(after_input, consensus, quality, snapshot=snap)

    assert after_input == before
    assert after_input["primary_score"] == "1-1"
    assert after_input["top_scores"] == before["top_scores"]


def test_away_favorite_minus_half_uses_home_plus_half_line(green_market) -> None:
    snap, consensus, quality = green_market
    report = build_market_shadow_report(NORWAY_ENGLAND_MODEL, consensus, quality, snapshot=snap)

    assert report.favorite_win_pressure is not None
    assert "home handicap 0.5" in report.favorite_win_pressure.detail
    assert " -0.5 cover" in report.favorite_win_pressure.detail
    assert abs(report.favorite_win_pressure.value_pct - 51.89) < 1.0
    assert abs(report.favorite_win_pressure.value_pct - consensus.h2h["away"]) < 3.0


def test_away_plus_half_is_non_loss_not_favorite_win(green_market) -> None:
    snap, consensus, quality = green_market
    report = build_market_shadow_report(NORWAY_ENGLAND_MODEL, consensus, quality, snapshot=snap)

    assert report.favorite_non_loss_pressure is not None
    assert "+0.5 protection" in report.favorite_non_loss_pressure.detail
    assert "home handicap -0.5" in report.favorite_non_loss_pressure.detail
    assert report.favorite_non_loss_pressure.value_pct > 70.0
    assert report.favorite_non_loss_pressure.label == "favorite_non_loss"
    # Must not be labeled or valued like a -0.5 win cover.
    assert abs(report.favorite_non_loss_pressure.value_pct - consensus.h2h["away"]) > 15.0


def test_incoherent_handicap_line_marked_unavailable() -> None:
    consensus = build_market_consensus(_h2h_only_snapshot())
    # Force spreads where away at home +0.5 looks like double-chance (wrong sign read).
    consensus.h2h = {"home": 22.0, "draw": 26.0, "away": 52.0}
    consensus.spreads_by_line = {
        "0.5": {"home": 20.0, "away": 80.0},
        "-0.5": {"home": 25.0, "away": 75.0},
    }
    quality = score_market_quality(_h2h_only_snapshot(), consensus)
    report = build_market_shadow_report(
        NORWAY_ENGLAND_MODEL,
        consensus,
        quality,
        snapshot=_h2h_only_snapshot(),
    )

    assert report.favorite_win_pressure is None
    assert any("favorite_win_pressure_unavailable" in n for n in report.notes)
    assert report.favorite_non_loss_pressure is not None
