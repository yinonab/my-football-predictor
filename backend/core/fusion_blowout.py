"""Fusion blowout — xG uplift from blended 1X2, market, weather, and power gap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.blowout import BlowoutAdjustment

FavoriteSide = Literal["home", "away"]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _favorite_from_1x2(probs: dict[str, float]) -> tuple[str, float, float]:
    keys = ("home_win", "draw", "away_win")
    ordered = sorted(keys, key=lambda k: float(probs.get(k, 0.0)), reverse=True)
    favorite = ordered[0]
    underdog = ordered[2]
    return favorite, float(probs.get(favorite, 0.0)), float(probs.get(underdog, 0.0))


@dataclass(frozen=True)
class FusionBlowoutSignal:
    blowout_t: float
    favorite_side: FavoriteSide
    favorite_outcome: str
    favorite_probability: float
    underdog_probability: float
    margin_pp: float
    weather_factor: float
    triggers: list[str] = field(default_factory=list)
    suppressed_by: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.blowout_t >= 0.08

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "blowout_t": round(self.blowout_t, 4),
            "favorite_side": self.favorite_side,
            "favorite_outcome": self.favorite_outcome,
            "favorite_probability": round(self.favorite_probability, 2),
            "underdog_probability": round(self.underdog_probability, 2),
            "margin_pp": round(self.margin_pp, 2),
            "weather_factor": round(self.weather_factor, 4),
            "triggers": list(self.triggers),
            "suppressed_by": list(self.suppressed_by),
        }


def compute_fusion_blowout_signal(
    final_probabilities_1x2: dict[str, float],
    market_probabilities_1x2: dict[str, float] | None,
    *,
    power_gap: float,
    weather_xg_delta: float = 0.0,
) -> FusionBlowoutSignal:
    """
    Build blowout intensity from user-visible blended 1X2 and context.

    power_gap = final_home_power - final_away_power (signed).
    """
    fav_outcome, fav_prob, dog_prob = _favorite_from_1x2(final_probabilities_1x2)
    margin_pp = fav_prob - dog_prob
    favorite_side: FavoriteSide = "home" if fav_outcome == "home_win" else "away"

    triggers: list[str] = []
    suppressed: list[str] = []

    margin_t = _clamp((margin_pp - 20.0) / 55.0)
    if margin_pp >= 35.0:
        triggers.append("BLENDED_MARGIN_WIDE")
    if fav_prob >= 68.0:
        triggers.append("STRONG_FAVORITE_PROB")

    market_t = 0.0
    if market_probabilities_1x2:
        m_fav, m_prob, _ = _favorite_from_1x2(market_probabilities_1x2)
        if m_fav == fav_outcome and m_prob > fav_prob + 3.0:
            market_t = _clamp((m_prob - fav_prob) / 25.0)
            triggers.append("MARKET_CONFIRMS_FAVORITE")

    power_t = _clamp(abs(power_gap) / 220.0) * 0.45
    if abs(power_gap) >= 100.0:
        triggers.append("POWER_GAP_ELEVATED")

    weather_factor = 1.0
    if weather_xg_delta < -0.05:
        weather_factor = _clamp(1.0 + weather_xg_delta / 0.28, 0.55, 1.0)
        suppressed.append("WEATHER_REDUCES_GOAL_VOLUME")

    blowout_t = _clamp((0.58 * margin_t + 0.27 * market_t + power_t) * weather_factor)
    if fav_prob < 58.0:
        blowout_t *= 0.5
        suppressed.append("FAVORITE_PROB_BELOW_THRESHOLD")

    return FusionBlowoutSignal(
        blowout_t=blowout_t,
        favorite_side=favorite_side,
        favorite_outcome=fav_outcome,
        favorite_probability=fav_prob,
        underdog_probability=dog_prob,
        margin_pp=margin_pp,
        weather_factor=weather_factor,
        triggers=triggers,
        suppressed_by=suppressed,
    )


def apply_fusion_blowout(
    home_xg: float,
    away_xg: float,
    signal: FusionBlowoutSignal,
    *,
    base_alpha: float = 0.0,
) -> BlowoutAdjustment:
    """Inflate favorite xG when fusion signal is strong (regenerates score matrix)."""
    if not signal.active:
        return BlowoutAdjustment(
            home_xg=home_xg,
            away_xg=away_xg,
            alpha=base_alpha,
            max_goals=6,
            active=False,
            note="",
        )

    t = signal.blowout_t
    if signal.favorite_side == "home":
        fav_xg, dog_xg = home_xg, away_xg
    else:
        fav_xg, dog_xg = away_xg, home_xg

    fav_target = 2.75 + t * 2.05
    fav_xg = fav_xg + t * max(0.0, fav_target - fav_xg)
    dog_floor = 0.45 + 0.35 * t
    dog_xg = max(dog_floor, dog_xg * (1.0 - 0.12 * t))

    if signal.favorite_side == "home":
        home_adj, away_adj = fav_xg, dog_xg
        side_note = "בית"
    else:
        home_adj, away_adj = dog_xg, fav_xg
        side_note = "חוץ"

    alpha = max(base_alpha, 0.08 + 0.24 * t)
    max_goals = 8 if t >= 0.45 else 7 if t >= 0.2 else 6

    note = (
        f"גולנט משולב ({signal.margin_pp:.0f}% פער, t={t:.2f}): "
        f"xG {round(home_adj, 2)}-{round(away_adj, 2)} ({side_note} מועדף) — "
        "מטריצת תוצאות מחושבת מחדש"
    )

    return BlowoutAdjustment(
        home_xg=round(home_adj, 2),
        away_xg=round(away_adj, 2),
        alpha=round(alpha, 3),
        max_goals=max_goals,
        active=True,
        note=note,
    )
