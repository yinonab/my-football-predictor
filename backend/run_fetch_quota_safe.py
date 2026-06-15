"""Quota-safe API-Football fetch — qualifiers only, stays under free daily limit."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from core.cloud_persist import push_all
from core.team_ratings import build_and_save_ratings, merge_matches
from data.api_football import ApiFootballClient
from data.nt_history_bundle import BUNDLED_NT_MATCHES
from data.nt_match import NationalTeamMatch
from run_fetch_nt_history import save_fetched_matches

logger = logging.getLogger(__name__)

DEFAULT_BUDGET = 80
# Free API-Football plan: seasons 2022–2024 only; one season keeps quota low
QUALIFIER_SEASONS = (2024,)


def fetch_quota_safe(
    *,
    budget: int = DEFAULT_BUDGET,
    seasons: tuple[int, ...] = QUALIFIER_SEASONS,
) -> tuple[list[NationalTeamMatch], int]:
    """Fetch WC qualifiers only; returns (matches, api_calls_used)."""
    api = ApiFootballClient(max_requests=budget)
    if not api.is_available:
        raise RuntimeError("API_FOOTBALL_KEY is not set")

    collected = api.fetch_all_qualifiers(seasons=seasons)
    merged = merge_matches(collected)
    logger.info(
        "Quota-safe fetch: %d qualifier fixtures, %d API calls",
        len(merged),
        api.request_count,
    )
    return merged, api.request_count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=" * 60)
    print("  QUOTA-SAFE FETCH (qualifiers 2022–2024)")
    print("=" * 60)

    matches, used = fetch_quota_safe()
    path = save_fetched_matches(matches)
    print(f"  Saved {len(matches)} matches -> {path}")
    print(f"  API calls used: {used}/{DEFAULT_BUDGET}")

    total = merge_matches(list(BUNDLED_NT_MATCHES), matches)
    print(f"  Total with bundled tournaments: {len(total)}")

    build_and_save_ratings()
    pushed = push_all()
    if pushed:
        print(f"  Cloud backup: {pushed} file(s) synced to Gist")
    print("=" * 60)


if __name__ == "__main__":
    main()
