"""Priority 1.7B.6.3 — Hybrid balance tuning on trust-gated spread hybrid."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any, Callable

from core.favorite_trust_calibration import compute_favorite_trust, prev_light_damping_params
from core.strength_stage_recovery import p174_best_spread_share_recovery_params
from core.trust_gated_spread_hybrid import (
    TrustGatedSpreadHybridParams,
    _apply_share_cap,
    _fav_share,
    _fav_side,
    _round_pair,
    _set_diff_preserve_total,
)

MAX_HYBRID_BALANCE_VARIANTS = 180
P1763_STACK_BASE = "P1C2+R16rec+hybrid_balance"
PREV_BEST_H2_NAME = "HybH2_m0.05_lw0.4_md0.1"
PREV_SPRA_NAME = "SprA_gd_w0.15_md0.08_mid0.3"


@dataclass(frozen=True)
class HybridBalanceParams:
    """Tuned hybrid balance correction (shadow-only, stage not required)."""

    name: str
    enabled: bool = True
    correction_family: str = "hb1"  # hb1 | hb2 | hb3 | hb4 | hb5

    trust_low_threshold: float = 0.45
    trust_high_threshold: float = 0.65
    medium_bucket_uses_low_damping: bool = False
    low_or_medium_overcommit_guard: bool = False

    low_trust_damping_weight: float = 0.15
    medium_trust_damping_weight: float = 0.10
    high_trust_damping_weight: float = 0.03
    additional_spra_low_weight: float = 0.0
    additional_spra_medium_weight: float = 0.0
    additional_spra_high_weight: float = 0.0
    max_damping_delta: float = 0.08
    min_diff_to_apply: float = 0.30

    overcommit_margin: float = 0.05
    overcommit_damping_weight_low: float = 0.40
    overcommit_damping_weight_medium: float = 0.20
    max_overcommit_delta: float = 0.10

    disagreement_damping_weight: float = 0.25
    max_disagreement_delta: float = 0.08
    min_disagreement_diff: float = 0.20

    restore_margin: float = 0.10
    restore_weight: float = 0.10
    max_restore_delta: float = 0.05
    max_favorite_share: float = 0.70
    restore_enabled: bool = True

    max_total_spread_delta: float = 0.10
    correction_order: str = "h3_h2_h1_h4"  # h3_h2_h1_h4 | h2_h3_h1_h4 | h3_h1_h2_h4 | h2_h1_h4

    def correction_key(self) -> tuple:
        return (
            self.correction_family,
            self.correction_order,
            round(self.trust_low_threshold, 4),
            round(self.trust_high_threshold, 4),
            self.medium_bucket_uses_low_damping,
            self.low_or_medium_overcommit_guard,
            round(self.low_trust_damping_weight, 4),
            round(self.medium_trust_damping_weight, 4),
            round(self.high_trust_damping_weight, 4),
            round(self.additional_spra_low_weight, 4),
            round(self.additional_spra_medium_weight, 4),
            round(self.additional_spra_high_weight, 4),
            round(self.max_damping_delta, 4),
            round(self.min_diff_to_apply, 4),
            round(self.overcommit_margin, 4),
            round(self.overcommit_damping_weight_low, 4),
            round(self.max_overcommit_delta, 4),
            round(self.disagreement_damping_weight, 4),
            round(self.max_disagreement_delta, 4),
            round(self.max_total_spread_delta, 4),
            self.restore_enabled,
        )


def _trust_bucket(score: float, params: HybridBalanceParams) -> str:
    if score < params.trust_low_threshold:
        return "low"
    if score < params.trust_high_threshold:
        return "medium"
    return "high"


def _effective_bucket(bucket: str, params: HybridBalanceParams) -> str:
    if params.medium_bucket_uses_low_damping and bucket == "medium":
        return "low"
    return bucket


def _spra_weight(bucket: str, params: HybridBalanceParams) -> float:
    eb = _effective_bucket(bucket, params)
    base = {
        "low": params.low_trust_damping_weight,
        "medium": params.medium_trust_damping_weight,
        "high": params.high_trust_damping_weight,
    }[eb]
    extra = {
        "low": params.additional_spra_low_weight,
        "medium": params.additional_spra_medium_weight,
        "high": params.additional_spra_high_weight,
    }[eb]
    return base + extra


def apply_hybrid_balance_correction(
    recovery_home: float,
    recovery_away: float,
    *,
    p1c2_home: float,
    p1c2_away: float,
    baseline_home: float,
    baseline_away: float,
    stage: str | None,
    params: HybridBalanceParams,
    home_power: float | None = None,
    away_power: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    warnings: list[str] = [
        "no_actual_result_used",
        "no_dataset_specific_logic",
        "no_stage_dependency",
    ]
    caps: list[str] = []
    home, away = float(recovery_home), float(recovery_away)
    total_in = home + away
    diff_before = abs(home - away)
    share_before = _fav_share(home, away)

    trust_raw = compute_favorite_trust(
        p1c2_home=p1c2_home,
        p1c2_away=p1c2_away,
        recovery_home=recovery_home,
        recovery_away=recovery_away,
        baseline_home=baseline_home,
        baseline_away=baseline_away,
        home_power=home_power,
        away_power=away_power,
        stage=stage,
    )
    trust_score = float(trust_raw["trust_score"])
    bucket = _trust_bucket(trust_score, params)
    if params.medium_bucket_uses_low_damping and bucket == "medium":
        warnings.append("medium_bucket_treated_as_low")
    if not params.restore_enabled:
        warnings.append("restore_disabled")

    base_side = _fav_side(baseline_home, baseline_away)
    p1c2_side = _fav_side(p1c2_home, p1c2_away)
    rec_side = _fav_side(home, away)
    ref_diff = abs(baseline_home - baseline_away)
    cand_diff = diff_before
    diff_ratio_before = cand_diff / max(ref_diff, 1e-6)
    fav_side_before = rec_side
    damping_weight_selected: float | None = None

    diag: dict[str, Any] = {
        "enabled": params.enabled,
        "correction_family": params.correction_family,
        "correction_order": params.correction_order,
        "correction_applied": False,
        "correction_reason": None,
        "stage": stage,
        "stage_available": stage is not None,
        "stage_required": False,
        "context_used": trust_raw.get("context_used", []),
        "base_candidate": P1763_STACK_BASE,
        "trust_score": round(trust_score, 4),
        "trust_bucket": bucket,
        "trust_low_threshold": params.trust_low_threshold,
        "trust_high_threshold": params.trust_high_threshold,
        "baseline_xg_diff": round(ref_diff, 3),
        "candidate_xg_diff_before": round(diff_before, 3),
        "reference_diff": round(ref_diff, 3),
        "diff_ratio_before": round(diff_ratio_before, 4),
        "favorite_side_before": fav_side_before,
        "favorite_agreement": trust_raw.get("favorite_agreement"),
        "favorite_direction_stable": trust_raw.get("favorite_direction_stable"),
        "damping_weight_selected": None,
        "h2_wrong_favorite_guard_applied": False,
        "h1_spra_damping_applied": False,
        "h2_overcommitment_guard_applied": False,
        "h4_restore_applied": False,
        "restore_enabled": params.restore_enabled,
        "spread_delta_total": 0.0,
        "max_total_spread_delta": params.max_total_spread_delta,
        "cap_applied": False,
        "total_preserved": True,
        "total_delta": 0.0,
        "warnings": warnings,
        "hybrid_balance_diagnostics": {**trust_raw, "trust_bucket": bucket},
    }

    if stage is None:
        warnings.append("missing_stage_but_supported")

    if not params.enabled or total_in <= 0 or not math.isfinite(total_in):
        if total_in <= 0:
            warnings.append("invalid_xg_skipped")
        diag.update(_final_diag(home, away, total_in, diff_before, fav_side_before, share_before, diag))
        return home, away, diag

    spread_budget = params.max_total_spread_delta
    spread_used = 0.0
    applied_any = False

    def _budget(delta: float) -> float:
        nonlocal spread_used
        allowed = min(delta, max(0.0, spread_budget - spread_used))
        spread_used += allowed
        if allowed < delta - 1e-6:
            caps.append("max_spread_delta_cap_applied")
            diag["cap_applied"] = True
            warnings.append("max_spread_delta_cap_applied")
        return allowed

    compressed = (
        trust_raw.get("favorite_direction_stable")
        and base_side == rec_side
        and rec_side != "draw"
        and cand_diff < ref_diff - 0.05
    )

    def _h3_wrong_favorite() -> None:
        nonlocal home, away, cand_diff, applied_any
        if spread_used >= spread_budget:
            return
        disagree = (
            (base_side != p1c2_side and base_side != "draw" and p1c2_side != "draw")
            or (base_side != rec_side and base_side != "draw" and rec_side != "draw")
            or bucket == "low"
        )
        if not disagree or cand_diff < params.min_disagreement_diff:
            return
        damp = min(params.max_disagreement_delta, params.disagreement_damping_weight * cand_diff)
        if bucket == "low":
            damp = min(params.max_disagreement_delta, damp * 1.2)
        damp = _budget(damp)
        if damp > 1e-6:
            home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
            cand_diff = abs(home - away)
            diag["h2_wrong_favorite_guard_applied"] = True
            applied_any = True

    def _h2_overcommit() -> None:
        nonlocal home, away, cand_diff, applied_any
        if spread_used >= spread_budget:
            return
        eb = _effective_bucket(bucket, params)
        if eb == "high" and not params.low_or_medium_overcommit_guard:
            return
        if bucket == "high" and not params.low_or_medium_overcommit_guard:
            return
        if cand_diff <= ref_diff + params.overcommit_margin:
            return
        excess = cand_diff - ref_diff - params.overcommit_margin
        ow = params.overcommit_damping_weight_low if eb == "low" else params.overcommit_damping_weight_medium
        damp = min(params.max_overcommit_delta, ow * excess)
        damp = _budget(damp)
        if damp > 1e-6:
            home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
            cand_diff = abs(home - away)
            diag["h2_overcommitment_guard_applied"] = True
            applied_any = True

    def _h1_spra() -> None:
        nonlocal home, away, cand_diff, applied_any, damping_weight_selected
        if spread_used >= spread_budget or compressed:
            return
        if bucket == "high" and _spra_weight(bucket, params) < 1e-6:
            return
        if cand_diff < params.min_diff_to_apply:
            return
        dw = _spra_weight(bucket, params)
        damping_weight_selected = dw
        if cand_diff > ref_diff + 0.05 or (bucket in ("low", "medium") and cand_diff >= 0.45):
            excess = max(cand_diff - ref_diff, 0.05) if cand_diff > ref_diff else cand_diff * 0.15
            damp = min(params.max_damping_delta, dw * excess)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["h1_spra_damping_applied"] = True
                applied_any = True

    def _h4_restore() -> None:
        nonlocal home, away, cand_diff, applied_any
        if not params.restore_enabled or spread_used >= spread_budget:
            return
        if not (
            trust_raw.get("favorite_direction_stable")
            and base_side == rec_side
            and rec_side != "draw"
            and cand_diff < ref_diff - params.restore_margin
            and bucket in ("medium", "high")
        ):
            return
        gap = ref_diff - cand_diff - params.restore_margin
        restore = min(params.max_restore_delta, params.restore_weight * max(gap, 0.0))
        restore = _budget(restore)
        if restore > 1e-6:
            home, away = _set_diff_preserve_total(home, away, min(cand_diff + restore, total_in - 0.1))
            cand_diff = abs(home - away)
            if _fav_share(home, away) > params.max_favorite_share:
                home, away = _apply_share_cap(home, away, params.max_favorite_share)
            diag["h4_restore_applied"] = True
            applied_any = True

    steps: dict[str, Callable[[], None]] = {
        "h3": _h3_wrong_favorite,
        "h2": _h2_overcommit,
        "h1": _h1_spra,
        "h4": _h4_restore,
    }
    order = params.correction_order.split("_")
    for key in order:
        if key in steps:
            steps[key]()

    if fav_side_before == "draw":
        warnings.append("favorite_side_ambiguous")

    diag["damping_weight_selected"] = damping_weight_selected
    home, away = _round_pair(home, away)
    diff_after = abs(home - away)
    diag["spread_delta_total"] = round(diff_after - diff_before, 4)
    diag.update(
        _final_diag(home, away, total_in, diff_before, fav_side_before, share_before, diag, diff_after)
    )

    if not applied_any:
        warnings.append("no_correction_needed")
        diag["correction_reason"] = "no_adjustment_needed"
    else:
        diag["correction_applied"] = True
        diag["correction_reason"] = params.correction_family

    return home, away, diag


def _final_diag(
    home: float,
    away: float,
    total_in: float,
    diff_before: float,
    fav_side_before: str,
    share_before: float,
    diag: dict[str, Any],
    diff_after: float | None = None,
) -> dict[str, Any]:
    diff_after = diff_after if diff_after is not None else abs(home - away)
    total_out = home + away
    ref = float(diag.get("reference_diff", 0))
    return {
        "candidate_xg_diff_after": round(diff_after, 3),
        "diff_ratio_after": round(diff_after / max(ref, 1e-6), 4),
        "favorite_side_after": _fav_side(home, away),
        "total_delta": round(total_out - total_in, 4),
        "total_preserved": abs(total_out - total_in) < 0.03,
        "corrected_home_xg": round(home, 3),
        "corrected_away_xg": round(away, 3),
        "corrected_total_xg": round(home + away, 3),
        "corrected_xg_diff": round(diff_after, 3),
        "corrected_favorite_side": _fav_side(home, away),
        "favorite_share_before": round(share_before, 4),
        "favorite_share_after": round(_fav_share(home, away), 4),
    }


def no_hybrid_balance_params() -> HybridBalanceParams:
    return HybridBalanceParams(name="hybrid_balance_noop", enabled=False)


def prev_best_h2_params() -> TrustGatedSpreadHybridParams:
    return TrustGatedSpreadHybridParams(
        name=PREV_BEST_H2_NAME,
        correction_family="h2_overcommit",
        overcommit_margin=0.05,
        overcommit_damping_weight_low=0.40,
        overcommit_damping_weight_medium=0.20,
        max_overcommit_delta=0.10,
    )


def p174_recovery_params():
    return p174_best_spread_share_recovery_params()


def best_hb3_reference_params() -> HybridBalanceParams:
    """Best shadow candidate from P1.7B.6.3."""
    return HybridBalanceParams(
        name="HB3_tl0.4_th0.6_ml0",
        correction_family="hb3",
        trust_low_threshold=0.40,
        trust_high_threshold=0.60,
        medium_bucket_uses_low_damping=True,
        low_or_medium_overcommit_guard=False,
        overcommit_margin=0.05,
        overcommit_damping_weight_low=0.40,
        additional_spra_medium_weight=0.10,
        low_trust_damping_weight=0.20,
        max_total_spread_delta=0.10,
    )


def spra_reference_params():
    return prev_light_damping_params()


def _add_variant(
    out: list[HybridBalanceParams],
    seen: set[tuple],
    *,
    max_variants: int,
    **kwargs,
) -> bool:
    if len(out) >= max_variants:
        return False
    p = HybridBalanceParams(**kwargs)
    key = p.correction_key()
    if key in seen:
        return True
    seen.add(key)
    out.append(p)
    return len(out) < max_variants


def build_hybrid_balance_grid(*, max_variants: int = MAX_HYBRID_BALANCE_VARIANTS) -> list[HybridBalanceParams]:
    out: list[HybridBalanceParams] = [no_hybrid_balance_params()]
    seen: set[tuple] = {no_hybrid_balance_params().correction_key()}

    def add(**kw) -> bool:
        return _add_variant(out, seen, max_variants=max_variants, **kw)

    # HB1 — H2 base + additional SprA damping
    hb1_rows = [
        (0.05, 0.40, 0.10, 0.10, 0.05, 0.00, 0.08),
        (0.05, 0.40, 0.10, 0.15, 0.10, 0.03, 0.10),
        (0.05, 0.45, 0.10, 0.10, 0.10, 0.03, 0.10),
        (0.08, 0.40, 0.12, 0.15, 0.10, 0.03, 0.10),
        (0.03, 0.35, 0.08, 0.20, 0.15, 0.05, 0.12),
        (0.05, 0.50, 0.12, 0.10, 0.15, 0.03, 0.12),
    ]
    for margin, lw, md, al, am, ah, tmax in hb1_rows:
        if not add(
            name=f"HB1_m{margin}_lw{lw}_al{al}_t{tmax}",
            correction_family="hb1",
            correction_order="h3_h2_h1_h4",
            overcommit_margin=margin,
            overcommit_damping_weight_low=lw,
            max_overcommit_delta=md,
            additional_spra_low_weight=al,
            additional_spra_medium_weight=am,
            additional_spra_high_weight=ah,
            max_total_spread_delta=tmax,
            restore_enabled=False,
        ):
            return out

    # HB2 — wrong-favorite guard + stronger H1
    for lw, mw, hw, md, dgw, dmax, tmax in [
        (0.25, 0.15, 0.03, 0.10, 0.35, 0.10, 0.10),
        (0.30, 0.15, 0.03, 0.10, 0.35, 0.10, 0.12),
        (0.25, 0.20, 0.05, 0.12, 0.25, 0.08, 0.10),
        (0.35, 0.15, 0.00, 0.12, 0.45, 0.12, 0.12),
        (0.20, 0.10, 0.03, 0.08, 0.25, 0.08, 0.08),
    ]:
        if not add(
            name=f"HB2_lw{lw}_md{md}_t{tmax}",
            correction_family="hb2",
            correction_order="h3_h1_h2_h4",
            low_trust_damping_weight=lw,
            medium_trust_damping_weight=mw,
            high_trust_damping_weight=hw,
            max_damping_delta=md,
            disagreement_damping_weight=dgw,
            max_disagreement_delta=dmax,
            max_total_spread_delta=tmax,
            restore_enabled=False,
        ):
            return out

    # HB3 — bucket threshold tuning
    for tl, th, med_low, lom in product(
        (0.40, 0.45, 0.50),
        (0.60, 0.65, 0.70),
        (False, True),
        (False, True),
    ):
        if not add(
            name=f"HB3_tl{tl}_th{th}_ml{int(med_low)}",
            correction_family="hb3",
            trust_low_threshold=tl,
            trust_high_threshold=th,
            medium_bucket_uses_low_damping=med_low,
            low_or_medium_overcommit_guard=lom,
            overcommit_margin=0.05,
            overcommit_damping_weight_low=0.40,
            additional_spra_medium_weight=0.10,
            low_trust_damping_weight=0.20,
            max_total_spread_delta=0.10,
        ):
            return out

    # HB4 — order + cap tuning
    for order, tmax, restore in product(
        ("h3_h2_h1_h4", "h2_h3_h1_h4", "h3_h1_h2_h4"),
        (0.08, 0.10, 0.12, 0.15),
        (False, True),
    ):
        if not add(
            name=f"HB4_{order}_t{tmax}_r{int(restore)}",
            correction_family="hb4",
            correction_order=order,
            max_total_spread_delta=tmax,
            restore_enabled=restore,
            restore_weight=0.05 if restore else 0.0,
            overcommit_margin=0.05,
            overcommit_damping_weight_low=0.40,
            low_trust_damping_weight=0.20,
            medium_trust_damping_weight=0.10,
            additional_spra_medium_weight=0.10,
        ):
            return out

    # HB5 — no restore strict damping
    for lw, mw, tmax in product(
        (0.20, 0.25, 0.30),
        (0.10, 0.15),
        (0.08, 0.10, 0.12),
    ):
        if not add(
            name=f"HB5_lw{lw}_mw{mw}_t{tmax}",
            correction_family="hb5",
            correction_order="h3_h2_h1_h4",
            restore_enabled=False,
            low_trust_damping_weight=lw,
            medium_trust_damping_weight=mw,
            overcommit_margin=0.05,
            overcommit_damping_weight_low=0.40,
            additional_spra_low_weight=0.10,
            additional_spra_medium_weight=0.10,
            max_damping_delta=0.10,
            max_total_spread_delta=tmax,
        ):
            return out

    return out[:max_variants]


def portability_probe() -> dict[str, Any]:
    p = HybridBalanceParams(
        name="probe",
        correction_family="hb1",
        overcommit_margin=0.05,
        overcommit_damping_weight_low=0.40,
        additional_spra_low_weight=0.15,
        max_total_spread_delta=0.10,
    )
    _, _, diag = apply_hybrid_balance_correction(
        1.6, 0.4,
        p1c2_home=1.5, p1c2_away=0.5,
        baseline_home=1.2, baseline_away=0.8,
        stage=None,
        params=p,
    )
    return {
        "stage_required": False,
        "no_stage_rows_supported": True,
        "correction_applies_without_stage": diag.get("stage_required") is False,
        "probe_correction_applied": diag.get("correction_applied"),
    }


def diagnose_contribution_ll_gap(
    rows: list[dict[str, Any]],
    *,
    label: str = "candidate",
) -> dict[str, Any]:
    """Explain why failure-category gains may not move WC2018 LL."""
    wc = [r for r in rows if r.get("dataset") == "wc2018"]
    improved = harmed = 0
    pos_sum = neg_sum = 0.0
    for r in wc:
        d = float(r.get("ll_delta", 0))
        if d < -0.001:
            improved += 1
            pos_sum += -d
        elif d > 0.001:
            harmed += 1
            neg_sum += d
    reasons = [
        {
            "reason": "spread_too_large matches under-damped (medium/high trust)",
            "affected_match_count": sum(1 for r in wc if r.get("trust_bucket") in ("medium", "high")),
            "ll_contribution": round(neg_sum, 4),
            "suggested_fix": "HB3 lower high threshold or medium-as-low damping",
        },
        {
            "reason": "max_total_spread_delta cap limits correction",
            "affected_match_count": sum(1 for r in wc if (r.get("cap_applied") or r.get("hybrid_cap"))),
            "ll_contribution": None,
            "suggested_fix": "HB4 raise cap to 0.12–0.15",
        },
        {
            "reason": "H2-only path improves wrong_favorite not spread magnitude",
            "affected_match_count": improved,
            "ll_contribution": round(pos_sum, 4),
            "suggested_fix": "HB1 stack H2 + SprA damping",
        },
        {
            "reason": "improvements on low-impact matches",
            "affected_match_count": improved,
            "ll_contribution": round(pos_sum - neg_sum, 4),
            "suggested_fix": "target high-spread low-trust segments",
        },
    ]
    return {
        "label": label,
        "wc2018_match_count": len(wc),
        "matches_improved": improved,
        "matches_harmed": harmed,
        "positive_ll_delta_sum": round(pos_sum, 4),
        "negative_ll_delta_sum": round(neg_sum, 4),
        "net_ll_delta": round(pos_sum - neg_sum, 4) if wc else 0,
        "diagnostic_table": reasons,
    }
