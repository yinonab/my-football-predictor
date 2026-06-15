"""Per-opponent attack/defense rates for Maher-style xG."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from data.nt_match import NationalTeamMatch, registry_key_for_nt


@dataclass(frozen=True)
class OpponentRates:
    goals_for_per_game: float
    goals_against_per_game: float
    matches: int


def build_opponent_index(
    matches: list[NationalTeamMatch],
    registry_keys: set[str],
) -> dict[tuple[str, str], OpponentRates]:
    """
    For each ordered pair (team, opponent), aggregate goals scored/conceded
    when team faced opponent (home or away).
    """
    gf: dict[tuple[str, str], float] = defaultdict(float)
    ga: dict[tuple[str, str], float] = defaultdict(float)
    n: dict[tuple[str, str], int] = defaultdict(int)

    for match in matches:
        home_key = registry_key_for_nt(match.home, registry_keys)
        away_key = registry_key_for_nt(match.away, registry_keys)
        if not home_key or not away_key or home_key == away_key:
            continue

        w = match.weight
        gf[(home_key, away_key)] += match.home_goals * w
        ga[(home_key, away_key)] += match.away_goals * w
        n[(home_key, away_key)] += 1

        gf[(away_key, home_key)] += match.away_goals * w
        ga[(away_key, home_key)] += match.home_goals * w
        n[(away_key, home_key)] += 1

    index: dict[tuple[str, str], OpponentRates] = {}
    for pair, count in n.items():
        if count <= 0:
            continue
        index[pair] = OpponentRates(
            goals_for_per_game=round(gf[pair] / count, 2),
            goals_against_per_game=round(ga[pair] / count, 2),
            matches=count,
        )
    return index


def _blend_rate(global_rate: float, opponent_rate: float, matches: int, *, cap: float = 0.65) -> float:
    if matches <= 0 or global_rate <= 0:
        return opponent_rate if matches > 0 else global_rate
    weight = min(matches / 4.0, cap)
    return global_rate * (1.0 - weight) + opponent_rate * weight


def estimate_xg_opponent_aware(
    home_key: str,
    away_key: str,
    home_gf: float,
    home_ga: float,
    away_gf: float,
    away_ga: float,
    opponent_index: dict[tuple[str, str], OpponentRates],
    *,
    global_avg: float = 3.0,
) -> tuple[float, float, str]:
    """
    Maher xG with optional per-opponent attack/defense blend.
    λ_home ≈ attack(home vs away) × defense_weakness(away vs home).
    """
    from core.maher import estimate_xg_pair

    base_home, base_away = estimate_xg_pair(
        home_gf,
        home_ga,
        away_gf,
        away_ga,
        global_avg=global_avg,
    )

    h_vs_a = opponent_index.get((home_key, away_key))
    a_vs_h = opponent_index.get((away_key, home_key))
    if not h_vs_a and not a_vs_h:
        return base_home, base_away, ""

    half = max(global_avg / 2.0, 0.5)
    h_gf = _blend_rate(home_gf or half, h_vs_a.goals_for_per_game if h_vs_a else half, h_vs_a.matches if h_vs_a else 0)
    h_ga = _blend_rate(home_ga or half, h_vs_a.goals_against_per_game if h_vs_a else half, h_vs_a.matches if h_vs_a else 0)
    a_gf = _blend_rate(away_gf or half, a_vs_h.goals_for_per_game if a_vs_h else half, a_vs_h.matches if a_vs_h else 0)
    a_ga = _blend_rate(away_ga or half, a_vs_h.goals_against_per_game if a_vs_h else half, a_vs_h.matches if a_vs_h else 0)

    opp_home, opp_away = estimate_xg_pair(h_gf, h_ga, a_gf, a_ga, global_avg=global_avg)

    blend = 0.0
    if h_vs_a:
        blend = max(blend, min(h_vs_a.matches / 4.0, 0.65))
    if a_vs_h:
        blend = max(blend, min(a_vs_h.matches / 4.0, 0.65))

    home_xg = round(base_home * (1.0 - blend) + opp_home * blend, 2)
    away_xg = round(base_away * (1.0 - blend) + opp_away * blend, 2)

    n = max(h_vs_a.matches if h_vs_a else 0, a_vs_h.matches if a_vs_h else 0)
    note = f"Maher לפי יריב ({n} מפגשים): xG {home_xg}-{away_xg}"
    return home_xg, away_xg, note
