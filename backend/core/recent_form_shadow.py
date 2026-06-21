"""Phase 4R.4 — Recent-form fusion shadow diagnostics and controlled active gate experiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

import config
from core.recent_form_fusion import get_fusion_team_entry
from core.recent_match_history import (
    NormalizedRecentMatch,
    build_normalized_recent_match_history,
    get_team_recent_matches,
)
from core.recent_scoring_form import RecentScoringFormMetrics, get_recent_scoring_form
from core.underdog_goal_gate import (
    LARGE_CANDIDATE_PROB_GAP,
    CLOSE_CANDIDATE_PROB_GAP,
    CandidateComparisonSummary,
    GateLevel,
    UnderdogGoalGateResult,
    UnderdogMatchContext,
    compute_underdog_goal_gate,
)
from data.nt_match import registry_key_for_nt
from data.database import FIFA_ELO_2026

SupportLevel = Literal["strong", "moderate", "weak", "negative", "unavailable"]

GATE_PERMISSIVE_ORDER: tuple[GateLevel, ...] = (
    "BLOCK",
    "WEAK_ALLOW",
    "ALLOW",
    "STRONG_ALLOW",
)

RECENT_FORM_SHADOW_UNAVAILABLE = "RECENT_FORM_SHADOW_UNAVAILABLE"
RECENT_FORM_SHADOW_LOW_CONFIDENCE = "RECENT_FORM_SHADOW_LOW_CONFIDENCE"
RECENT_FORM_ACTIVE_BLOCKED_LOW_COVERAGE = "RECENT_FORM_ACTIVE_BLOCKED_LOW_COVERAGE"
RECENT_FORM_ACTIVE_BLOCKED_CANDIDATE_GAP = "RECENT_FORM_ACTIVE_BLOCKED_CANDIDATE_GAP"
RECENT_FORM_ACTIVE_BLOCKED_XG_BTTS = "RECENT_FORM_ACTIVE_BLOCKED_XG_BTTS"
RECENT_FORM_ACTIVE_BLOCKED_WEAK_SUPPORT = "RECENT_FORM_ACTIVE_BLOCKED_WEAK_SUPPORT"
RECENT_FORM_ACTIVE_APPLIED = "RECENT_FORM_ACTIVE_APPLIED"
RECENT_FORM_SHADOW_GATE_ADJUSTED = "RECENT_FORM_SHADOW_GATE_ADJUSTED"

REGISTRY = set(FIFA_ELO_2026.keys())


@dataclass(frozen=True)
class FusionRecentFormBundle:
    """Underdog recent-form metrics from fusion/static read path only."""

    team_registry_key: str | None
    scoring: RecentScoringFormMetrics
    coverage_quality: str
    freshness_gap_days: int | None
    latest_match_date: str | None
    source_mix: dict[str, int]
    competition_mix: dict[str, int]
    clean_sheet_rate: float | None
    support_level: SupportLevel
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecentFormShadowOutcome:
    baseline_gate_level: GateLevel
    shadow_gate_level: GateLevel
    active_gate_level: GateLevel
    would_change_gate: bool
    would_change_primary_score: bool
    active_change_applied: bool
    shadow_primary_score: str | None
    diagnostics: dict[str, Any]


def _resolve_registry_key(team: str) -> str | None:
    if team in REGISTRY:
        return team
    return registry_key_for_nt(team, REGISTRY)


def _fusion_read_history() -> list[NormalizedRecentMatch]:
    return build_normalized_recent_match_history(
        include_optional_caches=False,
        include_recent_form_cache=False,
        include_fusion_cache=True,
    )


def _competition_mix(matches: list[NormalizedRecentMatch]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for row in matches:
        comp = row.competition or "unknown"
        mix[comp] = mix.get(comp, 0) + 1
    return mix


def _provider_source_mix(
    matches: list[NormalizedRecentMatch],
    fusion_entry: dict[str, Any] | None,
) -> dict[str, int]:
    if fusion_entry:
        fusion = fusion_entry.get("fusion") or {}
        provider_mix = fusion.get("source_mix")
        if isinstance(provider_mix, dict) and provider_mix:
            return {str(k): int(v) for k, v in provider_mix.items()}
    breakdown: dict[str, int] = {}
    for row in matches:
        breakdown[row.source] = breakdown.get(row.source, 0) + 1
    return breakdown


def classify_underdog_support_level(
    *,
    scoring: RecentScoringFormMetrics,
    coverage_quality: str,
) -> SupportLevel:
    if not scoring.recent_form_available or (scoring.matches_found or 0) < 3:
        return "unavailable"
    if coverage_quality in {"low", "unavailable"}:
        return "weak" if scoring.recent_form_confidence != "unavailable" else "unavailable"
    rate = scoring.last_10_scored_rate or 0.0
    failed = scoring.last_10_failed_to_score_rate or 0.0
    if rate >= 0.70 and failed <= 0.35 and coverage_quality in {"high", "medium"}:
        return "strong"
    if rate >= 0.50:
        return "moderate"
    if rate >= 0.30:
        return "weak"
    if rate < 0.30 or failed >= 0.65:
        return "negative"
    return "weak"


def load_fusion_recent_form_bundle(
    team: str,
    *,
    favorite_power: float | None = None,
    window: int = 10,
) -> FusionRecentFormBundle:
    team_key = _resolve_registry_key(team)
    history = _fusion_read_history()
    scoring = get_recent_scoring_form(
        team_key or team,
        favorite_power=favorite_power,
        window=window,
        history=history,
    )
    matches = (
        get_team_recent_matches(team_key or team, limit=window, history=history)
        if team_key
        else []
    )
    fusion_entry = get_fusion_team_entry(team_key) if team_key else None
    fusion_meta = (fusion_entry or {}).get("fusion") or {}

    coverage_quality = str(fusion_meta.get("coverage_quality") or "unavailable")
    if not scoring.recent_form_available:
        coverage_quality = "unavailable"

    clean_sheets = sum(1 for m in matches if m.goals_against == 0)
    clean_sheet_rate = (clean_sheets / len(matches)) if matches else None

    warnings = list(fusion_meta.get("coverage_warnings") or [])
    reason_codes = list(scoring.reason_codes or [])
    support = classify_underdog_support_level(
        scoring=scoring,
        coverage_quality=coverage_quality,
    )
    if support == "unavailable":
        reason_codes.append(RECENT_FORM_SHADOW_UNAVAILABLE)
    elif scoring.recent_form_confidence == "low":
        reason_codes.append(RECENT_FORM_SHADOW_LOW_CONFIDENCE)

    return FusionRecentFormBundle(
        team_registry_key=team_key,
        scoring=scoring,
        coverage_quality=coverage_quality,
        freshness_gap_days=fusion_meta.get("freshness_gap_days"),
        latest_match_date=fusion_meta.get("latest_match_date"),
        source_mix=_provider_source_mix(matches, fusion_entry),
        competition_mix=_competition_mix(matches),
        clean_sheet_rate=round(clean_sheet_rate, 3) if clean_sheet_rate is not None else None,
        support_level=support,
        warnings=tuple(dict.fromkeys(warnings)),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _gate_permissiveness(level: GateLevel) -> int:
    if level == "BALANCED":
        return 2
    return GATE_PERMISSIVE_ORDER.index(level)


def move_gate_toward(
    current: GateLevel,
    target: GateLevel,
    *,
    max_steps: int,
) -> GateLevel:
    if current == "BALANCED" or target == "BALANCED" or current == target:
        return current
    cur_i = _gate_permissiveness(current)
    tgt_i = _gate_permissiveness(target)
    if cur_i == tgt_i:
        return current
    step_dir = 1 if tgt_i > cur_i else -1
    steps = min(max_steps, abs(tgt_i - cur_i))
    new_i = max(0, min(len(GATE_PERMISSIVE_ORDER) - 1, cur_i + step_dir * steps))
    return GATE_PERMISSIVE_ORDER[new_i]


def compute_shadow_gate_level(
    *,
    baseline_gate: UnderdogGoalGateResult,
    bundle: FusionRecentFormBundle,
    underdog_ctx: UnderdogMatchContext,
    underdog_scores_probability: float,
    btts_probability: float,
) -> tuple[GateLevel, list[str]]:
    """Gate level using fusion read-path form + conservative support adjustment."""
    reason_codes: list[str] = []
    if underdog_ctx.is_balanced or underdog_ctx.favorite_side == "none":
        return baseline_gate.level, reason_codes

    shadow_result = compute_underdog_goal_gate(
        underdog_ctx=underdog_ctx,
        underdog_scores_probability=underdog_scores_probability,
        btts_probability=btts_probability,
        recent_form=bundle.scoring,
    )
    level = shadow_result.level
    if bundle.support_level == "unavailable" or bundle.support_level == "weak":
        return baseline_gate.level, reason_codes

    adjusted = level
    if bundle.support_level == "strong" and bundle.coverage_quality in {"high", "medium"}:
        adjusted = move_gate_toward(
            level,
            "STRONG_ALLOW",
            max_steps=config.RECENT_FORM_MAX_GATE_STEP_DELTA,
        )
    elif bundle.support_level == "negative":
        adjusted = move_gate_toward(
            level,
            "BLOCK",
            max_steps=config.RECENT_FORM_MAX_GATE_STEP_DELTA,
        )

    if adjusted != baseline_gate.level:
        reason_codes.append(RECENT_FORM_SHADOW_GATE_ADJUSTED)
    return adjusted, reason_codes


def resolve_active_gate_level(
    *,
    baseline_level: GateLevel,
    shadow_level: GateLevel,
    bundle: FusionRecentFormBundle,
    underdog_ctx: UnderdogMatchContext,
    underdog_scores_probability: float,
    btts_probability: float,
    comparison: CandidateComparisonSummary | None,
) -> tuple[GateLevel, list[str], bool]:
    """Bounded active gate move (max one level) toward shadow when safe."""
    reason_codes: list[str] = []
    if not config.recent_form_active_experiment_enabled():
        return baseline_level, reason_codes, False

    if bundle.coverage_quality not in config.recent_form_min_coverage_for_active():
        reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_LOW_COVERAGE)
        return baseline_level, reason_codes, False

    if bundle.support_level in {"unavailable", "weak"}:
        reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_WEAK_SUPPORT)
        return baseline_level, reason_codes, False

    if underdog_ctx.underdog_xg < 0.55 or btts_probability < 35:
        reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_XG_BTTS)
        return baseline_level, reason_codes, False

    prob_gap = comparison.exact_probability_gap if comparison else None
    if prob_gap is not None and prob_gap > LARGE_CANDIDATE_PROB_GAP:
        reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_CANDIDATE_GAP)
        return baseline_level, reason_codes, False

    max_steps = max(1, config.RECENT_FORM_MAX_GATE_STEP_DELTA)
    candidate_level = move_gate_toward(baseline_level, shadow_level, max_steps=max_steps)

    if candidate_level == baseline_level:
        return baseline_level, reason_codes, False

    more_permissive = _gate_permissiveness(candidate_level) > _gate_permissiveness(baseline_level)
    if more_permissive:
        if bundle.support_level not in {"strong", "moderate"}:
            reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_WEAK_SUPPORT)
            return baseline_level, reason_codes, False
        if prob_gap is not None and prob_gap > CLOSE_CANDIDATE_PROB_GAP and bundle.support_level != "strong":
            reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_CANDIDATE_GAP)
            return baseline_level, reason_codes, False
    elif bundle.support_level != "negative":
        reason_codes.append(RECENT_FORM_ACTIVE_BLOCKED_WEAK_SUPPORT)
        return baseline_level, reason_codes, False

    reason_codes.append(RECENT_FORM_ACTIVE_APPLIED)
    return candidate_level, reason_codes, True


def gate_result_with_level(
    gate: UnderdogGoalGateResult,
    level: GateLevel,
    *,
    extra_reason_codes: list[str] | None = None,
) -> UnderdogGoalGateResult:
    codes = list(gate.reason_codes)
    if extra_reason_codes:
        codes.extend(extra_reason_codes)
    return replace(gate, level=level, reason_codes=list(dict.fromkeys(codes)))


def build_recent_form_shadow_diagnostics(
    bundle: FusionRecentFormBundle,
    *,
    baseline_gate: UnderdogGoalGateResult,
    shadow_level: GateLevel,
    active_level: GateLevel,
    would_change_gate: bool,
    would_change_primary_score: bool,
    active_change_applied: bool,
    shadow_primary_score: str | None,
    extra_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    scoring = bundle.scoring
    reason_codes = list(bundle.reason_codes)
    if extra_reason_codes:
        reason_codes.extend(extra_reason_codes)
    return {
        "enabled": config.recent_form_shadow_enabled(),
        "affects_scoreline": config.RECENT_FORM_AFFECTS_SCORELINE,
        "active_experiment_enabled": config.recent_form_active_experiment_enabled(),
        "recent_form_available": scoring.recent_form_available,
        "recent_form_confidence": scoring.recent_form_confidence,
        "matches_found": scoring.matches_found,
        "requested_match_count": scoring.requested_match_count,
        "last_10_scored_rate": scoring.last_10_scored_rate,
        "failed_to_score_rate": scoring.last_10_failed_to_score_rate,
        "goals_for_avg": scoring.last_10_goals_for_avg,
        "goals_against_avg": scoring.last_10_goals_against_avg,
        "clean_sheet_rate": bundle.clean_sheet_rate,
        "source_mix": dict(bundle.source_mix),
        "competition_mix": dict(bundle.competition_mix),
        "coverage_quality": bundle.coverage_quality,
        "freshness_gap_days": bundle.freshness_gap_days,
        "latest_match_date": bundle.latest_match_date,
        "support_level": bundle.support_level,
        "current_gate_level": baseline_gate.level,
        "shadow_gate_level": shadow_level,
        "active_gate_level": active_level,
        "would_change_gate": would_change_gate,
        "would_change_primary_score": would_change_primary_score,
        "active_change_applied": active_change_applied,
        "shadow_primary_score": shadow_primary_score,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "warnings": list(bundle.warnings),
    }


def evaluate_recent_form_shadow(
    *,
    underdog_ctx: UnderdogMatchContext | None,
    baseline_gate: UnderdogGoalGateResult,
    underdog_scores_probability: float,
    btts_probability: float,
    comparison: CandidateComparisonSummary | None,
    baseline_primary_label: str | None,
    shadow_primary_label: str | None,
) -> RecentFormShadowOutcome:
    """Compute shadow/active gate diagnostics for a representative pick."""
    if not config.recent_form_shadow_enabled() or not underdog_ctx or not underdog_ctx.underdog_team:
        return RecentFormShadowOutcome(
            baseline_gate_level=baseline_gate.level,
            shadow_gate_level=baseline_gate.level,
            active_gate_level=baseline_gate.level,
            would_change_gate=False,
            would_change_primary_score=False,
            active_change_applied=False,
            shadow_primary_score=shadow_primary_label,
            diagnostics={},
        )

    bundle = load_fusion_recent_form_bundle(
        underdog_ctx.underdog_team,
        favorite_power=underdog_ctx.favorite_power,
    )
    shadow_level, shadow_codes = compute_shadow_gate_level(
        baseline_gate=baseline_gate,
        bundle=bundle,
        underdog_ctx=underdog_ctx,
        underdog_scores_probability=underdog_scores_probability,
        btts_probability=btts_probability,
    )
    active_level, active_codes, active_applied = resolve_active_gate_level(
        baseline_level=baseline_gate.level,
        shadow_level=shadow_level,
        bundle=bundle,
        underdog_ctx=underdog_ctx,
        underdog_scores_probability=underdog_scores_probability,
        btts_probability=btts_probability,
        comparison=comparison,
    )

    would_change_gate = shadow_level != baseline_gate.level
    would_change_primary = bool(
        shadow_primary_label
        and baseline_primary_label
        and shadow_primary_label != baseline_primary_label
    )

    diagnostics = build_recent_form_shadow_diagnostics(
        bundle,
        baseline_gate=baseline_gate,
        shadow_level=shadow_level,
        active_level=active_level,
        would_change_gate=would_change_gate,
        would_change_primary_score=would_change_primary,
        active_change_applied=active_applied,
        shadow_primary_score=shadow_primary_label,
        extra_reason_codes=[*shadow_codes, *active_codes],
    )

    return RecentFormShadowOutcome(
        baseline_gate_level=baseline_gate.level,
        shadow_gate_level=shadow_level,
        active_gate_level=active_level,
        would_change_gate=would_change_gate,
        would_change_primary_score=would_change_primary,
        active_change_applied=active_applied,
        shadow_primary_score=shadow_primary_label,
        diagnostics=diagnostics,
    )


def bundle_to_dict(bundle: FusionRecentFormBundle) -> dict[str, Any]:
    payload = asdict(bundle)
    payload["scoring"] = bundle.scoring.to_dict()
    return payload
