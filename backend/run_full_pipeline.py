"""Run full pipeline: build ratings, calibrate, optional API fetch."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.calibrate import current_defaults_report, grid_search  # noqa: E402
from core.team_ratings import build_all_matches, build_and_save_ratings  # noqa: E402
from data.api_football import ApiFootballClient  # noqa: E402

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_dotenv()

    print("=" * 60)
    print("  FULL NT PIPELINE — phases 3–6")
    print("=" * 60)

    client = ApiFootballClient()
    if client.is_available:
        print("\n[6] Fetching API history (qualifiers + friendlies)...")
        from run_fetch_nt_history import fetch_all_teams, save_fetched_matches

        try:
            fetched = fetch_all_teams(client=client)
            save_fetched_matches(fetched)
            print(f"    Fetched {len(fetched)} matches from API-Football")
        except Exception as exc:
            print(f"    API fetch skipped: {exc}")
    else:
        print("\n[6] API_FOOTBALL_KEY not set — skipping live fetch")

    print("\n[3–4] Building ratings + H2H index from bundled + cached matches...")
    ratings = build_and_save_ratings()
    matches = build_all_matches()
    with_history = sum(1 for r in ratings.values() if r.matches_used > 0)
    print(f"    {len(matches)} matches | {with_history}/48 teams with history")

    print("\n[5] Multi-tournament calibration (top 3 grid results)...")
    baseline = current_defaults_report()
    print(
        f"    Current: 1X2={baseline.report.outcome_accuracy}% "
        f"exact={baseline.report.exact_score_accuracy}% "
        f"top3={baseline.report.top3_score_hit_rate}%"
    )
    top = grid_search(top_n=3)
    best = top[0]
    print(
        f"    Best:    1X2={best.report.outcome_accuracy}% "
        f"exact={best.report.exact_score_accuracy}% "
        f"top3={best.report.top3_score_hit_rate}% "
        f"(rho={best.params.rho}, goals={best.params.avg_goals})"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
