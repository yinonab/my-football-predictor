"""Phase 4C — Explicit baseline vs active vs final strength representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import config
from core.active_model_activation import (
    ActivePowerResult,
    ModelDiagnosticsPayload,
    model_activation_should_apply,
)
from core.match_features import MatchFeatures


def _gap(home: float, away: float) -> float:
    return round(home - away, 4)


@dataclass
class StrengthResult:
    """Structured strength layer: baseline, active candidate, and final prediction powers."""

    home_team: str
    away_team: str

    baseline_home_power: float
    baseline_away_power: float
    baseline_gap: float

    active_home_power: float
    active_away_power: float
    active_gap: float

    final_home_power: float
    final_away_power: float
    final_gap: float

    activation_enabled: bool
    power_candidate_affects_prediction: bool
    active_candidate: str | None
    active_external_rating_mode: str | None
    active_external_rating_strategy: str | None
    model_version: str
    baseline_model_version: str

    fallback_to_baseline: bool
    fallback_reasons: list[str] = field(default_factory=list)

    candidate_metrics_source: str = "phase2j_walk_forward"
    candidate_gate_status: str = "MODEL_ACTIVATION_PASS"

    rating_sources: list[str] = field(default_factory=list)
    fifa_anchor_details: dict[str, Any] | None = None
    warning_details: list[dict[str, Any]] = field(default_factory=list)
    confidence: str | None = None

    @property
    def uses_active_candidate(self) -> bool:
        return bool(self.activation_enabled and not self.fallback_to_baseline)

    @property
    def power_delta_home(self) -> float:
        return round(self.active_home_power - self.baseline_home_power, 4)

    @property
    def power_delta_away(self) -> float:
        return round(self.active_away_power - self.baseline_away_power, 4)

    @property
    def gap_delta(self) -> float:
        return round(self.active_gap - self.baseline_gap, 4)

    def enrich_breakdown_text(self, side: str, base_breakdown: str) -> str:
        """Append activation/fallback note so breakdown matches final power."""
        if self.uses_active_candidate:
            delta = self.power_delta_home if side == "home" else self.power_delta_away
            final = self.final_home_power if side == "home" else self.final_away_power
            return (
                f"{base_breakdown} | מועמד פעיל ({self.model_version}): "
                f"התאמת כוח {delta:+.2f} → כוח סופי לחיזוי {final:.2f}"
            )
        if self.fallback_to_baseline and model_activation_should_apply():
            reasons = ", ".join(self.fallback_reasons[:2]) or "fallback"
            return f"{base_breakdown} | נפילה לבייסליין ({reasons})"
        return base_breakdown

    def final_power_for(self, side: str) -> float:
        return self.final_home_power if side == "home" else self.final_away_power

    def to_model_diagnostics_dict(self) -> dict[str, Any]:
        """Merge existing model diagnostics contract with explicit power fields."""
        payload: dict[str, Any] = {
            "model_version": self.model_version,
            "baseline_model_version": self.baseline_model_version,
            "activation_enabled": self.activation_enabled,
            "active_candidate": self.active_candidate,
            "active_external_rating_mode": self.active_external_rating_mode,
            "active_external_rating_strategy": self.active_external_rating_strategy,
            "fallback_to_baseline": self.fallback_to_baseline,
            "fallback_reasons": list(self.fallback_reasons),
            "candidate_metrics_source": self.candidate_metrics_source,
            "candidate_gate_status": self.candidate_gate_status,
            "baseline_home_power": round(self.baseline_home_power, 2),
            "baseline_away_power": round(self.baseline_away_power, 2),
            "active_home_power": round(self.active_home_power, 2),
            "active_away_power": round(self.active_away_power, 2),
            "final_home_power": round(self.final_home_power, 2),
            "final_away_power": round(self.final_away_power, 2),
            "gap_delta": round(self.gap_delta, 4),
        }
        return payload

    def to_debug_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_strength_result(
    *,
    match_features: MatchFeatures,
    baseline_home_power: float,
    baseline_away_power: float,
    active_power: ActivePowerResult,
    model_diag: ModelDiagnosticsPayload,
    final_home_power: float,
    final_away_power: float,
    warning_details: list[dict[str, Any]] | None = None,
    confidence: str | None = None,
) -> StrengthResult:
    """Wrap existing activation values — does not recalculate power."""
    active_home = float(active_power.home_power)
    active_away = float(active_power.away_power)
    baseline_home = float(baseline_home_power)
    baseline_away = float(baseline_away_power)
    final_home = float(final_home_power)
    final_away = float(final_away_power)

    rating_sources = ["internal_elo", "attack", "defense", "form"]
    fifa_details: dict[str, Any] | None = None
    if model_diag.activation_enabled:
        rating_sources.extend(
            [
                "fifa_points_snapshot",
                config.ACTIVE_POWER_CANDIDATE,
                config.ACTIVE_EXTERNAL_RATING_STRATEGY,
            ]
        )
        fifa_details = {
            "active_candidate": model_diag.active_candidate,
            "active_external_rating_mode": model_diag.active_external_rating_mode,
            "active_external_rating_strategy": model_diag.active_external_rating_strategy,
            "home_fifa_points": match_features.home_fifa_points,
            "away_fifa_points": match_features.away_fifa_points,
            "external_rating_gap": match_features.external_rating_gap,
        }

    return StrengthResult(
        home_team=match_features.home_team,
        away_team=match_features.away_team,
        baseline_home_power=baseline_home,
        baseline_away_power=baseline_away,
        baseline_gap=_gap(baseline_home, baseline_away),
        active_home_power=active_home,
        active_away_power=active_away,
        active_gap=_gap(active_home, active_away),
        final_home_power=final_home,
        final_away_power=final_away,
        final_gap=_gap(final_home, final_away),
        activation_enabled=model_diag.activation_enabled,
        power_candidate_affects_prediction=config.POWER_CANDIDATE_AFFECTS_PREDICTION,
        active_candidate=model_diag.active_candidate,
        active_external_rating_mode=model_diag.active_external_rating_mode,
        active_external_rating_strategy=model_diag.active_external_rating_strategy,
        model_version=model_diag.model_version,
        baseline_model_version=model_diag.baseline_model_version,
        fallback_to_baseline=model_diag.fallback_to_baseline,
        fallback_reasons=list(model_diag.fallback_reasons),
        candidate_metrics_source=model_diag.candidate_metrics_source,
        candidate_gate_status=model_diag.candidate_gate_status,
        rating_sources=rating_sources,
        fifa_anchor_details=fifa_details,
        warning_details=list(warning_details or []),
        confidence=confidence,
    )
