"""Global Rating Stack — diagnostic layer comparing internal vs external strength."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import config
from data.database import FIFA_ELO_2026
from data.nt_match import registry_key_for_nt

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "global_ratings.json"

WARNING_POWER_COMPRESSED = "POWER_COMPRESSED_VS_ELO"
WARNING_FORM_INFLATED = "FORM_MAY_BE_INFLATED"
WARNING_LOW_CONFIDENCE = "LOW_RATING_CONFIDENCE"
WARNING_MISSING_EXTERNAL = "MISSING_EXTERNAL_RATING"
WARNING_MODEL_MARKET = "MODEL_MARKET_DIVERGENCE"


@dataclass
class ExternalRatingRecord:
    world_elo: float | None = None
    fifa_points: float | None = None
    fifa_rank: int | None = None
    rating_confidence: float = config.DEFAULT_RATING_CONFIDENCE
    notes: str = ""
    source: str = "fallback"


@dataclass
class TeamGlobalDiagnostics:
    team: str
    internal_elo: float
    world_elo: float
    fifa_points: float | None
    fifa_rank: int | None
    raw_form: float
    opponent_adjusted_form: float
    rating_confidence: float
    global_strength_score: float
    internal_external_elo_delta: float
    avg_opponent_elo: float | None = None
    opponent_history_matches: int = 0
    external_source: str = "fallback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalRatingGaps:
    internal_elo_gap: float
    world_elo_gap: float
    power_gap: float
    global_strength_gap: float
    power_vs_global_gap_delta: float
    global_strength_gap_raw: float
    global_strength_gap_label: str
    power_compression_ratio: float
    world_power_compression_ratio: float
    power_vs_elo_gap_delta: float
    power_vs_world_gap_delta: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WarningDetail:
    code: str
    severity: str
    message: str
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "metrics": dict(self.metrics),
        }


@dataclass
class GlobalRatingDiagnostics:
    home: TeamGlobalDiagnostics
    away: TeamGlobalDiagnostics
    gaps: GlobalRatingGaps
    warnings: list[str] = field(default_factory=list)
    warning_details: list[WarningDetail] = field(default_factory=list)
    experimental_adjustment_applied: bool = False
    power_component_diagnostics: dict[str, Any] | None = None
    power_shadow_calibration: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "home": self.home.to_dict(),
            "away": self.away.to_dict(),
            "gaps": self.gaps.to_dict(),
            "warnings": list(self.warnings),
            "warning_details": [w.to_dict() for w in self.warning_details],
            "experimental_adjustment_applied": self.experimental_adjustment_applied,
        }
        if self.power_component_diagnostics is not None:
            out["power_component_diagnostics"] = self.power_component_diagnostics
        if self.power_shadow_calibration is not None:
            out["power_shadow_calibration"] = self.power_shadow_calibration
        return out


def english_name(registry_key: str) -> str:
    return registry_key.split(" (")[0].strip()


@lru_cache(maxsize=1)
def load_global_ratings_file() -> dict[str, dict[str, Any]]:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load global_ratings.json: %s", exc)
        return {}


def lookup_external_record(registry_key: str) -> ExternalRatingRecord:
    """Resolve manual external ratings by English team name."""
    name = english_name(registry_key)
    raw = load_global_ratings_file().get(name)
    if not raw:
        return ExternalRatingRecord(source="missing")

    return ExternalRatingRecord(
        world_elo=float(raw["world_elo"]) if raw.get("world_elo") is not None else None,
        fifa_points=float(raw["fifa_points"]) if raw.get("fifa_points") is not None else None,
        fifa_rank=int(raw["fifa_rank"]) if raw.get("fifa_rank") is not None else None,
        rating_confidence=float(
            raw.get("rating_confidence", config.DEFAULT_RATING_CONFIDENCE)
        ),
        notes=str(raw.get("notes", "")),
        source="manual",
    )


@lru_cache(maxsize=1)
def _opponent_avg_elo_index() -> dict[str, tuple[float, int]]:
    """Average opponent baseline Elo per team from NT match history."""
    from core.team_ratings import build_all_matches

    registry = set(FIFA_ELO_2026.keys())
    baseline = {k: float(FIFA_ELO_2026[k]) for k in registry}
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)

    for match in build_all_matches():
        home_key = registry_key_for_nt(match.home, registry)
        away_key = registry_key_for_nt(match.away, registry)
        if not home_key or not away_key:
            continue
        sums[home_key] += baseline.get(away_key, 1500.0)
        counts[home_key] += 1
        sums[away_key] += baseline.get(home_key, 1500.0)
        counts[away_key] += 1

    return {k: (sums[k] / counts[k], counts[k]) for k in sums if counts[k] > 0}


def opponent_quality_factor(avg_opponent_elo: float) -> float:
    if avg_opponent_elo >= 1700:
        return 1.0
    if avg_opponent_elo >= 1600:
        return 0.85
    if avg_opponent_elo >= 1500:
        return 0.70
    if avg_opponent_elo >= 1400:
        return 0.55
    return 0.40


def compute_opponent_adjusted_form(
    registry_key: str,
    raw_form: float,
) -> tuple[float, float | None, int, bool]:
    """Return adjusted_form, avg_opponent_elo, match_count, used_opponent_history."""
    entry = _opponent_avg_elo_index().get(registry_key)
    if not entry:
        return raw_form, None, 0, False

    avg_opp, n = entry
    factor = opponent_quality_factor(avg_opp)
    adjusted = round(max(0.05, min(0.95, raw_form * factor)), 3)
    return adjusted, round(avg_opp, 1), n, True


def normalize_elo(elo: float) -> float:
    lo, hi = config.ELO_NORMALIZE_MIN, config.ELO_NORMALIZE_MAX
    return max(0.0, min(1.0, (elo - lo) / max(hi - lo, 1.0)))


def normalize_fifa_points(points: float) -> float:
    return max(0.0, min(1.0, points / config.FIFA_POINTS_NORMALIZE_MAX))


def normalize_fifa_rank(rank: int) -> float:
    """Higher is better: rank 1 → ~1.0, rank 200 → ~0."""
    return max(0.0, min(1.0, 1.0 - (rank - 1) / max(config.FIFA_RANK_NORMALIZE_MAX - 1, 1)))


def compute_global_strength_score(
    *,
    world_elo: float,
    internal_elo: float,
    opponent_adjusted_form: float,
    fifa_points: float | None,
    fifa_rank: int | None,
) -> float:
    w_world = config.GLOBAL_STRENGTH_WEIGHT_WORLD_ELO
    w_internal = config.GLOBAL_STRENGTH_WEIGHT_INTERNAL_ELO
    w_fifa = config.GLOBAL_STRENGTH_WEIGHT_FIFA
    w_form = config.GLOBAL_STRENGTH_WEIGHT_ADJ_FORM

    has_fifa = fifa_points is not None or fifa_rank is not None
    if not has_fifa:
        extra = w_fifa
        w_world += extra * (w_world / (w_world + w_internal))
        w_internal += extra * (w_internal / (w_world + w_internal))
        w_fifa = 0.0

    if fifa_points is not None:
        fifa_component = normalize_fifa_points(fifa_points)
    elif fifa_rank is not None:
        fifa_component = normalize_fifa_rank(fifa_rank)
    else:
        fifa_component = 0.0

    score = (
        w_world * normalize_elo(world_elo)
        + w_internal * normalize_elo(internal_elo)
        + w_fifa * fifa_component
        + w_form * max(0.0, min(1.0, opponent_adjusted_form))
    )
    return round(score, 4)


def build_team_diagnostics(
    registry_key: str,
    *,
    internal_elo: float,
    raw_form: float,
) -> TeamGlobalDiagnostics:
    external = lookup_external_record(registry_key)
    world_elo = (
        external.world_elo if external.world_elo is not None else float(internal_elo)
    )
    adj_form, avg_opp, opp_n, used_opp = compute_opponent_adjusted_form(
        registry_key, raw_form
    )
    confidence = external.rating_confidence
    if not used_opp:
        confidence = round(min(confidence, config.DEFAULT_RATING_CONFIDENCE), 3)

    source = external.source
    if external.world_elo is None:
        source = "internal_fallback"

    gss = compute_global_strength_score(
        world_elo=world_elo,
        internal_elo=internal_elo,
        opponent_adjusted_form=adj_form,
        fifa_points=external.fifa_points,
        fifa_rank=external.fifa_rank,
    )

    return TeamGlobalDiagnostics(
        team=registry_key,
        internal_elo=round(internal_elo, 1),
        world_elo=round(world_elo, 1),
        fifa_points=external.fifa_points,
        fifa_rank=external.fifa_rank,
        raw_form=round(raw_form, 3),
        opponent_adjusted_form=adj_form,
        rating_confidence=confidence,
        global_strength_score=gss,
        internal_external_elo_delta=round(internal_elo - world_elo, 1),
        avg_opponent_elo=avg_opp,
        opponent_history_matches=opp_n,
        external_source=source,
    )


def global_strength_gap_label(gap_abs: float) -> str:
    if gap_abs < config.GLOBAL_STRENGTH_GAP_TINY_MAX:
        return "tiny"
    if gap_abs < config.GLOBAL_STRENGTH_GAP_SMALL_MAX:
        return "small"
    if gap_abs < config.GLOBAL_STRENGTH_GAP_MEDIUM_MAX:
        return "medium"
    if gap_abs < config.GLOBAL_STRENGTH_GAP_LARGE_MAX:
        return "large"
    return "extreme"


def build_gap_metrics(
    *,
    home_power: float,
    away_power: float,
    home: TeamGlobalDiagnostics,
    away: TeamGlobalDiagnostics,
) -> GlobalRatingGaps:
    internal_elo_gap = round(home.internal_elo - away.internal_elo, 1)
    world_elo_gap = round(home.world_elo - away.world_elo, 1)
    power_gap = round(home_power - away_power, 2)
    global_strength_gap = round(
        home.global_strength_score - away.global_strength_score, 4
    )
    gss_raw = round(abs(global_strength_gap), 4)
    abs_power = abs(power_gap)
    abs_elo = abs(internal_elo_gap)
    abs_world = abs(world_elo_gap)

    return GlobalRatingGaps(
        internal_elo_gap=internal_elo_gap,
        world_elo_gap=world_elo_gap,
        power_gap=power_gap,
        global_strength_gap=global_strength_gap,
        power_vs_global_gap_delta=round(abs_power - abs_world * 0.42, 2),
        global_strength_gap_raw=gss_raw,
        global_strength_gap_label=global_strength_gap_label(gss_raw),
        power_compression_ratio=round(abs_power / max(abs_elo, 1.0), 4),
        world_power_compression_ratio=round(abs_power / max(abs_world, 1.0), 4),
        power_vs_elo_gap_delta=round(abs_power - abs_elo, 2),
        power_vs_world_gap_delta=round(abs_power - abs_world, 2),
    )


def _power_compressed_severity(gaps: GlobalRatingGaps) -> str:
    elo_gap = abs(gaps.internal_elo_gap)
    ratio = gaps.power_compression_ratio
    if elo_gap >= config.POWER_COMPRESSED_HIGH_ELO_GAP and ratio <= (
        config.POWER_COMPRESSED_HIGH_RATIO
    ):
        return "high"
    if elo_gap >= 80 and ratio < config.POWER_COMPRESSED_VS_ELO_RATIO:
        return "medium"
    return "low"


def _form_inflation_severity(side: TeamGlobalDiagnostics) -> str:
    delta = side.raw_form - side.opponent_adjusted_form
    if delta >= config.FORM_INFLATED_HIGH_DELTA:
        return "high"
    if delta >= config.FORM_INFLATED_MEDIUM_DELTA:
        return "medium"
    return "low"


def _confidence_severity(home: TeamGlobalDiagnostics, away: TeamGlobalDiagnostics) -> str:
    low = min(home.rating_confidence, away.rating_confidence)
    if low < config.LOW_CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if (
        home.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD
        or away.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD
    ):
        return "medium"
    return "low"


def build_warning_details(
    home: TeamGlobalDiagnostics,
    away: TeamGlobalDiagnostics,
    gaps: GlobalRatingGaps,
    *,
    model_probs: dict[str, float] | None = None,
    market_probs: dict[str, float] | None = None,
) -> list[WarningDetail]:
    details: list[WarningDetail] = []
    elo_gap = abs(gaps.internal_elo_gap)
    world_gap = abs(gaps.world_elo_gap)
    power_gap = abs(gaps.power_gap)

    power_triggered = (
        elo_gap >= 80
        and power_gap < elo_gap * config.POWER_COMPRESSED_VS_ELO_RATIO
    ) or (
        world_gap >= 80
        and power_gap < world_gap * config.POWER_COMPRESSED_VS_ELO_RATIO
    )
    if power_triggered:
        severity = _power_compressed_severity(gaps)
        details.append(
            WarningDetail(
                code=WARNING_POWER_COMPRESSED,
                severity=severity,
                message=(
                    "Composite Power gap is much smaller than Elo/world-Elo gap "
                    f"(compression ratio {gaps.power_compression_ratio:.2f})."
                ),
                metrics={
                    "power_gap": gaps.power_gap,
                    "internal_elo_gap": gaps.internal_elo_gap,
                    "world_elo_gap": gaps.world_elo_gap,
                    "compression_ratio": gaps.power_compression_ratio,
                    "world_compression_ratio": gaps.world_power_compression_ratio,
                },
            )
        )

    inflated_side: TeamGlobalDiagnostics | None = None
    for side in (home, away):
        if (
            side.raw_form >= config.FORM_INFLATED_RAW_MIN
            and side.opponent_adjusted_form
            < side.raw_form * config.FORM_INFLATED_ADJ_RATIO
        ):
            inflated_side = side
            break
    if inflated_side is not None:
        form_delta = round(
            inflated_side.raw_form - inflated_side.opponent_adjusted_form, 3
        )
        details.append(
            WarningDetail(
                code=WARNING_FORM_INFLATED,
                severity=_form_inflation_severity(inflated_side),
                message=(
                    f"{english_name(inflated_side.team)} raw form may be inflated "
                    f"by weak opponents (delta {form_delta:.2f})."
                ),
                metrics={
                    "team": english_name(inflated_side.team),
                    "raw_form": inflated_side.raw_form,
                    "opponent_adjusted_form": inflated_side.opponent_adjusted_form,
                    "form_inflation_delta": form_delta,
                },
            )
        )

    if (
        home.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD
        or away.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD
    ):
        details.append(
            WarningDetail(
                code=WARNING_LOW_CONFIDENCE,
                severity=_confidence_severity(home, away),
                message="One or both teams have low external rating confidence.",
                metrics={
                    "home_confidence": home.rating_confidence,
                    "away_confidence": away.rating_confidence,
                },
            )
        )

    if home.external_source != "manual" or away.external_source != "manual":
        missing = [
            english_name(side.team)
            for side in (home, away)
            if side.external_source != "manual"
        ]
        details.append(
            WarningDetail(
                code=WARNING_MISSING_EXTERNAL,
                severity="medium" if len(missing) == 2 else "low",
                message=f"Missing manual external rating for: {', '.join(missing)}.",
                metrics={"teams_missing_external": missing},
            )
        )

    if model_probs and market_probs:
        max_div = 0.0
        divergent_key = ""
        for key in ("home_win", "draw", "away_win"):
            div = abs(model_probs.get(key, 0) - market_probs.get(key, 0))
            if div > max_div:
                max_div = div
                divergent_key = key
        if max_div >= config.MODEL_MARKET_DIVERGENCE_PP:
            severity = (
                "high"
                if max_div >= config.MODEL_MARKET_DIVERGENCE_HIGH_PP
                else "medium"
            )
            details.append(
                WarningDetail(
                    code=WARNING_MODEL_MARKET,
                    severity=severity,
                    message=(
                        f"Model vs market divergence on {divergent_key} "
                        f"({max_div:.1f} pp)."
                    ),
                    metrics={
                        "max_divergence_pp": round(max_div, 2),
                        "outcome": divergent_key,
                    },
                )
            )

    return details


def _collect_warnings(
    home: TeamGlobalDiagnostics,
    away: TeamGlobalDiagnostics,
    gaps: GlobalRatingGaps,
    *,
    model_probs: dict[str, float] | None = None,
    market_probs: dict[str, float] | None = None,
) -> tuple[list[str], list[WarningDetail]]:
    details = build_warning_details(
        home, away, gaps, model_probs=model_probs, market_probs=market_probs
    )
    seen: set[str] = set()
    warnings: list[str] = []
    for item in details:
        if item.code not in seen:
            seen.add(item.code)
            warnings.append(item.code)
    return warnings, details


def build_match_diagnostics(
    home_key: str,
    away_key: str,
    *,
    home_power: float,
    away_power: float,
    home_internal_elo: float,
    away_internal_elo: float,
    home_raw_form: float,
    away_raw_form: float,
    model_probs: dict[str, float] | None = None,
    market_probs: dict[str, float] | None = None,
) -> GlobalRatingDiagnostics:
    home = build_team_diagnostics(
        home_key, internal_elo=home_internal_elo, raw_form=home_raw_form
    )
    away = build_team_diagnostics(
        away_key, internal_elo=away_internal_elo, raw_form=away_raw_form
    )

    gaps = build_gap_metrics(
        home_power=home_power,
        away_power=away_power,
        home=home,
        away=away,
    )

    warnings, warning_details = _collect_warnings(
        home, away, gaps, model_probs=model_probs, market_probs=market_probs
    )

    return GlobalRatingDiagnostics(
        home=home,
        away=away,
        gaps=gaps,
        warnings=warnings,
        warning_details=warning_details,
        experimental_adjustment_applied=False,
    )


def apply_experimental_power_nudge(
    home_power: float,
    away_power: float,
    diag: GlobalRatingDiagnostics,
) -> tuple[float, float, GlobalRatingDiagnostics]:
    """
    Experimental only (GLOBAL_RATINGS_AFFECT_PREDICTION=true).
    Nudge composite power slightly toward world/global strength gap when compressed.
    """
    if not config.GLOBAL_RATINGS_AFFECT_PREDICTION:
        return home_power, away_power, diag

    elo_gap = diag.gaps.internal_elo_gap
    world_gap = diag.gaps.world_elo_gap
    power_gap = diag.gaps.power_gap

    target_gap = world_gap if abs(world_gap) >= abs(elo_gap) else elo_gap
    if abs(target_gap) < 80 or abs(power_gap) >= abs(target_gap) * 0.55:
        return home_power, away_power, diag

    deficit = target_gap - power_gap
    nudge = max(
        -config.GLOBAL_POWER_NUDGE_MAX * abs(target_gap),
        min(config.GLOBAL_POWER_NUDGE_MAX * abs(target_gap), deficit * 0.15),
    )

    if target_gap >= 0:
        new_home = home_power + nudge
        new_away = away_power
    else:
        new_home = home_power
        new_away = away_power - nudge

    updated = GlobalRatingDiagnostics(
        home=diag.home,
        away=diag.away,
        gaps=diag.gaps,
        warnings=diag.warnings + ["EXPERIMENTAL_POWER_NUDGE_APPLIED"],
        warning_details=diag.warning_details,
        experimental_adjustment_applied=True,
    )
    return new_home, new_away, updated


def resolve_registry_key(team_input: str, resolve_fn) -> str:
    """Thin wrapper for API layer team resolution."""
    resolved, _ = resolve_fn(team_input)
    return resolved
