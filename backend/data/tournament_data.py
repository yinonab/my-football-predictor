"""Tournament snapshot datasets for multi-tournament shadow backtests (Phase 2C)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.copa2024 import COPA2024_FIFA_ELO, COPA2024_MATCHES
from data.database import FIFA_ELO_2026, compute_derived_metrics
from data.euro2024 import EURO2024_FIFA_ELO, EURO2024_MATCHES
from data.nt_match import registry_key_for_nt
from data.wc2018 import WC2018_FIFA_ELO, WC2018_MATCHES
from data.wc2022 import WC2022_FIFA_ELO, WC2022_MATCHES
from data.wc2026_qualifiers import WC2026_QUALIFIER_MATCHES


@dataclass(frozen=True)
class BacktestMatch:
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True


@dataclass(frozen=True)
class TournamentDataset:
    key: str
    label: str
    matches: tuple[BacktestMatch, ...]
    elo_map: dict[str, int]
    rating_mode: str  # "pre_tournament_snapshot" | "live_snapshot"


class TournamentSnapshotDataManager:
    """Minimal team registry from a fixed pre-tournament Elo snapshot."""

    def __init__(self, elo_map: dict[str, int]) -> None:
        self.team_database: dict[str, dict[str, float]] = {
            name: compute_derived_metrics(float(elo))
            for name, elo in elo_map.items()
        }

    def get_team_data(self, team_name: str, *, use_live: bool = False) -> dict[str, Any]:
        if team_name not in self.team_database:
            raise KeyError(f"Unknown team in tournament snapshot: {team_name}")
        return self.team_database[team_name]

    def list_teams(self) -> list[str]:
        return list(self.team_database.keys())


def _to_backtest_matches(matches: tuple, *, default_neutral: bool = True) -> tuple[BacktestMatch, ...]:
    out: list[BacktestMatch] = []
    for match in matches:
        neutral = getattr(match, "neutral", default_neutral)
        out.append(
            BacktestMatch(
                home=match.home,
                away=match.away,
                home_goals=match.home_goals,
                away_goals=match.away_goals,
                neutral=neutral,
            )
        )
    return tuple(out)


def _qualifier_elo_map() -> dict[str, int]:
    registry = set(FIFA_ELO_2026.keys())
    elo: dict[str, int] = {}
    for match in WC2026_QUALIFIER_MATCHES:
        for name in (match.home, match.away):
            if name in elo:
                continue
            key = registry_key_for_nt(name, registry)
            if key:
                elo[name] = int(FIFA_ELO_2026[key])
            else:
                elo[name] = 1500
    return elo


def _qualifier_matches() -> tuple[BacktestMatch, ...]:
    return tuple(
        BacktestMatch(
            home=q.home,
            away=q.away,
            home_goals=q.home_goals,
            away_goals=q.away_goals,
            neutral=True,
        )
        for q in WC2026_QUALIFIER_MATCHES
    )


# CLI --dataset keys → bundled tournament modules
DATASET_REGISTRY: dict[str, TournamentDataset] = {
    "wc2018": TournamentDataset(
        key="wc2018",
        label="WC 2018",
        matches=_to_backtest_matches(WC2018_MATCHES),
        elo_map=dict(WC2018_FIFA_ELO),
        rating_mode="pre_tournament_snapshot",
    ),
    "wc2022": TournamentDataset(
        key="wc2022",
        label="WC 2022",
        matches=_to_backtest_matches(WC2022_MATCHES),
        elo_map=dict(WC2022_FIFA_ELO),
        rating_mode="pre_tournament_snapshot",
    ),
    "euro2024": TournamentDataset(
        key="euro2024",
        label="Euro 2024",
        matches=_to_backtest_matches(EURO2024_MATCHES),
        elo_map=dict(EURO2024_FIFA_ELO),
        rating_mode="pre_tournament_snapshot",
    ),
    "copa2024": TournamentDataset(
        key="copa2024",
        label="Copa America 2024",
        matches=_to_backtest_matches(COPA2024_MATCHES),
        elo_map=dict(COPA2024_FIFA_ELO),
        rating_mode="pre_tournament_snapshot",
    ),
    "qualifiers2026": TournamentDataset(
        key="qualifiers2026",
        label="WC 2026 Qualifiers",
        matches=_qualifier_matches(),
        elo_map=_qualifier_elo_map(),
        rating_mode="live_snapshot",
    ),
}

DATASET_ALIASES: dict[str, str] = {
    "wc18": "wc2018",
    "wc22": "wc2022",
    "euro24": "euro2024",
    "copa24": "copa2024",
    "qualifiers": "qualifiers2026",
}


def resolve_dataset_key(name: str) -> str:
    key = name.strip().lower()
    if key in DATASET_ALIASES:
        return DATASET_ALIASES[key]
    if key not in DATASET_REGISTRY and key != "all":
        known = ", ".join(sorted([*DATASET_REGISTRY.keys(), "all"]))
        raise ValueError(f"Unknown dataset '{name}'. Known: {known}")
    return key


def get_dataset(name: str) -> TournamentDataset | None:
    key = resolve_dataset_key(name)
    if key == "all":
        return None
    return DATASET_REGISTRY[key]


def list_dataset_keys() -> list[str]:
    return list(DATASET_REGISTRY.keys())


def combined_all_matches() -> tuple[BacktestMatch, ...]:
    matches: list[BacktestMatch] = []
    for ds in DATASET_REGISTRY.values():
        matches.extend(ds.matches)
    return tuple(matches)


def dataset_documentation() -> dict[str, str]:
    return {
        "wc2018": "data/wc2018.py — WC2018_MATCHES + WC2018_FIFA_ELO (pre-tournament)",
        "wc2022": "data/wc2022.py — WC2022_MATCHES + WC2022_FIFA_ELO (pre-tournament)",
        "euro2024": "data/euro2024.py — EURO2024_MATCHES + EURO2024_FIFA_ELO",
        "copa2024": "data/copa2024.py — COPA2024_MATCHES + COPA2024_FIFA_ELO",
        "qualifiers2026": "data/wc2026_qualifiers.py + FIFA_ELO_2026 registry (live snapshot)",
        "all": "Concatenation of all datasets above",
    }
