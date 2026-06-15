"""Fetch national-team fixture history (2018–2026) via API-Football."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from data.api_football import ApiFootballClient  # noqa: E402
from data.database import FIFA_ELO_2026  # noqa: E402
from data.nt_match import NationalTeamMatch  # noqa: E402
from core.team_ratings import (  # noqa: E402
    FETCHED_HISTORY_PATH,
    build_and_save_ratings,
    merge_matches,
)
from data.nt_history_bundle import BUNDLED_NT_MATCHES  # noqa: E402

logger = logging.getLogger(__name__)

DATE_FROM = "2018-01-01"
DATE_TO = "2026-12-31"


def fetch_all_teams(
    *,
    client: ApiFootballClient | None = None,
    sleep_seconds: float = 0.35,
    include_qualifiers: bool = True,
) -> list[NationalTeamMatch]:
    api = client or ApiFootballClient()
    if not api.is_available:
        raise RuntimeError("API_FOOTBALL_KEY is not set — add it to backend/.env")

    collected: list[NationalTeamMatch] = []
    team_ids: dict[str, int] = {}

    if include_qualifiers:
        try:
            qual = api.fetch_all_qualifiers()
            collected.extend(qual)
            logger.info("Qualifier leagues: %d fixtures", len(qual))
        except Exception as exc:
            logger.warning("Qualifier fetch failed: %s", exc)

    for registry_key in FIFA_ELO_2026:
        english = registry_key.split(" (")[0]
        try:
            team = api.search_national_team(english)
            if not team:
                logger.warning("No API team found for %s", registry_key)
                continue
            team_ids[registry_key] = int(team["id"])
            fixtures = api.fetch_team_fixtures(team["id"], DATE_FROM, DATE_TO)
            for fx in fixtures:
                parsed = api.parse_fixture(fx)
                if parsed:
                    collected.append(parsed)
            logger.info("%s: %d fixtures", registry_key, len(fixtures))
        except Exception as exc:
            logger.warning("Fetch failed for %s: %s", registry_key, exc)
        time.sleep(sleep_seconds)

    merged = merge_matches(collected)
    logger.info("Fetched %d unique NT matches for %d teams", len(merged), len(team_ids))
    return merged


def save_fetched_matches(matches: list[NationalTeamMatch]) -> Path:
    FETCHED_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "match_count": len(matches),
        "matches": [m.to_dict() for m in matches],
    }
    FETCHED_HISTORY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return FETCHED_HISTORY_PATH


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=" * 60)
    print("  FETCH NT HISTORY (API-Football)")
    print("=" * 60)

    matches = fetch_all_teams()
    path = save_fetched_matches(matches)
    print(f"  Saved {len(matches)} matches → {path}")

    all_matches = merge_matches(list(BUNDLED_NT_MATCHES), matches)
    print(f"  Total with bundled tournaments: {len(all_matches)}")

    ratings_path = build_and_save_ratings()
    print(f"  Ratings rebuilt → {ratings_path.parent / 'nt_ratings.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
