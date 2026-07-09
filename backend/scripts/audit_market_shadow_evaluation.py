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


def _format_effective_display(effective: dict | float | None) -> str:
    if isinstance(effective, dict):
        return str(effective.get("display", "n/a"))
    if effective is None:
        return "n/a"
    return f"{effective:g}"


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
    print(
        f"{'fixture':<28} {'band':<7} {'verdict':<7} {'primary':<6} "
        f"{'fav':<9} {'O/U':<6} {'BTTS':<6} {'wt':>3} {'eff':>5}"
    )
    print("-" * 88)
    for r in reports:
        eff = r.effective_movement.get("favorite_side")
        eff_s = _format_effective_display(eff)
        ou = (r.totals_pressure or {}).get("direction", "n/a")[:6]
        btts = (r.btts_pressure or {}).get("direction", "n/a")[:6]
        primary = (r.model_primary_score or "n/a")[:6]
        top1 = r.shadow_top_scores_after[0]["score"] if r.shadow_top_scores_after else "n/a"
        print(
            f"{r.fixture:<28} {r.quality_band:<7} {r.verdict:<7} {primary:<6} "
            f"{r.market_favorite[:9]:<9} {ou:<6} {btts:<6} {r.requested_shadow_weight_pct:>3} {eff_s:>5}"
        )
        print(f"  shadow top1: {top1}")
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
