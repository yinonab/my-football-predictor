"""Team power decomposition and environmental rule-based modifiers."""

from __future__ import annotations

import config
from data.database import LiveDataManager


class TeamPowerEvaluator:
    """Calculates composite power scores from decomposed team features."""

    def __init__(self, data_manager: LiveDataManager) -> None:
        self._dm = data_manager

    def calculate_composite_power(
        self,
        team_name: str,
        *,
        use_live: bool = False,
    ) -> float:
        raw = self._dm.get_team_data(team_name, use_live=use_live)
        power = (
            config.WEIGHT_ELO * raw["elo"]
            + config.WEIGHT_FORM * (raw["form"] * 1000)
            + config.WEIGHT_ATTACK * (raw["attack"] * 1000)
            - config.WEIGHT_DEFENSE * (raw["defense"] * 1000)
        )
        return float(power)

    def apply_environmental_modifiers(
        self,
        power: float,
        altitude: int = 0,
        star_absent: bool = False,
    ) -> float:
        """Rule-based environmental/tactical adjustments (not machine learning)."""
        modifier = 1.0
        if altitude > config.ALTITUDE_THRESHOLD_M:
            modifier -= config.ALTITUDE_PENALTY
        if star_absent:
            modifier -= config.STAR_ABSENT_PENALTY
        modifier = max(config.MIN_MODIFIER, min(config.MAX_MODIFIER, modifier))
        return power * modifier

    def get_team_breakdown(
        self,
        team_name: str,
        *,
        use_live: bool = False,
    ) -> dict[str, str | float]:
        raw = self._dm.get_team_data(team_name, use_live=use_live)
        power = self.calculate_composite_power(team_name, use_live=use_live)
        matches_used = raw.get("matches_used")
        extra = f" | מבוסס על {matches_used} משחקים" if matches_used else ""
        return {
            "name": team_name,
            "power_score": round(power, 2),
            "elo": raw["elo"],
            "breakdown": (
                f"התקפה: {raw['attack']} | הגנה: {raw['defense']} | "
                f"כושר: {raw['form']}{extra}"
            ),
        }
