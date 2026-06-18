"""Phase 3A — Controlled activation wiring for FIFA-points external anchor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from core.global_ratings import english_name
from core.power_effective_elo import EFFECTIVE_EXTERNAL_VARIANT_BASE
from data.database import LiveDataManager

FIFA_STRATEGIES: frozenset[str] = frozenset(
    {
        "fifa_points_snapshot_static",
        "fifa_points_confidence_weighted",
        "fifa_points_disagreement_weighted",
    }
)

GOLDEN_PARITY_MATCHUPS: list[tuple[str, str]] = [
    ("Brazil", "Morocco"),
    ("Portugal", "DR Congo"),
    ("Argentina", "France"),
    ("Spain", "Cape Verde"),
    ("Germany", "Haiti"),
    ("England", "USA"),
]

DRY_RUN_MATCHUPS: list[tuple[str, str]] = [
    ("Brazil", "Morocco"),
    ("Portugal", "DR Congo"),
    ("Germany", "Haiti"),
    ("Spain", "Cape Verde"),
    ("England", "USA"),
    ("Argentina", "France"),
]

SAMPLE_PRODUCTION_MATCHUPS: list[tuple[str, str]] = [
    ("Brazil", "Morocco"),
    ("Portugal", "DR Congo"),
    ("Germany", "Haiti"),
    ("Spain", "Cape Verde"),
    ("England", "USA"),
    ("Argentina", "France"),
    ("Norway", "Algeria"),
    ("Japan", "South Africa"),
]

PHASE2J_WINNER_CANDIDATE = "effective_external_current_formula"
PHASE2J_WINNER_STRATEGY = "fifa_points_confidence_weighted"
PHASE2J_WINNER_MODE = "fifa_points_snapshot"


@dataclass
class ActivePowerResult:
    applied: bool
    home_power: float
    away_power: float
    home_elo: float
    away_elo: float
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class ModelDiagnosticsPayload:
    model_version: str
    baseline_model_version: str
    activation_enabled: bool
    active_candidate: str | None
    active_external_rating_mode: str | None
    active_external_rating_strategy: str | None
    fallback_to_baseline: bool
    fallback_reasons: list[str]
    candidate_metrics_source: str
    candidate_gate_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "baseline_model_version": self.baseline_model_version,
            "activation_enabled": self.activation_enabled,
            "active_candidate": self.active_candidate,
            "active_external_rating_mode": self.active_external_rating_mode,
            "active_external_rating_strategy": self.active_external_rating_strategy,
            "fallback_to_baseline": self.fallback_to_baseline,
            "fallback_reasons": self.fallback_reasons,
            "candidate_metrics_source": self.candidate_metrics_source,
            "candidate_gate_status": self.candidate_gate_status,
        }


def model_activation_should_apply() -> bool:
    return bool(
        config.MODEL_ACTIVATION_ENABLED and config.POWER_CANDIDATE_AFFECTS_PREDICTION
    )


def validate_activation_configuration() -> tuple[bool, list[str]]:
    """Return (ok, reasons). Does not mutate production state."""
    reasons: list[str] = []
    if not config.MODEL_ACTIVATION_ENABLED:
        reasons.append("MODEL_ACTIVATION_ENABLED=false")
    if not config.POWER_CANDIDATE_AFFECTS_PREDICTION:
        reasons.append("POWER_CANDIDATE_AFFECTS_PREDICTION=false")
    if config.ACTIVE_POWER_CANDIDATE not in EFFECTIVE_EXTERNAL_VARIANT_BASE:
        reasons.append(f"invalid ACTIVE_POWER_CANDIDATE={config.ACTIVE_POWER_CANDIDATE}")
    if config.ACTIVE_EXTERNAL_RATING_MODE != "fifa_points_snapshot":
        reasons.append(
            f"unsupported ACTIVE_EXTERNAL_RATING_MODE={config.ACTIVE_EXTERNAL_RATING_MODE}"
        )
    if config.ACTIVE_EXTERNAL_RATING_STRATEGY not in FIFA_STRATEGIES:
        reasons.append(
            f"invalid ACTIVE_EXTERNAL_RATING_STRATEGY={config.ACTIVE_EXTERNAL_RATING_STRATEGY}"
        )
    snap_path = Path(config.EXTERNAL_RATING_SNAPSHOTS_PATH)
    if not snap_path.exists():
        reasons.append("external_rating_snapshots.json missing")
    else:
        from core.external_rating_snapshots import external_fifa_points_production_ready

        prod_ready, prod_report = external_fifa_points_production_ready()
        if not prod_ready:
            reasons.append(
                "production_fifa_coverage_low:"
                f"{prod_report.dataset}={prod_report.fifa_points_coverage:.2f}"
            )
            if prod_report.missing:
                reasons.append(f"production_fifa_missing_teams={prod_report.missing}")
    return (len(reasons) == 0, reasons)


def _team_snapshot_from_live(team_key: str, display_name: str, dm: LiveDataManager):
    from core.temporal_backtest import TeamRatingSnapshot

    data = dm.get_team_data(team_key)
    return TeamRatingSnapshot(
        team=display_name,
        internal_elo=float(data.get("elo", 1500.0)),
        form=float(data.get("form", 0.0)),
        attack=float(data.get("attack", 0.0)),
        defense=float(data.get("defense", 0.0)),
        goals_for_per_game=float(data.get("goals_for_per_game", 0.0)),
        goals_against_per_game=float(data.get("goals_against_per_game", 0.0)),
        match_count=int(data.get("match_count", 0)),
        avg_opponent_elo=float(data.get("avg_opponent_elo", 1500.0)),
        opponent_adjusted_form=float(data.get("opponent_adjusted_form", 0.0)),
        rating_confidence=float(data.get("rating_confidence", 0.85)),
    )


def resolve_production_fifa_snapshot_dataset(
    home_en: str, away_en: str
) -> tuple[str | None, list[str]]:
    from core.external_rating_snapshots import get_team_fifa_points

    key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    _, home_ok = get_team_fifa_points(key, home_en)
    _, away_ok = get_team_fifa_points(key, away_en)
    if home_ok and away_ok:
        return key, []
    reasons: list[str] = []
    if not home_ok:
        reasons.append(f"fifa_points_missing_for_{home_en}")
    if not away_ok:
        reasons.append(f"fifa_points_missing_for_{away_en}")
    return None, reasons


def resolve_historical_fifa_snapshot_dataset(
    home_en: str, away_en: str,
) -> tuple[str | None, list[str]]:
    from core.external_rating_snapshots import get_team_fifa_points
    from core.fixture_metadata import TOURNAMENT_STARTS

    keys = list(TOURNAMENT_STARTS.keys())
    for key in keys:
        _, home_ok = get_team_fifa_points(key, home_en, match_date="2099-01-01")
        _, away_ok = get_team_fifa_points(key, away_en, match_date="2099-01-01")
        if home_ok and away_ok:
            return key, []
    return None, [f"fifa_points_missing_for_{home_en}_or_{away_en}"]


def resolve_fifa_snapshot_dataset(
    home_en: str,
    away_en: str,
    *,
    for_production: bool = True,
) -> tuple[str | None, list[str]]:
    """Production live predictions use wc2026_current; walk-forward uses tournament snapshots."""
    if for_production:
        return resolve_production_fifa_snapshot_dataset(home_en, away_en)
    return resolve_historical_fifa_snapshot_dataset(home_en, away_en)


def compute_active_candidate_powers(
    home_key: str,
    away_key: str,
    *,
    data_manager: LiveDataManager,
    candidate: str | None = None,
    strategy: str | None = None,
    dataset_key: str | None = None,
) -> tuple[float, float, float, float, list[str]]:
    """Return home_power, away_power, home_blend_elo, away_blend_elo, errors."""
    from core.temporal_backtest import compute_temporal_power

    cand = candidate or config.ACTIVE_POWER_CANDIDATE
    strat = strategy or config.ACTIVE_EXTERNAL_RATING_STRATEGY
    home_en = english_name(home_key) or home_key.split(" (")[0]
    away_en = english_name(away_key) or away_key.split(" (")[0]

    ds, ds_reasons = resolve_fifa_snapshot_dataset(home_en, away_en, for_production=True)
    if dataset_key:
        ds = dataset_key
        ds_reasons = []
    if not ds:
        return 0.0, 0.0, 0.0, 0.0, ds_reasons

    home_snap = _team_snapshot_from_live(home_key, home_en, data_manager)
    away_snap = _team_snapshot_from_live(away_key, away_en, data_manager)

    home_power, home_blend = compute_temporal_power(
        home_en,
        home_snap,
        candidate=cand,
        elo_strategy=strat,
        world_elo_mode="none",
        dataset_key=ds,
        match_date="2099-01-01",
    )
    away_power, away_blend = compute_temporal_power(
        away_en,
        away_snap,
        candidate=cand,
        elo_strategy=strat,
        world_elo_mode="none",
        dataset_key=ds,
        match_date="2099-01-01",
    )
    return home_power, away_power, home_blend, away_blend, []


def try_apply_active_candidate_powers(
    home_key: str,
    away_key: str,
    *,
    baseline_home_power: float,
    baseline_away_power: float,
    baseline_home_elo: float,
    baseline_away_elo: float,
    data_manager: LiveDataManager,
    force_enable: bool = False,
) -> ActivePowerResult:
    """Apply active candidate powers when enabled and valid; else baseline."""
    if not force_enable and not model_activation_should_apply():
        return ActivePowerResult(
            applied=False,
            home_power=baseline_home_power,
            away_power=baseline_away_power,
            home_elo=baseline_home_elo,
            away_elo=baseline_away_elo,
        )

    ok, config_reasons = validate_activation_configuration()
    if not ok and not force_enable:
        return ActivePowerResult(
            applied=False,
            home_power=baseline_home_power,
            away_power=baseline_away_power,
            home_elo=baseline_home_elo,
            away_elo=baseline_away_elo,
            fallback_reasons=config_reasons,
        )

    hp, ap, he, ae, power_reasons = compute_active_candidate_powers(
        home_key,
        away_key,
        data_manager=data_manager,
    )
    if power_reasons:
        return ActivePowerResult(
            applied=False,
            home_power=baseline_home_power,
            away_power=baseline_away_power,
            home_elo=baseline_home_elo,
            away_elo=baseline_away_elo,
            fallback_reasons=power_reasons,
        )

    return ActivePowerResult(
        applied=True,
        home_power=hp,
        away_power=ap,
        home_elo=he,
        away_elo=ae,
    )


def build_model_diagnostics(
    *,
    activation_applied: bool,
    fallback_reasons: list[str] | None = None,
    gate_status: str = "MODEL_ACTIVATION_PASS",
    force_active: bool = False,
) -> ModelDiagnosticsPayload:
    enabled = model_activation_should_apply() or force_active
    fallback = bool(fallback_reasons) or ((enabled or force_active) and not activation_applied)
    reasons = list(fallback_reasons or [])
    if enabled and not activation_applied and not reasons:
        reasons.append("active_candidate_not_applied")

    if (enabled and activation_applied and not fallback) or (
        force_active and activation_applied and not fallback
    ):
        version = config.ACTIVE_MODEL_VERSION
        active_candidate = config.ACTIVE_POWER_CANDIDATE
        mode = config.ACTIVE_EXTERNAL_RATING_MODE
        strategy = config.ACTIVE_EXTERNAL_RATING_STRATEGY
    else:
        version = config.BASELINE_MODEL_VERSION
        active_candidate = None
        mode = None
        strategy = None

    return ModelDiagnosticsPayload(
        model_version=version,
        baseline_model_version=config.BASELINE_MODEL_VERSION,
        activation_enabled=enabled and activation_applied and not fallback,
        active_candidate=active_candidate,
        active_external_rating_mode=mode,
        active_external_rating_strategy=strategy,
        fallback_to_baseline=fallback,
        fallback_reasons=reasons,
        candidate_metrics_source="phase2j_walk_forward",
        candidate_gate_status=gate_status,
    )


def run_prediction_with_active_candidate(
    home_key: str,
    away_key: str,
    *,
    data_manager: LiveDataManager,
    opponent_index: dict,
    advantage: float = 0.0,
    avg_goals: float | None = None,
    rho: float | None = None,
    alpha: float | None = None,
    top_n: int = 3,
    force_enable: bool = False,
    candidate: str | None = None,
    strategy: str | None = None,
    dataset_key: str | None = None,
) -> dict[str, Any]:
    """Full-pipeline prediction using active FIFA external anchor (isolated helper)."""
    from core.blowout import apply_blowout_adjustment
    from core.maher import (
        blend_maher_with_power,
        floor_underdog_xg,
        mismatch_gap,
        scale_rho_for_gap,
    )
    from core.math_engine import AdvancedDixonColesEngine
    from core.opponent_maher import estimate_xg_opponent_aware
    from core.power_effective_elo import run_full_shadow_pipeline, _BASELINE_SENTINEL

    dm = data_manager
    avg = avg_goals if avg_goals is not None else config.GLOBAL_XG_AVG
    rho_val = rho if rho is not None else config.DEFAULT_RHO
    alpha_val = alpha if alpha is not None else config.OVERDISPERSION_ALPHA

    baseline = run_full_shadow_pipeline(
        home_key,
        away_key,
        power_variant="current",
        data_manager=dm,
        opponent_index=opponent_index,
        current_baseline=_BASELINE_SENTINEL,
        advantage=advantage,
        top_n=top_n,
    )

    base_hp = baseline.home_power
    base_ap = baseline.away_power
    home_data = dm.get_team_data(home_key)
    away_data = dm.get_team_data(away_key)
    base_he = float(home_data["elo"])
    base_ae = float(away_data["elo"])

    active = try_apply_active_candidate_powers(
        home_key,
        away_key,
        baseline_home_power=base_hp,
        baseline_away_power=base_ap,
        baseline_home_elo=base_he,
        baseline_away_elo=base_ae,
        data_manager=dm,
        force_enable=force_enable,
    )

    if active.applied:
        hp, ap, he, ae = (
            active.home_power,
            active.away_power,
            active.home_elo,
            active.away_elo,
        )
        if candidate or strategy or dataset_key:
            hp, ap, he, ae, errs = compute_active_candidate_powers(
                home_key,
                away_key,
                data_manager=dm,
                candidate=candidate,
                strategy=strategy,
                dataset_key=dataset_key,
            )
            if errs:
                hp, ap, he, ae = base_hp, base_ap, base_he, base_ae
                active = ActivePowerResult(
                    applied=False,
                    home_power=hp,
                    away_power=ap,
                    home_elo=he,
                    away_elo=ae,
                    fallback_reasons=errs,
                )
    else:
        hp, ap, he, ae = base_hp, base_ap, base_he, base_ae

    home_xg, away_xg, _ = estimate_xg_opponent_aware(
        home_key,
        away_key,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        opponent_index,
        global_avg=avg,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        hp,
        ap,
        advantage,
        global_avg=avg,
        home_elo=he,
        away_elo=ae,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        hp,
        ap,
        advantage,
        home_elo=he,
        away_elo=ae,
    )
    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        hp,
        ap,
        advantage,
        base_alpha=alpha_val,
        home_elo=he,
        away_elo=ae,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    gap_for_rho = mismatch_gap(hp, ap, advantage, home_elo=he, away_elo=ae)
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(rho_val, gap_for_rho),
        global_avg=avg,
        alpha=blowout.alpha,
    )
    result = engine.generate_match_prediction(
        hp,
        ap,
        advantage,
        top_n=top_n,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )

    diag = build_model_diagnostics(
        activation_applied=active.applied,
        fallback_reasons=active.fallback_reasons,
        force_active=force_enable and active.applied,
    )

    return {
        "baseline": {
            "probabilities_1x2": baseline.probabilities_1x2,
            "home_xg": baseline.home_xg,
            "away_xg": baseline.away_xg,
            "home_power": baseline.home_power,
            "away_power": baseline.away_power,
            "top_scores": baseline.top_scores,
        },
        "active": {
            "probabilities_1x2": result["probabilities_1x2"],
            "home_xg": result["home_xg"],
            "away_xg": result["away_xg"],
            "home_power": hp,
            "away_power": ap,
            "top_scores": [item["score"] for item in result.get("top_scores", [])],
        },
        "model_diagnostics": diag.to_dict(),
        "activation_applied": active.applied,
        "fallback_reasons": active.fallback_reasons,
    }
