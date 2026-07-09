"""Read-only CLI: market shadow diagnostics from static fixture (no API, no predict)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.market_consensus import build_market_consensus  # noqa: E402
from core.market_parser import parse_rapidapi_odds_feed_audit  # noqa: E402
from core.market_quality import score_market_quality  # noqa: E402
from core.market_shadow import build_market_shadow_report  # noqa: E402

DEFAULT_FIXTURE = BACKEND / "tests" / "fixtures" / "rapidapi_odds_feed_norway_england.json"

STATIC_MODEL = {
    "primary_score": "1-1",
    "top_scores": [
        {"score": "1-1", "probability": 11.2},
        {"score": "0-1", "probability": 10.5},
        {"score": "1-2", "probability": 9.8},
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Market shadow diagnostics (static fixture only)")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to RapidAPI audit fixture JSON",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    report_data = json.loads(args.fixture.read_text(encoding="utf-8"))
    snapshot = parse_rapidapi_odds_feed_audit(report_data)
    consensus = build_market_consensus(snapshot)
    quality = score_market_quality(snapshot, consensus)
    shadow = build_market_shadow_report(STATIC_MODEL, consensus, quality, snapshot=snapshot)

    if args.json:
        print(json.dumps(shadow.to_dict(), indent=2))
    else:
        d = shadow.to_dict()
        print(f"fixture: {args.fixture.name}")
        print(f"match: {snapshot.home_team} vs {snapshot.away_team}")
        print(f"quality: {d['quality_band']} (score {d['quality_score']})")
        print(f"market favorite: {d['market_favorite']} ({d['market_favorite_pct']}%)")
        print(f"h2h: {d['market_h2h']}")
        print(f"shadow tendency: {d['shadow_tendency']}")
        if d.get("favorite_win_pressure"):
            print(f"favorite win (-0.5): {d['favorite_win_pressure']['detail']}")
        if d.get("favorite_non_loss_pressure"):
            print(f"favorite non-loss (+0.5): {d['favorite_non_loss_pressure']['detail']}")
        print(f"candidate tendencies: {', '.join(d['candidate_score_tendencies'])}")
        print(f"recommended weight: {d['recommended_market_weight_pct']}%")
        print(f"model primary (unchanged): {d['model_primary_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
