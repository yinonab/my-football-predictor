#!/usr/bin/env python3
"""Phase 4X — football-data.org connectivity diagnostic (never prints token)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from data.football_data import (
    KEY_MISSING,
    NETWORK_ERROR,
    OK,
    RATE_LIMITED,
    UNAUTHORIZED,
    WC_NOT_AVAILABLE,
    FootballDataClient,
)

SELECTED_MATCHUPS: list[tuple[str, str]] = [
    ("Canada", "Qatar"),
    ("USA", "Australia"),
    ("Mexico", "South Korea"),
    ("Switzerland", "Canada"),
]


def _classify(client: FootballDataClient, exc: Exception | None = None) -> str:
    if not client.key_present:
        return KEY_MISSING
    if exc is not None:
        msg = str(exc)
        if msg in (KEY_MISSING, UNAUTHORIZED, RATE_LIMITED, NETWORK_ERROR, WC_NOT_AVAILABLE):
            return msg
        return NETWORK_ERROR
    code = client.last_error_code
    return code or OK


def _score_label(match: dict) -> str:
    score = match.get("score") or {}
    ft = score.get("fullTime") or {}
    h, a = ft.get("home"), ft.get("away")
    if h is None or a is None:
        return "-"
    return f"{h}-{a}"


def _find_match(matches: list[dict], home: str, away: str) -> dict | None:
    from core.football_data_fixture import find_football_data_match

    return find_football_data_match(matches, home, away)


def _print_match_row(label: str, match: dict | None) -> None:
    if not match:
        print(f"  {label}: NOT FOUND")
        return
    print(
        f"  {label}: status={match.get('status')} "
        f"kickoff={match.get('utcDate')} score={_score_label(match)} "
        f"group={match.get('group')} stage={match.get('stage')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose football-data.org WC access")
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    client = FootballDataClient()
    print(f"football-data enabled={client.enabled} key_present={client.key_present}")

    if not client.is_available:
        print(f"result={KEY_MISSING}")
        return 1

    try:
        competitions = client.get_competitions()
    except Exception as exc:
        result = _classify(client, exc)
        print(f"competitions: ERROR ({result})")
        print(f"result={result}")
        return 1

    wc = next((c for c in competitions if (c.get("code") or "").upper() == "WC"), None)
    if not wc:
        print(f"competitions: {len(competitions)} (WC not listed)")
        print(f"result={WC_NOT_AVAILABLE}")
        return 1

    print(
        f"competitions: OK — WC id={wc.get('id')} "
        f"currentSeason={wc.get('currentSeason', {}).get('startDate')} "
        f"to {wc.get('currentSeason', {}).get('endDate')}"
    )

    try:
        matches = client.get_world_cup_matches(season=args.season)
    except Exception as exc:
        result = _classify(client, exc)
        print(f"matches: ERROR ({result})")
        print(f"result={result}")
        return 1

    print(f"matches: {len(matches)} for season={args.season}")
    for home, away in SELECTED_MATCHUPS:
        found = _find_match(matches, home, away)
        _print_match_row(f"{home} vs {away}", found)

    print(f"result={OK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
