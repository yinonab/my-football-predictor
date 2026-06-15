"""Blowout adjustment for heavy mismatches (e.g. Germany 7-1, Spain 5-1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BlowoutAdjustment:
    home_xg: float
    away_xg: float
    alpha: float
    max_goals: int
    active: bool
    note: str = ""


def apply_blowout_adjustment(
    home_xg: float,
    away_xg: float,
    home_power: float,
    away_power: float,
    advantage: float,
    *,
    base_alpha: float = 0.0,
    gap_start: float = 180.0,
    gap_full: float = 450.0,
) -> BlowoutAdjustment:
    """
    When Elo/power gap is extreme, inflate favorite xG and variance so 4-0, 5-1,
    7-1 style scorelines get meaningful probability mass.
    """
    gap = home_power - away_power + advantage
    abs_gap = abs(gap)
    if abs_gap < gap_start:
        return BlowoutAdjustment(
            home_xg=home_xg,
            away_xg=away_xg,
            alpha=base_alpha,
            max_goals=6,
            active=False,
        )

    t = min(1.0, (abs_gap - gap_start) / max(gap_full - gap_start, 1.0))

    if gap >= 0:
        fav_xg, dog_xg = home_xg, away_xg
    else:
        fav_xg, dog_xg = away_xg, home_xg

    # Target favorite lambda up to ~4.2; allow underdog ~0.5-1.0 (5-1 not 7-0 only)
    fav_target = 2.8 + t * 1.6
    fav_xg = fav_xg + t * max(0.0, fav_target - fav_xg)
    dog_xg = max(0.45, dog_xg * (1.0 - 0.25 * t) + 0.15 * t)

    if gap >= 0:
        home_adj, away_adj = fav_xg, dog_xg
        fav_label = "home"
    else:
        home_adj, away_adj = dog_xg, fav_xg
        fav_label = "away"

    alpha = max(base_alpha, 0.08 + 0.22 * t)
    max_goals = 8 if t >= 0.35 else 7 if t > 0 else 6

    note = (
        f"מצב גולנט ({abs_gap:.0f} נק' פער): xG מורחב {round(home_adj, 2)}-{round(away_adj, 2)} "
        f"— תוצאות 4-0 עד 6+ שערים אפשריות"
    )

    return BlowoutAdjustment(
        home_xg=round(home_adj, 2),
        away_xg=round(away_adj, 2),
        alpha=round(alpha, 3),
        max_goals=max_goals,
        active=True,
        note=note if fav_label == "home" else note.replace("מורחב", "מורחב (חוץ)"),
    )
