"""Tests for market quality scoring bands."""

from __future__ import annotations

import json
from pathlib import Path

from core.market_consensus import build_market_consensus
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW, score_market_quality
from core.market_types import MarketFamily, NormalizedMarketSnapshot

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rapidapi_odds_feed_norway_england.json"


def _h2h_only_snapshot() -> NormalizedMarketSnapshot:
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


def _yellow_snapshot() -> NormalizedMarketSnapshot:
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
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 1.8, "outcome_1": 2.0}
                ],
            },
            {
                "provider_market_name": "ASIAN_HANDICAP",
                "mapped_family": "spreads",
                "line_point": 0.5,
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 1.9, "outcome_1": 1.9}
                ],
            },
        ],
    }
    return parse_rapidapi_odds_feed_audit(report)


def test_quality_red_h2h_only() -> None:
    snap = _h2h_only_snapshot()
    result = score_market_quality(snap)
    assert result.band == BAND_RED
    assert MarketFamily.H2H.value in result.families_present


def test_quality_yellow_without_btts() -> None:
    snap = _yellow_snapshot()
    result = score_market_quality(snap)
    assert result.band == BAND_YELLOW
    assert result.has_btts is False


def test_quality_green_norway_england_fixture() -> None:
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap = parse_rapidapi_odds_feed_audit(report)
    consensus = build_market_consensus(snap)
    result = score_market_quality(snap, consensus)
    assert result.band == BAND_GREEN
    assert result.has_btts is True
    assert result.total_line_count >= 10
    assert result.spread_line_count >= 10


def test_pipeline_returns_consensus_and_quality() -> None:
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap = parse_rapidapi_odds_feed_audit(report)
    consensus, quality = build_snapshot_pipeline(snap)
    assert consensus.h2h is not None
    assert quality.band == BAND_GREEN
