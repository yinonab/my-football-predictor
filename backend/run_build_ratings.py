"""Rebuild nt_ratings.json from bundled + cached API history."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.team_ratings import RATINGS_PATH, build_all_matches, build_and_save_ratings  # noqa: E402


def main() -> None:
    matches = build_all_matches()
    ratings = build_and_save_ratings()
    with_history = sum(1 for r in ratings.values() if r.matches_used > 0)
    print("=" * 60)
    print("  BUILD NT RATINGS")
    print("=" * 60)
    print(f"  Matches used:     {len(matches)}")
    print(f"  Teams rated:      {len(ratings)}")
    print(f"  With history:     {with_history}")
    print(f"  Output:           {RATINGS_PATH}")
    print("=" * 60)
    print("\n  Top attack (history):")
    top_attack = sorted(
        ratings.items(),
        key=lambda item: item[1].attack,
        reverse=True,
    )[:5]
    for name, rating in top_attack:
        if rating.matches_used:
            print(
                f"    {name.split(' (')[0]:12}  atk={rating.attack}  "
                f"def={rating.defense}  n={rating.matches_used}"
            )


if __name__ == "__main__":
    main()
