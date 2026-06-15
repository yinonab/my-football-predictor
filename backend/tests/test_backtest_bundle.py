"""Multi-tournament backtest tests."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.backtest import NationalTeamBacktestRunner
from data.nt_history_bundle import BUNDLED_NT_MATCHES


def test_bundle_backtest_runs() -> None:
    runner = NationalTeamBacktestRunner()
    report = runner.run_matches(list(BUNDLED_NT_MATCHES))
    assert report.match_count >= 100
    assert 0 <= report.outcome_accuracy <= 100
    assert 0 <= report.exact_score_accuracy <= 100
