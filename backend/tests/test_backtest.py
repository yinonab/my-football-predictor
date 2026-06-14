"""Backtest validation tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.backtest import BacktestRunner
from data.wc2022 import WC2022_MATCHES, WC2022_FIFA_ELO


def test_wc2022_has_64_matches() -> None:
    assert len(WC2022_MATCHES) == 64


def test_wc2022_has_32_teams() -> None:
    assert len(WC2022_FIFA_ELO) == 32


def test_backtest_report_ranges() -> None:
    report = BacktestRunner().run_wc2022()
    assert report.match_count == 64
    assert 0 <= report.outcome_accuracy <= 100
    assert 0 <= report.exact_score_accuracy <= 100
    assert 0 <= report.top3_score_hit_rate <= 100
    assert report.mean_brier >= 0
    assert report.mean_log_loss >= 0


def test_backtest_beats_random_outcome() -> None:
    report = BacktestRunner().run_wc2022()
    # Random 3-way guess ~33%; model should beat that clearly.
    assert report.outcome_accuracy > 40
