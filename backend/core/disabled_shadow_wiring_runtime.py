"""Priority 1.7B.23 — Disabled-by-default NR3+FCC shadow wiring runtime helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable

from core.priority1_options import Priority1Config

FLAG_NAME = "NR3_FCC_SHADOW_ENABLED"
SHADOW_STACK = "NR3+FCC"
BASELINE_STACK = "production_baseline"
SHADOW_SUBJECT = "NR3+FCC"


@dataclass(frozen=True)
class ShadowWiringDecision:
    shadow_enabled: bool
    shadow_executed: bool
    should_run: bool
    reason: str
    activation_allowed: bool = False
    production_activation_allowed: bool = False
    direct_activation_allowed: bool = False
    served_output_change_allowed: bool = False


@dataclass
class ShadowComparison:
    xg_home_baseline: float | None = None
    xg_away_baseline: float | None = None
    xg_home_shadow: float | None = None
    xg_away_shadow: float | None = None
    total_xg_baseline: float | None = None
    total_xg_shadow: float | None = None
    xg_total_delta: float | None = None
    favorite_side_baseline: str | None = None
    favorite_side_shadow: str | None = None
    favorite_share_baseline: float | None = None
    favorite_share_shadow: float | None = None
    favorite_share_delta: float | None = None
    probabilities_1x2_baseline: dict[str, float] | None = None
    probabilities_1x2_shadow: dict[str, float] | None = None
    top5_baseline: list[str] = field(default_factory=list)
    top5_shadow: list[str] = field(default_factory=list)
    top10_baseline: list[str] = field(default_factory=list)
    top10_shadow: list[str] = field(default_factory=list)
    top5_overlap: float | None = None
    top10_overlap: float | None = None
    unavailable_fields: list[str] = field(default_factory=list)


@dataclass
class ShadowArtifact:
    shadow_enabled: bool
    shadow_executed: bool
    served_output_unchanged: bool
    served_stack: str
    shadow_stack: str
    model_version_baseline: str
    model_version_shadow: str
    comparison: ShadowComparison
    sanity_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    rollback_available: bool = True
    activation_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["activation_allowed"] = False
        return d


@dataclass
class ShadowRuntimeResult:
    decision: ShadowWiringDecision
    artifact: ShadowArtifact | None
    served_snapshot_before: dict[str, Any] | None = None
    served_snapshot_after: dict[str, Any] | None = None


def should_run_nr3_fcc_shadow(options: Priority1Config | Any) -> bool:
    """True only when explicit local shadow flag is enabled."""
    enabled = bool(getattr(options, "nr3_fcc_shadow_enabled", False))
    if not enabled:
        return False
    # Shadow stack requires strength path + FCC prototype availability
    return True


def build_nr3_fcc_shadow_priority1_config(*, dataset_key: str | None = None) -> Priority1Config:
    """Build NR3+FCC stack config with shadow flag forced off (prevents recursion)."""
    from core.favorite_confidence_curve_prototype import build_fcc_stack, fcc_fixed_params
    from core.strength_activation_readiness_audit import nr3_finalist_spec

    shadow_p1 = build_fcc_stack(nr3_finalist_spec().params, fcc_fixed_params())
    return replace(
        shadow_p1,
        nr3_fcc_shadow_enabled=False,
        dataset_key=dataset_key,
    )


def _favorite_side(home_xg: float, away_xg: float) -> str:
    return "home" if home_xg >= away_xg else "away"


def _favorite_share(home_xg: float, away_xg: float) -> float:
    total = max(home_xg + away_xg, 1e-9)
    return max(home_xg, away_xg) / total


def _scorelines_from_result(result: dict[str, Any], *, top_k: int) -> list[str]:
    from core.backtest_metrics import scorelines_from_matrix

    all_scores = result.get("all_scores") or {}
    lines = scorelines_from_matrix(all_scores, top_k=top_k)
    if lines:
        return lines
    return [item.get("score", "") for item in (result.get("top_scores") or [])[:top_k]]


def _overlap(a: list[str], b: list[str]) -> float | None:
    if not a and not b:
        return None
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return None
    return len(sa & sb) / len(union)


def _extract_probs(result: dict[str, Any]) -> dict[str, float] | None:
    raw = result.get("probabilities_1x2")
    if not raw:
        return None
    return {
        "home": float(raw.get("home_win", raw.get("home", 0.0))),
        "draw": float(raw.get("draw", 0.0)),
        "away": float(raw.get("away_win", raw.get("away", 0.0))),
    }


def extract_served_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    """Capture served prediction fields only — excludes internal shadow keys."""
    return {
        "probabilities_1x2": _extract_probs(result),
        "expected_home_goals": result.get("expected_home_goals"),
        "expected_away_goals": result.get("expected_away_goals"),
        "top_scores": list(result.get("top_scores") or []),
    }


def verify_served_output_unchanged(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Validate served prediction fields were not altered by shadow sidecar."""
    if before.get("probabilities_1x2") != after.get("probabilities_1x2"):
        return False
    if before.get("expected_home_goals") != after.get("expected_home_goals"):
        return False
    if before.get("expected_away_goals") != after.get("expected_away_goals"):
        return False
    if before.get("top_scores") != after.get("top_scores"):
        return False
    return True


