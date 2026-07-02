"""Matchup-relative feature vector for experimental xG candidate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.maher import estimate_xg_pair


def _clamp01(value: float | None, *, default: float = 0.5) -> float:
    if value is None:
        return default
    return max(0.0, min(1.0, float(value)))


def _maher_confidence(
    *,
    home_gf: float | None,
    home_ga: float | None,
    away_gf: float | None,
    away_ga: float | None,
) -> float:
    values = [home_gf, home_ga, away_gf, away_ga]
    present = sum(1 for v in values if v is not None and float(v) > 0.0)
    if present >= 4:
        return 1.0
    if present >= 2:
        return 0.55
    return 0.25


@dataclass
class MatchupFeatureVector:
    home_team: str
    away_team: str
    home_power: float
    away_power: float
    power_gap: float
    power_gap_abs: float
    favorite_side: str
    underdog_side: str

    home_attack_rating: float
    home_defense_rating: float
    away_attack_rating: float
    away_defense_rating: float

    home_attack_vs_defense_edge: float
    away_attack_vs_defense_edge: float
    favorite_attack_edge: float
    underdog_attack_edge: float
    favorite_defense_rating: float
    underdog_defense_rating: float
    favorite_attack_rating: float
    underdog_attack_rating: float

    strength_home_xg: float
    strength_away_xg: float
    maher_home_xg: float
    maher_away_xg: float
    maher_favorite_xg: float | None
    maher_underdog_xg: float | None

    data_confidence: float
    rating_confidence: float
    maher_confidence: float
    attack_defense_confidence: float

    baseline_home_xg: float
    baseline_away_xg: float
    inflation_flags: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "power_gap": round(self.power_gap, 2),
            "favorite_side": self.favorite_side,
            "underdog_side": self.underdog_side,
            "attack_vs_defense_edges": {
                "home": round(self.home_attack_vs_defense_edge, 4),
                "away": round(self.away_attack_vs_defense_edge, 4),
                "favorite": round(self.favorite_attack_edge, 4),
                "underdog": round(self.underdog_attack_edge, 4),
            },
            "ratings": {
                "home_attack": round(self.home_attack_rating, 4),
                "home_defense": round(self.home_defense_rating, 4),
                "away_attack": round(self.away_attack_rating, 4),
                "away_defense": round(self.away_defense_rating, 4),
            },
            "strength_xg": {
                "home": round(self.strength_home_xg, 3),
                "away": round(self.strength_away_xg, 3),
            },
            "maher_xg": {
                "home": round(self.maher_home_xg, 3),
                "away": round(self.maher_away_xg, 3),
            },
            "confidence": {
                "data": round(self.data_confidence, 3),
                "rating": round(self.rating_confidence, 3),
                "maher": round(self.maher_confidence, 3),
                "attack_defense": round(self.attack_defense_confidence, 3),
            },
            "baseline_xg": {
                "home": round(self.baseline_home_xg, 3),
                "away": round(self.baseline_away_xg, 3),
            },
            "inflation_flags": list(self.inflation_flags),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_matchup_feature_vector(
    *,
    home_team: str,
    away_team: str,
    home_power: float,
    away_power: float,
    home_attack: float | None,
    home_defense: float | None,
    away_attack: float | None,
    away_defense: float | None,
    home_gf_per_game: float | None,
    home_ga_per_game: float | None,
    away_gf_per_game: float | None,
    away_ga_per_game: float | None,
    strength_home_xg: float,
    strength_away_xg: float,
    baseline_home_xg: float,
    baseline_away_xg: float,
    global_avg: float = 2.6,
) -> MatchupFeatureVector:
    home_attack_rating = _clamp01(home_attack, default=0.5)
    home_defense_rating = _clamp01(home_defense, default=0.5)
    away_attack_rating = _clamp01(away_attack, default=0.5)
    away_defense_rating = _clamp01(away_defense, default=0.5)

    home_attack_vs_defense_edge = home_attack_rating * (1.0 - away_defense_rating)
    away_attack_vs_defense_edge = away_attack_rating * (1.0 - home_defense_rating)

    power_gap = float(home_power) - float(away_power)
    power_gap_abs = abs(power_gap)
    if power_gap >= 0:
        favorite_side, underdog_side = "home", "away"
        favorite_attack_edge = home_attack_vs_defense_edge
        underdog_attack_edge = away_attack_vs_defense_edge
        favorite_defense_rating = home_defense_rating
        underdog_defense_rating = away_defense_rating
        favorite_attack_rating = home_attack_rating
        underdog_attack_rating = away_attack_rating
    else:
        favorite_side, underdog_side = "away", "home"
        favorite_attack_edge = away_attack_vs_defense_edge
        underdog_attack_edge = home_attack_vs_defense_edge
        favorite_defense_rating = away_defense_rating
        underdog_defense_rating = home_defense_rating
        favorite_attack_rating = away_attack_rating
        underdog_attack_rating = home_attack_rating

    maher_home_xg, maher_away_xg = estimate_xg_pair(
        home_gf_per_game or 0.0,
        home_ga_per_game or 0.0,
        away_gf_per_game or 0.0,
        away_ga_per_game or 0.0,
        global_avg=global_avg,
    )
    if favorite_side == "home":
        maher_favorite_xg, maher_underdog_xg = maher_home_xg, maher_away_xg
    else:
        maher_favorite_xg, maher_underdog_xg = maher_away_xg, maher_home_xg

    maher_confidence = _maher_confidence(
        home_gf=home_gf_per_game,
        home_ga=home_ga_per_game,
        away_gf=away_gf_per_game,
        away_ga=away_ga_per_game,
    )

    rating_values = [home_attack, home_defense, away_attack, away_defense]
    rating_present = sum(1 for v in rating_values if v is not None)
    rating_confidence = min(1.0, rating_present / 4.0)
    attack_defense_confidence = (
        1.0
        if all(v is not None for v in rating_values)
        else max(0.35, rating_present / 4.0)
    )
    data_confidence = round(
        0.45 * rating_confidence + 0.35 * maher_confidence + 0.20 * attack_defense_confidence,
        4,
    )

    inflation_flags: list[str] = []
    ud_baseline_xg = (
        baseline_away_xg if underdog_side == "away" else baseline_home_xg
    )
    if (
        power_gap_abs >= 250.0
        and underdog_attack_rating <= 0.20
        and favorite_defense_rating >= 0.70
        and ud_baseline_xg >= 0.75
    ):
        inflation_flags.append("WEAK_UNDERDOG_INFLATION_SUSPECT")

    return MatchupFeatureVector(
        home_team=home_team,
        away_team=away_team,
        home_power=float(home_power),
        away_power=float(away_power),
        power_gap=power_gap,
        power_gap_abs=power_gap_abs,
        favorite_side=favorite_side,
        underdog_side=underdog_side,
        home_attack_rating=home_attack_rating,
        home_defense_rating=home_defense_rating,
        away_attack_rating=away_attack_rating,
        away_defense_rating=away_defense_rating,
        home_attack_vs_defense_edge=home_attack_vs_defense_edge,
        away_attack_vs_defense_edge=away_attack_vs_defense_edge,
        favorite_attack_edge=favorite_attack_edge,
        underdog_attack_edge=underdog_attack_edge,
        favorite_defense_rating=favorite_defense_rating,
        underdog_defense_rating=underdog_defense_rating,
        favorite_attack_rating=favorite_attack_rating,
        underdog_attack_rating=underdog_attack_rating,
        strength_home_xg=float(strength_home_xg),
        strength_away_xg=float(strength_away_xg),
        maher_home_xg=float(maher_home_xg),
        maher_away_xg=float(maher_away_xg),
        maher_favorite_xg=float(maher_favorite_xg),
        maher_underdog_xg=float(maher_underdog_xg),
        data_confidence=data_confidence,
        rating_confidence=rating_confidence,
        maher_confidence=maher_confidence,
        attack_defense_confidence=attack_defense_confidence,
        baseline_home_xg=float(baseline_home_xg),
        baseline_away_xg=float(baseline_away_xg),
        inflation_flags=inflation_flags,
    )
