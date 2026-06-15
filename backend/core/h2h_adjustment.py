"""Head-to-head history and power adjustments for national-team matchups."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data.database import FIFA_ELO_2026
from data.nt_match import NationalTeamMatch, registry_key_for_nt

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
H2H_INDEX_PATH = CACHE_DIR / "h2h_index.json"

MIN_H2H_MATCHES = 2
DEFAULT_BLEND = 0.08


@dataclass(frozen=True)
class H2HSummary:
    home_key: str
    away_key: str
    match_count: int
    avg_home_goals: float
    avg_away_goals: float
    avg_total_goals: float
    home_win_rate: float
    draw_rate: float
    away_win_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> H2HSummary:
        return cls(
            home_key=str(data["home_key"]),
            away_key=str(data["away_key"]),
            match_count=int(data["match_count"]),
            avg_home_goals=float(data["avg_home_goals"]),
            avg_away_goals=float(data["avg_away_goals"]),
            avg_total_goals=float(data["avg_total_goals"]),
            home_win_rate=float(data["home_win_rate"]),
            draw_rate=float(data["draw_rate"]),
            away_win_rate=float(data["away_win_rate"]),
        )


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def build_h2h_index(
    matches: list[NationalTeamMatch],
    registry_keys: set[str] | None = None,
) -> dict[str, H2HSummary]:
    """Build symmetric H2H summaries keyed by 'TeamA|TeamB' (sorted)."""
    registry_keys = registry_keys or set(FIFA_ELO_2026.keys())
    buckets: dict[tuple[str, str], list[tuple[str, str, int, int]]] = {}

    for match in matches:
        home_key = registry_key_for_nt(match.home, registry_keys)
        away_key = registry_key_for_nt(match.away, registry_keys)
        if not home_key or not away_key or home_key == away_key:
            continue
        key = _pair_key(home_key, away_key)
        buckets.setdefault(key, []).append(
            (home_key, away_key, match.home_goals, match.away_goals)
        )

    index: dict[str, H2HSummary] = {}
    for (team_a, team_b), rows in buckets.items():
        if len(rows) < MIN_H2H_MATCHES:
            continue

        home_goals_a = 0.0
        home_goals_b = 0.0
        home_wins = draws = away_wins = 0

        for home_key, away_key, hg, ag in rows:
            if home_key == team_a:
                home_goals_a += hg
                home_goals_b += ag
                if hg > ag:
                    home_wins += 1
                elif hg == ag:
                    draws += 1
                else:
                    away_wins += 1
            else:
                home_goals_a += ag
                home_goals_b += hg
                if ag > hg:
                    home_wins += 1
                elif hg == ag:
                    draws += 1
                else:
                    away_wins += 1

        n = len(rows)
        storage_key = f"{team_a}|{team_b}"
        index[storage_key] = H2HSummary(
            home_key=team_a,
            away_key=team_b,
            match_count=n,
            avg_home_goals=round(home_goals_a / n, 2),
            avg_away_goals=round(home_goals_b / n, 2),
            avg_total_goals=round((home_goals_a + home_goals_b) / n, 2),
            home_win_rate=round(home_wins / n, 2),
            draw_rate=round(draws / n, 2),
            away_win_rate=round(away_wins / n, 2),
        )

    return index


def lookup_h2h(
    index: dict[str, H2HSummary],
    home_key: str,
    away_key: str,
) -> H2HSummary | None:
    storage_key = "|".join(_pair_key(home_key, away_key))
    summary = index.get(storage_key)
    if not summary:
        return None

    if summary.home_key == home_key:
        return summary

    return H2HSummary(
        home_key=home_key,
        away_key=away_key,
        match_count=summary.match_count,
        avg_home_goals=summary.avg_away_goals,
        avg_away_goals=summary.avg_home_goals,
        avg_total_goals=summary.avg_total_goals,
        home_win_rate=summary.away_win_rate,
        draw_rate=summary.draw_rate,
        away_win_rate=summary.home_win_rate,
    )


def apply_h2h_adjustment(
    home_power: float,
    away_power: float,
    summary: H2HSummary | None,
    *,
    blend: float = DEFAULT_BLEND,
) -> tuple[float, float, str]:
    """
    Nudge composite power based on historical H2H goal share.
    Returns (home_power, away_power, Hebrew note).
    """
    if not summary or summary.match_count < MIN_H2H_MATCHES:
        return home_power, away_power, ""

    total = summary.avg_home_goals + summary.avg_away_goals
    if total <= 0:
        return home_power, away_power, ""

    home_share = summary.avg_home_goals / total
    delta = (home_share - 0.5) * 400.0 * blend
    note = (
        f"מפגשים ישירים ({summary.match_count}): "
        f"ממוצע {summary.avg_home_goals:.1f}-{summary.avg_away_goals:.1f} "
        f"(סה״כ {summary.avg_total_goals:.1f} שערים)"
    )
    return home_power + delta, away_power - delta, note


def save_h2h_index(index: dict[str, H2HSummary], path: Path | None = None) -> Path:
    path = path or H2H_INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "pair_count": len(index),
        "pairs": {key: summary.to_dict() for key, summary in index.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_h2h_index(path: Path | None = None) -> dict[str, H2HSummary]:
    path = path or H2H_INDEX_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    pairs = payload.get("pairs", {})
    return {key: H2HSummary.from_dict(value) for key, value in pairs.items()}


class H2HStore:
    """Loaded H2H index with lookup helpers."""

    def __init__(self, index: dict[str, H2HSummary] | None = None) -> None:
        self._index = index if index is not None else load_h2h_index()

    @classmethod
    def from_matches(cls, matches: list[NationalTeamMatch]) -> H2HStore:
        return cls(build_h2h_index(matches))

    def get(self, home_key: str, away_key: str) -> H2HSummary | None:
        return lookup_h2h(self._index, home_key, away_key)

    def pair_count(self) -> int:
        return len(self._index)
