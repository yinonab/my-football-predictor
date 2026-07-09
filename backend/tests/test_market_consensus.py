"""Tests for cross-bookmaker market consensus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.market_consensus import build_market_consensus
from core.market_parser import parse_rapidapi_odds_feed_audit

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rapidapi_odds_feed_norway_england.json"


@pytest.fixture
def snapshot():
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_rapidapi_odds_feed_audit(report)


def test_h2h_consensus(snapshot) -> None:
    consensus = build_market_consensus(snapshot)
    assert consensus.h2h is not None
    assert set(consensus.h2h.keys()) == {"home", "draw", "away"}
    assert abs(sum(consensus.h2h.values()) - 100.0) < 0.5
    assert consensus.bookmaker_counts["h2h"] >= 3


def test_totals_consensus_by_line(snapshot) -> None:
    consensus = build_market_consensus(snapshot)
    assert "2.5" in consensus.totals_by_line
    line = consensus.totals_by_line["2.5"]
    assert set(line.keys()) == {"over", "under"}
    assert abs(line["over"] + line["under"] - 100.0) < 0.5


def test_spreads_consensus_by_line(snapshot) -> None:
    consensus = build_market_consensus(snapshot)
    assert consensus.spreads_by_line
    any_line = next(iter(consensus.spreads_by_line.values()))
    assert set(any_line.keys()) == {"home", "away"}


def test_btts_consensus(snapshot) -> None:
    consensus = build_market_consensus(snapshot)
    assert consensus.btts is not None
    assert set(consensus.btts.keys()) == {"yes", "no"}
    assert abs(consensus.btts["yes"] + consensus.btts["no"] - 100.0) < 0.5


def test_consensus_multiple_bookmakers(snapshot) -> None:
    consensus = build_market_consensus(snapshot)
    assert consensus.bookmaker_counts["all"] >= 3