def build_shadow_artifact(
    *,
    baseline_result: dict[str, Any],
    shadow_result: dict[str, Any] | None,
    shadow_enabled: bool,
    shadow_executed: bool,
) -> ShadowArtifact:
    """Build private shadow artifact; marks unavailable fields explicitly."""
    unavailable: list[str] = []
    b_home = baseline_result.get("expected_home_goals")
    b_away = baseline_result.get("expected_away_goals")
    if b_home is None or b_away is None:
        unavailable.append("xg_baseline_from_result")

    s_home = shadow_result.get("expected_home_goals") if shadow_result else None
    s_away = shadow_result.get("expected_away_goals") if shadow_result else None
    if shadow_result and (s_home is None or s_away is None):
        unavailable.append("xg_shadow_from_result")

    top5_b = _scorelines_from_result(baseline_result, top_k=5)
    top10_b = _scorelines_from_result(baseline_result, top_k=10)
    top5_s = _scorelines_from_result(shadow_result, top_k=5) if shadow_result else []
    top10_s = _scorelines_from_result(shadow_result, top_k=10) if shadow_result else []

    if shadow_result and not top5_s:
        unavailable.append("top5_shadow")

    b_probs = _extract_probs(baseline_result)
    s_probs = _extract_probs(shadow_result) if shadow_result else None

    total_b = (float(b_home) + float(b_away)) if b_home is not None and b_away is not None else None
    total_s = (float(s_home) + float(s_away)) if s_home is not None and s_away is not None else None
    xg_delta = (total_s - total_b) if total_s is not None and total_b is not None else None

    fav_share_b = _favorite_share(float(b_home), float(b_away)) if b_home is not None and b_away is not None else None
    fav_share_s = _favorite_share(float(s_home), float(s_away)) if s_home is not None and s_away is not None else None

    comparison = ShadowComparison(
        xg_home_baseline=float(b_home) if b_home is not None else None,
        xg_away_baseline=float(b_away) if b_away is not None else None,
        xg_home_shadow=float(s_home) if s_home is not None else None,
        xg_away_shadow=float(s_away) if s_away is not None else None,
        total_xg_baseline=total_b,
        total_xg_shadow=total_s,
        xg_total_delta=xg_delta,
        favorite_side_baseline=_favorite_side(float(b_home), float(b_away)) if b_home is not None and b_away is not None else None,
        favorite_side_shadow=_favorite_side(float(s_home), float(s_away)) if s_home is not None and s_away is not None else None,
        favorite_share_baseline=fav_share_b,
        favorite_share_shadow=fav_share_s,
        favorite_share_delta=(fav_share_s - fav_share_b) if fav_share_s is not None and fav_share_b is not None else None,
        probabilities_1x2_baseline=b_probs,
        probabilities_1x2_shadow=s_probs,
        top5_baseline=top5_b,
        top5_shadow=top5_s,
        top10_baseline=top10_b,
        top10_shadow=top10_s,
        top5_overlap=_overlap(top5_b, top5_s),
        top10_overlap=_overlap(top10_b, top10_s),
        unavailable_fields=unavailable,
    )

    sanity: list[str] = []
    risk: list[str] = []
    if not shadow_executed and shadow_enabled:
        risk.append("shadow_enabled_but_not_executed")
    if comparison.favorite_side_baseline and comparison.favorite_side_shadow:
        if comparison.favorite_side_baseline != comparison.favorite_side_shadow:
            risk.append("favorite_side_flip_shadow_vs_baseline")
    if xg_delta is not None and abs(xg_delta) > 0.35:
        risk.append("xg_total_delta_warning")

    return ShadowArtifact(
        shadow_enabled=shadow_enabled,
        shadow_executed=shadow_executed,
        served_output_unchanged=True,
        served_stack=BASELINE_STACK,
        shadow_stack=SHADOW_STACK,
        model_version_baseline="baseline_served",
        model_version_shadow=SHADOW_STACK if shadow_executed else "not_executed",
        comparison=comparison,
        sanity_flags=sanity,
        risk_flags=risk,
        rollback_available=True,
        activation_allowed=False,
    )


