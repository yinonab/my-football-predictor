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

    def get_power_component_diagnostics(
        self,
        team_name: str,
        *,
        use_live: bool = False,
        h2h_component: float | None = None,
        context_component: float | None = None,
        modifier_component: float | None = None,
    ) -> dict[str, object]:
        """Diagnostics-only power decomposition — does not alter composite Power."""
        raw = self._dm.get_team_data(team_name, use_live=use_live)
        elo = float(raw.get("elo", 1500.0))
        form = float(raw.get("form", 0.5))
        attack = float(raw.get("attack", 0.5))
        defense = float(raw.get("defense", 0.5))

        elo_c = config.WEIGHT_ELO * elo
        form_c = config.WEIGHT_FORM * form * 1000.0
        attack_c = config.WEIGHT_ATTACK * attack * 1000.0
        defense_c = -config.WEIGHT_DEFENSE * defense * 1000.0

        base_total = elo_c + form_c + attack_c + defense_c
        extra = sum(
            x for x in (h2h_component, context_component, modifier_component) if x is not None
        )
        total_power = base_total + extra

        from core.global_ratings import compute_opponent_adjusted_form

        adj_form, avg_opp, opp_n, _ = compute_opponent_adjusted_form(team_name, form)

        return {
            "team": team_name,
            "total_power": round(total_power, 2),
            "internal_elo": round(elo, 1),
            "components": {
                "elo_component": round(elo_c, 2),
                "form_component": round(form_c, 2),
                "attack_component": round(attack_c, 2),
                "defense_component": round(defense_c, 2),
                "h2h_component": round(h2h_component, 2) if h2h_component is not None else None,
                "context_component": (
                    round(context_component, 2) if context_component is not None else None
                ),
                "modifier_component": (
                    round(modifier_component, 2) if modifier_component is not None else None
                ),
            },
            "raw_inputs": {
                "form": round(form, 3),
                "attack": round(attack, 3),
                "defense": round(defense, 3),
                "gf": raw.get("goals_for_per_game"),
                "ga": raw.get("goals_against_per_game"),
                "matches_count": raw.get("matches_used"),
                "avg_opponent_elo": avg_opp,
                "opponent_adjusted_form": adj_form,
            },
            "weights": {
                "elo": config.WEIGHT_ELO,
                "form": config.WEIGHT_FORM,
                "attack": config.WEIGHT_ATTACK,
                "defense": config.WEIGHT_DEFENSE,
            },
        }
