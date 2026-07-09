"""Read-only CLI: batch shadow evaluation across static fixtures (no API, no predict)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.market_shadow_evaluation import (  # noqa: E402
    load_evaluation_cases,
    run_shadow_evaluation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Market shadow evaluation harness (static only)")
    parser.add_argument(
        "--cases",
        type=Path,
        default=BACKEND / "tests" / "fixtures" / "market_shadow_eval_cases.json",
        help="Path to evaluation cases JSON",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    cases = load_evaluation_cases(args.cases)
    reports = run_shadow_evaluation(cases)

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
        return 0

    print(f"cases: {len(reports)}")
    print(f"{'fixture':<24} {'band':<7} {'verdict':<7} favorite  weight  eff_fav")
    print("-" * 72)
    for r in reports:
        eff = r.effective_movement.get("favorite_side")
        eff_s = f"{eff:g}" if eff is not None else "n/a"
        print(
            f"{r.fixture:<24} {r.quality_band:<7} {r.verdict:<7} "
            f"{r.market_favorite:<9} {r.requested_shadow_weight_pct:>3}%   {eff_s:>5}%"
        )
        if r.verdict_reasons:
            print(f"  reasons: {', '.join(r.verdict_reasons)}")
        if r.warnings:
            print(f"  warnings: {', '.join(r.warnings[:3])}")
    pass_n = sum(1 for r in reports if r.verdict == "PASS")
    review_n = sum(1 for r in reports if r.verdict == "REVIEW")
    fail_n = sum(1 for r in reports if r.verdict == "FAIL")
    print(f"\nsummary: PASS={pass_n} REVIEW={review_n} FAIL={fail_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
