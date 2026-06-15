"""Compute per-team attack/defense/form/Elo from national-team match history."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.elo_updater import update_elo_pair
from core.h2h_adjustment import build_h2h_index, save_h2h_index
from core.match_store import load_live_matches
from data.database import FIFA_ELO_2026, compute_derived_metrics
from data.nt_history_bundle import BUNDLED_NT_MATCHES
from data.nt_match import NationalTeamMatch, registry_key_for_nt
from data.wc2018 import WC2018_FIFA_ELO
from data.wc2022 import WC2022_FIFA_ELO

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
RATINGS_PATH = CACHE_DIR / "nt_ratings.json"
FETCHED_HISTORY_PATH = CACHE_DIR / "nt_history_fetched.json"


@dataclass
class TeamRating:
    elo: float
    attack: float
    defense: float
    form: float
    matches_used: int
    goals_for_per_game: float
    goals_against_per_game: float
    rating_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _initial_elo(registry_key: str) -> float:
    english = registry_key.split(" (")[0]
    if english in WC2018_FIFA_ELO:
        return float(WC2018_FIFA_ELO[english])
    if english in WC2022_FIFA_ELO:
        return float(WC2022_FIFA_ELO[english])
    return float(FIFA_ELO_2026[registry_key])


def _match_points(goals_for: int, goals_against: int) -> float:
    if goals_for > goals_against:
        return 3.0
    if goals_for == goals_against:
        return 1.0
    return 0.0


def _to_scale(value: float, *, low: float = 0.05, high: float = 0.95) -> float:
    return round(max(low, min(high, value)), 2)


class TeamRatingsCalculator:
    """Maher-style strengths + chronological Elo replay on NT matches."""

    def __init__(
        self,
        registry_keys: set[str] | None = None,
        *,
        elo_blend_current: float = 0.55,
    ) -> None:
        self.registry_keys = registry_keys or set(FIFA_ELO_2026.keys())
        self.elo_blend_current = elo_blend_current

    def compute(self, matches: list[NationalTeamMatch]) -> dict[str, TeamRating]:
        sorted_matches = sorted(matches, key=lambda m: (m.date, m.home, m.away))
        elos = {key: _initial_elo(key) for key in self.registry_keys}

        weighted_gf: dict[str, float] = defaultdict(float)
        weighted_ga: dict[str, float] = defaultdict(float)
        weighted_n: dict[str, float] = defaultdict(float)
        form_history: dict[str, list[float]] = defaultdict(list)

        total_goals = 0.0
        total_team_slots = 0.0

        for match in sorted_matches:
            home_key = registry_key_for_nt(match.home, self.registry_keys)
            away_key = registry_key_for_nt(match.away, self.registry_keys)
            if not home_key or not away_key:
                continue

            weight = match.weight
            advantage = 0.0 if match.neutral else 0.0

            new_home, new_away, _ = update_elo_pair(
                elos[home_key],
                elos[away_key],
                match.home_goals,
                match.away_goals,
                k=32.0 * weight,
                home_advantage=advantage,
            )
            elos[home_key] = new_home
            elos[away_key] = new_away

            for key, gf, ga in (
                (home_key, match.home_goals, match.away_goals),
                (away_key, match.away_goals, match.home_goals),
            ):
                weighted_gf[key] += gf * weight
                weighted_ga[key] += ga * weight
                weighted_n[key] += weight
                form_history[key].append(_match_points(gf, ga))

            total_goals += (match.home_goals + match.away_goals) * weight
            total_team_slots += 2.0 * weight

        league_avg_gf = total_goals / total_team_slots if total_team_slots else 1.35

        ratings: dict[str, TeamRating] = {}
        for key in self.registry_keys:
            baseline = compute_derived_metrics(FIFA_ELO_2026[key])
            matches_used = int(round(weighted_n.get(key, 0.0)))

            if matches_used == 0:
                ratings[key] = TeamRating(
                    elo=baseline["elo"],
                    attack=baseline["attack"],
                    defense=baseline["defense"],
                    form=baseline["form"],
                    matches_used=0,
                    goals_for_per_game=0.0,
                    goals_against_per_game=0.0,
                    rating_source="fifa_baseline",
                )
                continue

            avg_gf = weighted_gf[key] / weighted_n[key]
            avg_ga = weighted_ga[key] / weighted_n[key]

            attack_ratio = avg_gf / max(league_avg_gf, 0.5)
            defense_ratio = league_avg_gf / max(avg_ga, 0.35)

            attack = _to_scale(0.12 + attack_ratio * 0.38)
            defense = _to_scale(0.12 + defense_ratio * 0.35)

            recent = form_history[key][-10:]
            form = _to_scale(0.08 + (sum(recent) / (len(recent) * 3.0)) * 0.87)

            replayed_elo = elos[key]
            current_elo = float(FIFA_ELO_2026[key])
            blended_elo = round(
                self.elo_blend_current * current_elo
                + (1.0 - self.elo_blend_current) * replayed_elo,
                1,
            )

            ratings[key] = TeamRating(
                elo=blended_elo,
                attack=attack,
                defense=defense,
                form=form,
                matches_used=matches_used,
                goals_for_per_game=round(avg_gf, 2),
                goals_against_per_game=round(avg_ga, 2),
                rating_source="history_blend",
            )

        return ratings


def load_fetched_matches(path: Path | None = None) -> list[NationalTeamMatch]:
    path = path or FETCHED_HISTORY_PATH
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [NationalTeamMatch.from_dict(item) for item in payload.get("matches", [])]


def merge_matches(
    *sources: list[NationalTeamMatch],
) -> list[NationalTeamMatch]:
    """Deduplicate by date/home/away/score."""
    seen: set[tuple[str, str, str, int, int]] = set()
    merged: list[NationalTeamMatch] = []
    for batch in sources:
        for match in batch:
            key = (
                match.date,
                match.home.lower(),
                match.away.lower(),
                match.home_goals,
                match.away_goals,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(match)
    return merged


def build_all_matches() -> list[NationalTeamMatch]:
    return merge_matches(
        list(BUNDLED_NT_MATCHES),
        load_fetched_matches(),
        load_live_matches(),
    )


def save_ratings(ratings: dict[str, TeamRating], path: Path | None = None) -> Path:
    path = path or RATINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "match_count": len(build_all_matches()),
        "teams": {key: rating.to_dict() for key, rating in ratings.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_ratings(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or RATINGS_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("teams", {})


def build_and_save_ratings() -> dict[str, TeamRating]:
    matches = build_all_matches()
    calculator = TeamRatingsCalculator()
    ratings = calculator.compute(matches)
    save_ratings(ratings)
    h2h_index = build_h2h_index(matches)
    save_h2h_index(h2h_index)
    logger.info(
        "Saved ratings for %d teams and %d H2H pairs from %d matches",
        len(ratings),
        len(h2h_index),
        len(matches),
    )
    return ratings
