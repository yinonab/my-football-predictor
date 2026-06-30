"""Priority 1 candidate configuration and shadow pipeline hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import config
from core.defense_audit import DefenseSign


@dataclass(frozen=True)
class Priority1Config:
    """Shadow/candidate switches — all default to production-safe values."""

    power_variant: str = "current"  # current | zscore_candidate
    zscore_defense_sign: DefenseSign = "subtract"
    xg_total_variant: str = "fixed"  # fixed | dynamic_candidate
    market_calibration_mode: str = "off"  # off | one_x_two_only | xg_candidate
    odds_affect_prediction: bool = False
    dataset_key: str | None = None
    stage: str | None = None
    weather_xg_delta: float = 0.0
    market_probs_pct: dict[str, float] | None = None
    market_total_goals: float | None = None
    books_count: int = 0
    dynamic_goals_tuning: Any | None = None
    tuning_label: str | None = None

    @classmethod
    def baseline(cls) -> Priority1Config:
        return cls()

    @classmethod
    def from_env(cls) -> Priority1Config:
        return cls(
            power_variant=config.POWER_MODEL_VARIANT,
            xg_total_variant=config.XG_TOTAL_GOALS_VARIANT,
            market_calibration_mode=config.MARKET_CALIBRATION_MODE,
            odds_affect_prediction=config.ODDS_AFFECT_PREDICTION,
        )

    @classmethod
    def zscore_candidate(cls, *, defense_sign: DefenseSign = "subtract") -> Priority1Config:
        return cls(power_variant="zscore_candidate", zscore_defense_sign=defense_sign)

    @classmethod
    def zscore_defense_current(cls) -> Priority1Config:
        return cls.zscore_candidate(defense_sign="subtract")

    @classmethod
    def zscore_defense_flipped(cls) -> Priority1Config:
        return cls.zscore_candidate(defense_sign="add")

    @classmethod
    def dynamic_goals_candidate(cls, *, tuning: Any | None = None, label: str | None = None) -> Priority1Config:
        return cls(
            xg_total_variant="dynamic_candidate",
            dynamic_goals_tuning=tuning,
            tuning_label=label,
        )

    @classmethod
    def market_xg_candidate(cls, *, odds_blend: bool = False) -> Priority1Config:
        return cls(
            market_calibration_mode="xg_candidate",
            odds_affect_prediction=odds_blend,
        )


PRIORITY1_VARIANTS: dict[str, Priority1Config] = {
    "baseline_current": Priority1Config.baseline(),
    "zscore_power_candidate": Priority1Config.zscore_candidate(),
    "dynamic_goals_candidate": Priority1Config.dynamic_goals_candidate(),
    "market_xg_candidate": Priority1Config.market_xg_candidate(),
    "market_xg_candidate_with_blend": Priority1Config.market_xg_candidate(
        odds_blend=True
    ),
}


def resolve_global_avg(
    *,
    base_avg: float,
    p1: Priority1Config,
    home_attack: float,
    home_defense: float,
    away_attack: float,
    away_defense: float,
    home_power: float,
    away_power: float,
    advantage: float,
    home_elo: float | None,
    away_elo: float | None,
) -> tuple[float, dict[str, Any] | None]:
    """Return effective global_avg and optional dynamic_goals diagnostics."""
    if p1.xg_total_variant != "dynamic_candidate":
        return base_avg, None

    from core.dynamic_goals import DynamicGoalsInput, compute_dynamic_total_goals

    dyn = compute_dynamic_total_goals(
        DynamicGoalsInput(
            base_total_goals=base_avg,
            dataset_key=p1.dataset_key,
            stage=p1.stage,
            home_attack=home_attack,
            home_defense=home_defense,
            away_attack=away_attack,
            away_defense=away_defense,
            power_gap=home_power - away_power,
            weather_xg_delta=p1.weather_xg_delta,
            market_total_goals=p1.market_total_goals,
            home_power=home_power,
            away_power=away_power,
            advantage=advantage,
            home_elo=home_elo,
            away_elo=away_elo,
        ),
        enabled=True,
        tuning=p1.dynamic_goals_tuning,
    )
    return dyn.final_expected_total_goals, dyn.to_dict()


def apply_power_variant_if_enabled(
    *,
    home_power: float,
    away_power: float,
    home_elo: float,
    away_elo: float,
    home_form: float,
    home_attack: float,
    home_defense: float,
    away_form: float,
    away_attack: float,
    away_defense: float,
    p1: Priority1Config,
    population_teams: dict[str, dict[str, Any]],
    population_source: str,
) -> tuple[float, float, dict[str, Any] | None]:
    """Swap to z-score power only when candidate config requests it."""
    if p1.power_variant != "zscore_candidate":
        return home_power, away_power, None

    from core.power_zscore import (
        TeamPowerComponents,
        build_pair_power_diagnostics,
        build_population_stats,
        compute_zscore_powers,
    )

    stats = build_population_stats(population_teams, population_source=population_source)
    sign = p1.zscore_defense_sign
    variant_label = (
        "zscore_defense_flipped_sign"
        if sign == "add"
        else "zscore_defense_current_sign"
    )
    home_c = TeamPowerComponents(
        effective_elo=home_elo,
        form=home_form,
        attack=home_attack,
        defense=home_defense,
        elo_trend=0.0,
        elo_trend_source="unavailable",
    )
    away_c = TeamPowerComponents(
        effective_elo=away_elo,
        form=away_form,
        attack=away_attack,
        defense=away_defense,
        elo_trend=0.0,
        elo_trend_source="unavailable",
    )
    hp, ap = compute_zscore_powers(home_c, away_c, stats, defense_sign=sign)
    diag = build_pair_power_diagnostics(
        home_c, away_c, stats, model_variant=variant_label, defense_sign=sign
    )
    return hp, ap, diag
