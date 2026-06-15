"""Persist World Cup 2026 match results entered after kickoff."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from data.nt_match import NationalTeamMatch

logger = logging.getLogger(__name__)

LIVE_MATCHES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "cache" / "wc2026_live_matches.json"
)


def load_live_matches(path: Path | None = None) -> list[NationalTeamMatch]:
    path = path or LIVE_MATCHES_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [NationalTeamMatch.from_dict(item) for item in payload.get("matches", [])]
    except Exception as exc:
        logger.warning("Failed to load live WC matches: %s", exc)
        return []


def save_live_matches(matches: list[NationalTeamMatch], path: Path | None = None) -> Path:
    path = path or LIVE_MATCHES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "competition": "FIFA World Cup 2026",
        "match_count": len(matches),
        "matches": [m.to_dict() for m in matches],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_live_match(
    *,
    home_key: str,
    away_key: str,
    home_goals: int,
    away_goals: int,
    neutral: bool = True,
    match_date: str | None = None,
) -> NationalTeamMatch:
    """Append a finished WC 2026 match; dedupe by date/home/away/score."""
    match = NationalTeamMatch(
        date=match_date or date.today().isoformat(),
        home=home_key,
        away=away_key,
        home_goals=home_goals,
        away_goals=away_goals,
        neutral=neutral,
        competition="FIFA World Cup 2026",
        weight=1.0,
    )
    existing = load_live_matches()
    key = (
        match.date,
        match.home.lower(),
        match.away.lower(),
        match.home_goals,
        match.away_goals,
    )
    for item in existing:
        if (
            item.date,
            item.home.lower(),
            item.away.lower(),
            item.home_goals,
            item.away_goals,
        ) == key:
            return item

    existing.append(match)
    save_live_matches(existing)
    logger.info(
        "Recorded live match: %s %d-%d %s (%d total)",
        home_key,
        home_goals,
        away_goals,
        away_key,
        len(existing),
    )
    return match
