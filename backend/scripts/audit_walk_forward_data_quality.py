#!/usr/bin/env python3
"""Walk-forward data quality audit (Phase 2E)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.temporal_match_data import audit_dataset_data_quality, format_data_quality_table
from data.tournament_data import list_dataset_keys, resolve_dataset_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward data quality audit.")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        default=None,
        help="Dataset keys (default: all tournament datasets)",
    )
    parser.add_argument(
        "--prior-mode",
        default="default_internal",
        choices=["default_internal", "tournament_prior_file", "rolling_from_prior_dataset"],
    )
    parser.add_argument(
        "--world-elo-mode",
        default="none",
        choices=["none", "current_static", "snapshot_file", "proxy_from_internal"],
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Phase 2F coverage report (override + prior + low-leakage readiness)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = args.datasets or list_dataset_keys()

    if args.coverage:
        from core.fixture_metadata import audit_dataset_coverage, format_coverage_table

        reports = []
        for ds in datasets:
            key = resolve_dataset_key(ds)
            if key == "all":
                for dk in list_dataset_keys():
                    reports.append(
                        audit_dataset_coverage(
                            dk,
                            prior_mode=args.prior_mode,
                            world_elo_mode=args.world_elo_mode,
                        )
                    )
            else:
                reports.append(
                    audit_dataset_coverage(
                        ds,
                        prior_mode=args.prior_mode,
                        world_elo_mode=args.world_elo_mode,
                    )
                )
        if args.json:
            print(json.dumps([r.to_dict() for r in reports], indent=2))
        else:
            print("Walk-forward data quality coverage (Phase 2F)\n")
            print(format_coverage_table(reports))
        return

    reports = []
    for ds in datasets:
        key = resolve_dataset_key(ds)
        if key == "all":
            for dk in list_dataset_keys():
                reports.append(
                    audit_dataset_data_quality(
                        dk,
                        prior_mode=args.prior_mode,
                        world_elo_mode=args.world_elo_mode,
                    )
                )
        else:
            reports.append(
                audit_dataset_data_quality(
                    ds,
                    prior_mode=args.prior_mode,
                    world_elo_mode=args.world_elo_mode,
                )
            )

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print("Walk-forward data quality audit\n")
        print(format_data_quality_table(reports))


if __name__ == "__main__":
    main()
