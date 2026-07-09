"""Tests for RapidAPI Odds Feed market parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.market_parser import parse_rapidapi_odds_feed_audit
from core.market_types import MarketFamily

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rapidapi_odds_feed_norway_england.json"


@pytest.fixture
def audit_report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_norway_england_snapshot(audit_report: dict) -> None:
    snap = parse_rapidapi_odds_feed_audit(audit_report)
    assert snap.home_team == "Norway"
    assert snap.away_team == "England"
    assert snap.event_id == "619963"
    assert MarketFamily.H2H in snap.families_present()
    assert MarketFamily.TOTALS in snap.families_present()
    assert MarketFamily.SPREADS in snap.families_present()
    assert MarketFamily.BTTS in snap.families_present()


def test_multi_line_totals_parsing(audit_report: dict) -> None:
    snap = parse_rapidapi_odds_feed_audit(audit_report)
    total_lines = snap.distinct_lines_for(MarketFamily.TOTALS)
    assert 2.5 in total_lines
    assert len(total_lines) >= 10


def test_multi_line_spreads_parsing(audit_report: dict) -> None:
    snap = parse_rapidapi_odds_feed_audit(audit_report)
    spread_lines = snap.distinct_lines_for(MarketFamily.SPREADS)
    assert 0.0 in spread_lines or 0.5 in spread_lines
    assert len(spread_lines) >= 10


def test_unknown_market_ignored() -> None:
    report = {
        "selected_event": {
            "event_id": "1",
            "label": "A vs B (Test)",
            "tournament": "Test",
        },
        "market_coverage_table": [
            {
                "provider_market_name": "WEIRD",
                "mapped_family": "unknown",
                "sample_odds": [{"book": "X", "outcome_0": 2.0, "outcome_1": 2.0}],
            },
            {
                "provider_market_name": "1X2",
                "mapped_family": "h2h",
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 2.0, "outcome_1": 3.2, "outcome_2": 3.5}
                ],
            },
        ],
    }
    snap = parse_rapidapi_odds_feed_audit(report)
    assert MarketFamily.UNKNOWN not in snap.families_present()
    assert len(snap.lines) == 1
    assert snap.lines[0].family == MarketFamily.H2H


def test_h2h_line_has_three_outcomes(audit_report: dict) -> None:
    snap = parse_rapidapi_odds_feed_audit(audit_report)
    h2h = [ln for ln in snap.lines if ln.family == MarketFamily.H2H]
    assert h2h
    assert len(h2h[0].outcomes) == 3
    assert abs(sum(o.fair_probability for o in h2h[0].outcomes) - 100.0) < 0.1
