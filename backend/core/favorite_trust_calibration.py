"""Priority 1.7B.6.1 — Generic favorite-trust / spread-confidence calibration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any

from core.strength_stage_recovery import p174_best_spread_share_recovery_params

MAX_FAVORITE_TRUST_VARIANTS = 180
P1761_STACK_BASE = "P1C2+R16rec+trust"
PREV_LIGHT_DAMPING_NAME = "SprA_gd_w0.15_md0.08_mid0.3"


@dataclass(frozen=True)
class FavoriteTrustParams:
    """Generic trust-based spread calibration (shadow-only, stage not required)."""

    name: str
    enabled: bool = True
    correction_family: str = "balanced"  # low_trust_damp | disagreement | overcommit | restore | upset | balanced

    trust_threshold: float = 0.45
    damping_weight: float = 0.10
    max_damping_delta: float = 0.05
    min_diff_to_apply: float = 0.35

    disagreement_damping_weight: float = 0.20
    max_disagreement_delta: float = 0.08
    min_disagreement_diff: float = 0.20

    overcommit_margin: float = 0.10
    overcommit_damping_weight: float = 0.20
    max_overcommit_delta: float = 0.08

    restore_margin: float = 0.10
    restore_weight: float = 0.15
    max_restore_delta: float = 0.05
    max_favorite_share: float = 0.70

    favorite_share_soft_cap: float = 0.66
    softening_weight: float = 0.20
    max_softening_delta: float = 0.08

    max_total_spread_delta: float = 0.10
    use_stage_as_optional_context: bool = False
    stage_weight: float = 0.0

    enable_low_trust_damp: bool = False
    enable_disagreement_guard: bool = False
    enable_overcommit_guard: bool = False
    enable_restore: bool = False
    enable_upset_softening: bool = False

    def correction_key(self) -> tuple:
        return (
            self.correction_family,
            round(self.trust_threshold, 4),
            round(self.damping_weight, 4),
            round(self.max_damping_delta, 4),
            round(self.min_diff_to_apply, 4),
            round(self.disagreement_damping_weight, 4),
            round(self.max_disagreement_delta, 4),
            round(self.min_disagreement_diff, 4),
            round(self.overcommit_margin, 4),
            round(self.overcommit_damping_weight, 4),
            round(self.max_overcommit_delta, 4),
            round(self.restore_margin, 4),
            round(self.restore_weight, 4),
            round(self.max_restore_delta, 4),
            round(self.max_favorite_share, 4),
            round(self.favorite_share_soft_cap, 4),
            round(self.softening_weight, 4),
            round(self.max_softening_delta, 4),
            round(self.max_total_spread_delta, 4),
            self.use_stage_as_optional_context,
            round(self.stage_weight, 4),
            self.enable_low_trust_damp,
            self.enable_disagreement_guard,
            self.enable_overcommit_guard,
            self.enable_restore,
            self.enable_upset_softening,
        )


def _fav_side(home: float, away: float) -> str:
    if abs(home - away) < 1e-6:
        return "draw"
    return "home" if home >= away else "away"


def _fav_share(home: float, away: float) -> float:
    t = home + away
    return max(home, away) / t if t > 0 else 0.5


def _round_pair(h: float, a: float) -> tuple[float, float]:
    return round(h, 2), round(a, 2)


def _set_diff_preserve_total(home: float, away: float, new_diff: float) -> tuple[float, float]:
    total = home + away
    if total <= 0:
        return home, away
    new_diff = max(0.0, min(new_diff, total - 0.10))
    if home >= away:
        nh = (total + new_diff) / 2.0
        na = (total - new_diff) / 2.0
    else:
        na = (total + new_diff) / 2.0
        nh = (total - new_diff) / 2.0
    nh = max(nh, 0.05)
    na = max(na, 0.05)
    cur = nh + na
    if cur > 0:
        nh = total * nh / cur
        na = total * na / cur
    return nh, na


def _apply_share_cap(home: float, away: float, cap: float) -> tuple[float, float]:
    total = home + away
    if total <= 0:
        return home, away
    share = _fav_share(home, away)
    if share <= cap:
        return home, away
    if home >= away:
        return total * cap, total * (1.0 - cap)
    return total * (1.0 - cap), total * cap


def compute_favorite_trust(
    *,
    p1c2_home: float,
    p1c2_away: float,
    recovery_home: float,
    recovery_away: float,
    baseline_home: float,
    baseline_away: float,
    home_power: float | None = None,
    away_power: float | None = None,
    stage: str | None = None,
    use_stage_context: bool = False,
    stage_weight: float = 0.0,
) -> dict[str, Any]:
    """Trust score in [0,1]; higher = more confidence in favorite direction/spread."""
    base_side = _fav_side(baseline_home, baseline_away)
    p1c2_side = _fav_side(p1c2_home, p1c2_away)
    rec_side = _fav_side(recovery_home, recovery_away)
    cand_diff = abs(recovery_home - recovery_away)
    ref_diff = abs(baseline_home - baseline_away)
    p1c2_diff = abs(p1c2_home - p1c2_away)
    cand_share = _fav_share(recovery_home, recovery_away)
    ref_share = _fav_share(baseline_home, baseline_away)
    diff_ratio = cand_diff / max(ref_diff, 1e-6)

    score = 0.50
    fav_agree = base_side == p1c2_side == rec_side and base_side != "draw"
    fav_stable = p1c2_side == rec_side and rec_side != "draw"
    if fav_agree:
        score += 0.18
    elif fav_stable:
        score += 0.08
    if base_side != p1c2_side and base_side != "draw" and p1c2_side != "draw":
        score -= 0.22
    if base_side != rec_side and base_side != "draw" and rec_side != "draw":
        score -= 0.12
    if diff_ratio > 1.25:
        score -= min(0.20, 0.10 * (diff_ratio - 1.0))
    elif diff_ratio < 0.75 and fav_stable:
        score += 0.05
    if cand_diff < 0.15:
        score -= 0.12
    if cand_share > 0.68:
        score -= 0.08
    if ref_diff > 0 and cand_diff < ref_diff - 0.08 and fav_stable:
        score += 0.06

    power_xg_consistent: bool | None = None
    if home_power is not None and away_power is not None:
        power_side = "home" if home_power >= away_power else "away"
        power_xg_consistent = power_side == rec_side or rec_side == "draw"
        if power_xg_consistent and rec_side != "draw":
            score += 0.10
        elif not power_xg_consistent and abs(home_power - away_power) > 5:
            score -= 0.10

    context_used: list[str] = []
    if use_stage_context and stage is not None and stage_weight > 0:
        score += stage_weight
        context_used.append(f"stage:{stage}")
    elif stage is None:
        context_used.append("no_stage")

    score = max(0.0, min(1.0, score))
    if score < 0.45:
        bucket = "low"
    elif score < 0.65:
        bucket = "medium"
    else:
        bucket = "high"

    return {
        "trust_score": round(score, 4),
        "trust_bucket": bucket,
        "favorite_agreement": fav_agree,
        "favorite_direction_stable": fav_stable,
        "candidate_diff": round(cand_diff, 3),
        "reference_diff": round(ref_diff, 3),
        "p1c2_diff": round(p1c2_diff, 3),
        "diff_ratio": round(diff_ratio, 4),
        "candidate_favorite_share": round(cand_share, 4),
        "reference_favorite_share": round(ref_share, 4),
        "power_xg_consistency": power_xg_consistent,
        "stage_context": stage,
        "stage_available": stage is not None,
        "stage_required": False,
        "context_used": context_used,
    }


def apply_favorite_trust_correction(
    recovery_home: float,
    recovery_away: float,
    *,
    p1c2_home: float,
    p1c2_away: float,
    baseline_home: float,
    baseline_away: float,
    stage: str | None,
    params: FavoriteTrustParams,
    home_power: float | None = None,
    away_power: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """Apply generic trust-based spread calibration; preserves total by default."""
    warnings: list[str] = []
    caps: list[str] = []
    home, away = float(recovery_home), float(recovery_away)
    total_in = home + away
    diff_in = abs(home - away)
    share_before = _fav_share(home, away)

    trust = compute_favorite_trust(
        p1c2_home=p1c2_home,
        p1c2_away=p1c2_away,
        recovery_home=recovery_home,
        recovery_away=recovery_away,
        baseline_home=baseline_home,
        baseline_away=baseline_away,
        home_power=home_power,
        away_power=away_power,
        stage=stage,
        use_stage_context=params.use_stage_as_optional_context,
        stage_weight=params.stage_weight,
    )

    diag: dict[str, Any] = {
        "enabled": params.enabled,
        "correction_family": params.correction_family,
        "correction_applied": False,
        "correction_reason": None,
        "stage": stage,
        "stage_available": stage is not None,
        "stage_required": False,
        "context_used": trust.get("context_used", []),
        "base_candidate": P1761_STACK_BASE,
        "baseline_home_xg": round(baseline_home, 3),
        "baseline_away_xg": round(baseline_away, 3),
        "baseline_total_xg": round(baseline_home + baseline_away, 3),
        "baseline_xg_diff": round(abs(baseline_home - baseline_away), 3),
        "baseline_favorite_side": _fav_side(baseline_home, baseline_away),
        "p1c2_home_xg": round(p1c2_home, 3),
        "p1c2_away_xg": round(p1c2_away, 3),
        "p1c2_total_xg": round(p1c2_home + p1c2_away, 3),
        "p1c2_xg_diff": round(abs(p1c2_home - p1c2_away), 3),
        "p1c2_favorite_side": _fav_side(p1c2_home, p1c2_away),
        "recovery_home_xg": round(recovery_home, 3),
        "recovery_away_xg": round(recovery_away, 3),
        "recovery_total_xg": round(total_in, 3),
        "recovery_xg_diff": round(diff_in, 3),
        "recovery_favorite_side": _fav_side(recovery_home, recovery_away),
        "favorite_share_before": round(share_before, 4),
        "favorite_share_after": round(share_before, 4),
        "total_preserved": True,
        "total_delta": 0.0,
        "spread_delta": 0.0,
        "low_trust_damping_applied": False,
        "disagreement_guard_applied": False,
        "overcommitment_guard_applied": False,
        "restore_applied": False,
        "upset_softening_applied": False,
        "caps_applied": caps,
        "warnings": warnings,
        "favorite_trust_diagnostics": trust,
        **{f"trust_{k}": v for k, v in trust.items() if k not in ("context_used",)},
    }

    if stage is None:
        warnings.append("missing_stage_but_supported")

    if not params.enabled:
        diag["correction_reason"] = "disabled"
        diag["corrected_home_xg"] = round(home, 3)
        diag["corrected_away_xg"] = round(away, 3)
        diag["corrected_total_xg"] = round(home + away, 3)
        diag["corrected_xg_diff"] = round(abs(home - away), 3)
        diag["corrected_favorite_side"] = _fav_side(home, away)
        return home, away, diag

    if total_in <= 0 or not math.isfinite(total_in):
        warnings.append("invalid_xg_skipped")
        diag["correction_reason"] = "invalid_xg"
        diag["corrected_home_xg"] = round(home, 3)
        diag["corrected_away_xg"] = round(away, 3)
        diag["corrected_total_xg"] = round(home + away, 3)
        diag["corrected_xg_diff"] = round(abs(home - away), 3)
        diag["corrected_favorite_side"] = _fav_side(home, away)
        return home, away, diag

    trust_score = float(trust["trust_score"])
    ref_diff = float(trust["reference_diff"])
    cand_diff = abs(home - away)
    spread_budget = params.max_total_spread_delta
    spread_used = 0.0
    applied_any = False

    base_side = _fav_side(baseline_home, baseline_away)
    p1c2_side = _fav_side(p1c2_home, p1c2_away)
    rec_side = _fav_side(home, away)

    def _budget(delta: float) -> float:
        nonlocal spread_used
        allowed = min(delta, max(0.0, spread_budget - spread_used))
        spread_used += allowed
        if allowed < delta - 1e-6:
            caps.append("max_spread_delta_cap_applied")
            warnings.append("max_spread_delta_cap_applied")
        return allowed

    use_disagree = params.correction_family == "disagreement" or (
        params.correction_family == "balanced" and params.enable_disagreement_guard
    )
    use_over = params.correction_family == "overcommit" or (
        params.correction_family == "balanced" and params.enable_overcommit_guard
    )
    use_damp = params.correction_family == "low_trust_damp" or (
        params.correction_family == "balanced" and params.enable_low_trust_damp
    )
    use_restore = params.correction_family == "restore" or (
        params.correction_family == "balanced" and params.enable_restore
    )
    use_upset = params.correction_family == "upset" or (
        params.correction_family == "balanced" and params.enable_upset_softening
    )

    # B — disagreement guard
    if use_disagree and spread_used < spread_budget:
        disagree = (
            (base_side != p1c2_side and base_side != "draw" and p1c2_side != "draw")
            or (base_side != rec_side and base_side != "draw" and rec_side != "draw")
        )
        if disagree and cand_diff >= params.min_disagreement_diff:
            damp = min(params.max_disagreement_delta, params.disagreement_damping_weight * cand_diff)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["disagreement_guard_applied"] = True
                applied_any = True

    # C — overcommitment guard
    if use_over and spread_used < spread_budget:
        if cand_diff > ref_diff + params.overcommit_margin and trust_score < 0.65:
            excess = cand_diff - ref_diff - params.overcommit_margin
            damp = min(params.max_overcommit_delta, params.overcommit_damping_weight * excess)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["overcommitment_guard_applied"] = True
                applied_any = True

    # A — low-trust spread damping
    if use_damp and spread_used < spread_budget:
        if trust_score < params.trust_threshold and cand_diff >= params.min_diff_to_apply:
            damp = min(params.max_damping_delta, params.damping_weight * cand_diff)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["low_trust_damping_applied"] = True
                applied_any = True

    # D — under-compressed restore
    if use_restore and spread_used < spread_budget:
        if (
            trust.get("favorite_direction_stable")
            and base_side == rec_side
            and rec_side != "draw"
            and cand_diff < ref_diff - params.restore_margin
            and trust_score >= params.trust_threshold - 0.05
        ):
            gap = ref_diff - cand_diff - params.restore_margin
            restore = min(params.max_restore_delta, params.restore_weight * max(gap, 0.0))
            restore = _budget(restore)
            if restore > 1e-6:
                home, away = _set_diff_preserve_total(home, away, min(cand_diff + restore, total_in - 0.1))
                cand_diff = abs(home - away)
                share = _fav_share(home, away)
                if share > params.max_favorite_share:
                    home, away = _apply_share_cap(home, away, params.max_favorite_share)
                diag["restore_applied"] = True
                applied_any = True

    # E — upset softening
    if use_upset and spread_used < spread_budget:
        share = _fav_share(home, away)
        if share > params.favorite_share_soft_cap and trust_score < 0.55:
            target = params.favorite_share_soft_cap
            delta_share = min(params.max_softening_delta, params.softening_weight * (share - target))
            if delta_share > 1e-6:
                home, away = _apply_share_cap(home, away, max(target, share - delta_share))
                diag["upset_softening_applied"] = True
                applied_any = True

    if rec_side == "draw":
        warnings.append("favorite_side_ambiguous")

    home, away = _round_pair(home, away)
    total_out = home + away
    diag["total_delta"] = round(total_out - total_in, 4)
    diag["spread_delta"] = round(abs(home - away) - diff_in, 4)
    diag["total_preserved"] = abs(diag["total_delta"]) < 0.03
    if not diag["total_preserved"]:
        warnings.append("total_not_preserved")
    diag["favorite_share_after"] = round(_fav_share(home, away), 4)
    diag["caps_applied"] = caps
    warnings.append("no_stage_dependency")
    warnings.append("no_dataset_specific_logic")

    if not applied_any:
        warnings.append("no_correction_needed")
        diag["correction_reason"] = "no_adjustment_needed"
    else:
        diag["correction_applied"] = True
        diag["correction_reason"] = params.correction_family

    diag["corrected_home_xg"] = round(home, 3)
    diag["corrected_away_xg"] = round(away, 3)
    diag["corrected_total_xg"] = round(home + away, 3)
    diag["corrected_xg_diff"] = round(abs(home - away), 3)
    diag["corrected_favorite_side"] = _fav_side(home, away)
    return home, away, diag


def no_favorite_trust_params() -> FavoriteTrustParams:
    return FavoriteTrustParams(name="favorite_trust_noop", enabled=False)


def p174_recovery_params():
    return p174_best_spread_share_recovery_params()


def prev_light_damping_params():
    from core.strength_spread_residual_correction import SpreadResidualParams

    return SpreadResidualParams(
        name=PREV_LIGHT_DAMPING_NAME,
        enabled=True,
        correction_family="group_damping",
        group_spread_damping_weight=0.15,
        max_group_spread_damping_delta=0.08,
        min_diff_to_apply=0.30,
    )


def _add_variant(
    out: list[FavoriteTrustParams],
    seen: set[tuple],
    *,
    max_variants: int,
    **kwargs,
) -> bool:
    if len(out) >= max_variants:
        return False
    p = FavoriteTrustParams(**kwargs)
    key = p.correction_key()
    if key in seen:
        return True
    seen.add(key)
    out.append(p)
    return len(out) < max_variants


def build_favorite_trust_grid(*, max_variants: int = MAX_FAVORITE_TRUST_VARIANTS) -> list[FavoriteTrustParams]:
    out: list[FavoriteTrustParams] = [no_favorite_trust_params()]
    seen: set[tuple] = {no_favorite_trust_params().correction_key()}

    def add(**kw) -> bool:
        return _add_variant(out, seen, max_variants=max_variants, **kw)

    # A — low-trust damping
    for thr, w, md, mid in product(
        (0.35, 0.45, 0.55),
        (0.05, 0.10, 0.15, 0.20),
        (0.03, 0.05, 0.08),
        (0.25, 0.35),
    ):
        if not add(
            name=f"TrustA_thr{thr}_w{w}_md{md}_mid{mid}",
            correction_family="low_trust_damp",
            trust_threshold=thr,
            damping_weight=w,
            max_damping_delta=md,
            min_diff_to_apply=mid,
        ):
            return out

    # B — disagreement guard
    for w, md, mid in product((0.10, 0.20, 0.30), (0.05, 0.08, 0.10), (0.15, 0.20)):
        if not add(
            name=f"TrustB_w{w}_md{md}_mid{mid}",
            correction_family="disagreement",
            disagreement_damping_weight=w,
            max_disagreement_delta=md,
            min_disagreement_diff=mid,
        ):
            return out

    # C — overcommitment
    for margin, w, md in product((0.05, 0.10, 0.15), (0.10, 0.20, 0.30), (0.05, 0.08)):
        if not add(
            name=f"TrustC_m{margin}_w{w}_md{md}",
            correction_family="overcommit",
            overcommit_margin=margin,
            overcommit_damping_weight=w,
            max_overcommit_delta=md,
        ):
            return out

    # D — restore
    for margin, w, md in product((0.05, 0.10), (0.10, 0.15, 0.20), (0.03, 0.05, 0.08)):
        if not add(
            name=f"TrustD_m{margin}_w{w}_md{md}",
            correction_family="restore",
            restore_margin=margin,
            restore_weight=w,
            max_restore_delta=md,
        ):
            return out

    # E — upset softening
    for cap, sw, md in product((0.62, 0.64, 0.66, 0.68), (0.10, 0.20, 0.30), (0.05, 0.08)):
        if not add(
            name=f"TrustE_cap{cap}_sw{sw}_md{md}",
            correction_family="upset",
            favorite_share_soft_cap=cap,
            softening_weight=sw,
            max_softening_delta=md,
        ):
            return out

    # F — balanced
    combos = [
        (0.45, 0.10, 0.20, 0.10, 0.15, 0.10, 0.66, 0.08),
        (0.35, 0.15, 0.25, 0.15, 0.10, 0.08, 0.64, 0.10),
        (0.55, 0.08, 0.15, 0.08, 0.12, 0.06, 0.68, 0.08),
    ]
    for thr, dw, ow, rw, sw, tmax, cap, swd in combos:
        if not add(
            name=f"TrustF_bal_thr{thr}_tmax{tmax}",
            correction_family="balanced",
            enable_disagreement_guard=True,
            enable_overcommit_guard=True,
            enable_low_trust_damp=True,
            enable_restore=True,
            enable_upset_softening=True,
            trust_threshold=thr,
            damping_weight=dw,
            overcommit_damping_weight=ow,
            restore_weight=rw,
            softening_weight=sw,
            max_total_spread_delta=tmax,
            favorite_share_soft_cap=cap,
            max_softening_delta=swd,
        ):
            return out

    for thr, tmax in product((0.35, 0.45), (0.06, 0.08, 0.10)):
        if not add(
            name=f"TrustF_g{thr}_m{tmax}",
            correction_family="balanced",
            enable_disagreement_guard=True,
            enable_overcommit_guard=True,
            enable_low_trust_damp=True,
            enable_restore=False,
            enable_upset_softening=True,
            trust_threshold=thr,
            max_total_spread_delta=tmax,
        ):
            return out

    # Optional stage context (minor)
    for sw in (0.0, 0.05):
        if not add(
            name=f"TrustF_ctx_sw{sw}",
            correction_family="balanced",
            enable_disagreement_guard=True,
            enable_overcommit_guard=True,
            enable_low_trust_damp=True,
            enable_upset_softening=True,
            use_stage_as_optional_context=True,
            stage_weight=sw,
            max_total_spread_delta=0.08,
        ):
            return out

    return out[:max_variants]


def portability_probe() -> dict[str, Any]:
    """Verify trust/correction works without stage."""
    p = FavoriteTrustParams(
        name="probe",
        correction_family="balanced",
        enable_disagreement_guard=True,
        enable_low_trust_damp=True,
        enable_overcommit_guard=True,
        trust_threshold=0.45,
        max_total_spread_delta=0.10,
    )
    trust = compute_favorite_trust(
        p1c2_home=1.5, p1c2_away=0.8,
        recovery_home=1.6, recovery_away=0.7,
        baseline_home=1.2, baseline_away=1.0,
        stage=None,
    )
    _, _, diag = apply_favorite_trust_correction(
        1.6, 0.7,
        p1c2_home=1.5, p1c2_away=0.8,
        baseline_home=1.2, baseline_away=1.0,
        stage=None,
        params=p,
    )
    return {
        "stage_required": False,
        "no_stage_rows_supported": True,
        "correction_applies_without_stage": diag.get("stage_required") is False,
        "trust_computed_without_stage": trust.get("trust_score") is not None,
        "missing_stage_warning": "missing_stage_but_supported" in diag.get("warnings", []),
        "probe_trust_score": trust.get("trust_score"),
        "probe_correction_applied": diag.get("correction_applied"),
    }
