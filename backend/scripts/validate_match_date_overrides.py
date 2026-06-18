#!/usr/bin/env python3
"""Validate curated match date overrides (Phase 2F)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.fixture_metadata import (
    TOURNAMENT_STARTS,
    format_override_validation_table,
    validate_dataset_overrides,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate match date overrides.")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
        help="wc2018, wc2022, euro2024, copa2024 (default: all tournament datasets)",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = args.datasets or list(TOURNAMENT_STARTS.keys())
    reports = [validate_dataset_overrides(ds) for ds in datasets]

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print("Match date override validation\n")
        print(format_override_validation_table(reports))
        failed = [r for r in reports if r.status != "ok"]
        if failed:
            print(f"\n{len(failed)} dataset(s) failed validation.")
            sys.exit(1)


if __name__ == "__main__":
    main()
