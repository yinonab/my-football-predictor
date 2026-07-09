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
from core.market_matrix_shadow import calibrate_market_matrix_shadow  # noqa: E402
from core.market_shadow import build_market_shadow_report  # noqa: E402

DEFAULT_FIXTURE = BACKEND / "tests" / "fixtures" / "rapidapi_odds_feed_norway_england.json"

STATIC_MATRIX = {
    "0-0": 7.5,
    "1-0": 9.5,
    "0-1": 10.5,
    "1-1": 12.0,
    "2-0": 7.0,
    "0-2": 8.5,
    "2-1": 9.0,
    "1-2": 10.0,
    "2-2": 7.5,
    "3-1": 5.0,
    "1-3": 5.5,
    "3-0": 3.5,
    "0-3": 4.0,
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
    parser.add_argument("--matrix", action="store_true", help="Include matrix shadow calibration output")
    args = parser.parse_args()

    report_data = json.loads(args.fixture.read_text(encoding="utf-8"))
    snapshot = parse_rapidapi_odds_feed_audit(report_data)
    consensus = build_market_consensus(snapshot)
    quality = score_market_quality(snapshot, consensus)
    static_model = {
        "primary_score": "1-1",
        "top_scores": [
            {"score": s, "probability": p}
            for s, p in sorted(STATIC_MATRIX.items(), key=lambda kv: kv[1], reverse=True)[:3]
        ],
    }
    shadow = build_market_shadow_report(static_model, consensus, quality, snapshot=snapshot)
    matrix = calibrate_market_matrix_shadow(STATIC_MATRIX, consensus, quality)

    if args.json:
        payload = {"shadow": shadow.to_dict(), "matrix": matrix.to_dict()}
        print(json.dumps(payload, indent=2))
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
        if args.matrix:
            m = matrix.to_dict()
            print("matrix requested weight:", m["requested_shadow_weight_pct"])
            print("effective favorite movement %:", m["effective_favorite_side_movement_pct"])
            print("effective btts movement %:", m["effective_btts_movement_pct"])
            print("effective over2.5 movement %:", m["effective_over_2_5_movement_pct"])
            print("top before:", ", ".join(f"{x['score']} {x['probability']}" for x in m["top_scores_before"][:5]))
            print("top after:", ", ".join(f"{x['score']} {x['probability']}" for x in m["top_scores_after"][:5]))
            print("1x2 before/after:", m["implied_1x2_before"], "->", m["implied_1x2_after"])
            print("over2.5 before/after:", m["implied_total_over_2_5_before"], "->", m["implied_total_over_2_5_after"])
            print("btts before/after:", m["implied_btts_before"], "->", m["implied_btts_after"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