def create_disabled_shadow_result(*, reason: str = "flag_false") -> ShadowRuntimeResult:
    """When disabled — no NR3+FCC execution."""
    decision = ShadowWiringDecision(
        shadow_enabled=False,
        shadow_executed=False,
        should_run=False,
        reason=reason,
    )
    artifact = ShadowArtifact(
        shadow_enabled=False,
        shadow_executed=False,
        served_output_unchanged=True,
        served_stack=BASELINE_STACK,
        shadow_stack=SHADOW_STACK,
        model_version_baseline="baseline_served",
        model_version_shadow="disabled",
        comparison=ShadowComparison(),
        rollback_available=True,
        activation_allowed=False,
    )
    return ShadowRuntimeResult(decision=decision, artifact=artifact)


def run_nr3_fcc_shadow_sidecar(
    *,
    baseline_result: dict[str, Any],
    match: Any,
    prior: list[Any],
    snapshot: Any,
    dataset_key: str,
    baseline_p1: Priority1Config,
    candidate: str,
    elo_strategy: str,
    world_elo_mode: str,
    prior_mode: str,
    run_match_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute NR3+FCC shadow artifact without mutating baseline served fields.
    Returns artifact dict for private internal diagnostics only.
    """
    served_before = extract_served_snapshot(baseline_result)

    shadow_p1 = build_nr3_fcc_shadow_priority1_config(dataset_key=dataset_key)
    shadow_result = run_match_fn(
        match,
        prior=prior,
        snapshot=snapshot,
        dataset_key=dataset_key,
        p1=shadow_p1,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
    )

    artifact = build_shadow_artifact(
        baseline_result=baseline_result,
        shadow_result=shadow_result,
        shadow_enabled=True,
        shadow_executed=True,
    )

    served_after = extract_served_snapshot(baseline_result)
    unchanged = verify_served_output_unchanged(served_before, served_after)
    artifact.served_output_unchanged = unchanged
    if not unchanged:
        artifact.risk_flags = list(artifact.risk_flags) + ["served_output_mutation_detected"]

    return artifact.to_dict()


def attach_shadow_sidecar_if_enabled(
    result: dict[str, Any],
    *,
    match: Any,
    prior: list[Any],
    snapshot: Any,
    dataset_key: str,
    p1: Priority1Config,
    candidate: str,
    elo_strategy: str,
    world_elo_mode: str,
    prior_mode: str,
    run_match_fn: Callable[..., dict[str, Any]],
) -> ShadowRuntimeResult:
    """Optional backtest hook — no-op when flag false; private artifact when true."""
    if not should_run_nr3_fcc_shadow(p1):
        return create_disabled_shadow_result()

    served_before = extract_served_snapshot(result)
    artifact_dict = run_nr3_fcc_shadow_sidecar(
        baseline_result=result,
        match=match,
        prior=prior,
        snapshot=snapshot,
        dataset_key=dataset_key,
        baseline_p1=p1,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
        run_match_fn=run_match_fn,
    )
    result.setdefault("_internal_diagnostics", {})["nr3_fcc_shadow"] = artifact_dict

    served_after = extract_served_snapshot(result)
    decision = ShadowWiringDecision(
        shadow_enabled=True,
        shadow_executed=bool(artifact_dict.get("shadow_executed")),
        should_run=True,
        reason="nr3_fcc_shadow_enabled",
    )
    return ShadowRuntimeResult(
        decision=decision,
        artifact=None,
        served_snapshot_before=served_before,
        served_snapshot_after=served_after,
    )


def attach_shadow_sidecar_if_enabled(
    result: dict[str, Any],
    *,
    match: Any,
    prior: list[Any],
    snapshot: Any,
    dataset_key: str,
    p1: Priority1Config,
    candidate: str,
    elo_strategy: str,
    world_elo_mode: str,
    prior_mode: str,
    run_match_fn: Callable[..., dict[str, Any]],
) -> ShadowRuntimeResult:
    """Optional backtest hook — no-op when flag false; private artifact when true."""
    if not should_run_nr3_fcc_shadow(p1):
        return create_disabled_shadow_result()

    served_before = extract_served_snapshot(result)
    artifact_dict = run_nr3_fcc_shadow_sidecar(
        baseline_result=result,
        match=match,
        prior=prior,
        snapshot=snapshot,
        dataset_key=dataset_key,
        baseline_p1=p1,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
        run_match_fn=run_match_fn,
    )
    result.setdefault("_internal_diagnostics", {})["nr3_fcc_shadow"] = artifact_dict

    served_after = extract_served_snapshot(result)
    decision = ShadowWiringDecision(
        shadow_enabled=True,
        shadow_executed=bool(artifact_dict.get("shadow_executed")),
        should_run=True,
        reason="nr3_fcc_shadow_enabled",
    )
    return ShadowRuntimeResult(
        decision=decision,
        artifact=None,
        served_snapshot_before=served_before,
        served_snapshot_after=served_after,
    )
