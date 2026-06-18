#!/usr/bin/env python3
"""Audit backtest leakage / walk-forward risk (Phase 2C)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.backtest_leakage_audit import audit_backtest_leakage, format_leakage_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest leakage risk audit.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit_backtest_leakage()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_leakage_report(report))


if __name__ == "__main__":
    main()
