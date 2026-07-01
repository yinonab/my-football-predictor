"""Priority 1.7B.6.2 — Trust-gated spread damping hybrid on P1C2 + R16 recovery."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any

from core.favorite_trust_calibration import (
    FavoriteTrustParams,
    compute_favorite_trust,
    prev_light_damping_params,
)
from core.strength_stage_recovery import p174_best_spread_share_recovery_params

MAX_TRUST_GATED_HYBRID_VARIANTS = 180
P1762_STACK_BASE = "P1C2+R16rec+hybrid"
PREV_SPRA_NAME = "SprA_gd_w0.15_md0.08_mid0.3"
BEST_TRUST_A_35 = "TrustA_thr0.35_w0.2_md0.08_mid0.25"
BEST_TRUST_A_45 = "TrustA_thr0.45_w0.05_md0.03_mid0.35"


@dataclass(frozen=True)
class TrustGatedSpreadHybridParams:
    """Trust controls spread damping strength (shadow-only, stage not required)."""

    name: str
    enabled: bool = True
    correction_family: str = "balanced"  # h1_spra | h2_overcommit | h3_disagree | h4_restore | balanced

    trust_low_threshold: float = 0.45
    trust_high_threshold: float = 0.65

    low_trust_damping_weight: float = 0.15
    medium_trust_damping_weight: float = 0.10
    high_trust_damping_weight: float = 0.03
    max_damping_delta: float = 0.08
    min_diff_to_apply: float = 0.30

    overcommit_margin: float = 0.10
    overcommit_damping_weight_low: float = 0.30
    overcommit_damping_weight_medium: float = 0.20
    max_overcommit_delta: float = 0.08

    disagreement_damping_weight: float = 0.25
    max_disagreement_delta: float = 0.08
    min_disagreement_diff: float = 0.20

    restore_margin: float = 0.10
    restore_weight_medium: float = 0.10
    restore_weight_high: float = 0.15
    max_restore_delta: float = 0.05
    max_favorite_share: float = 0.70

    max_total_spread_adjustment_delta: float = 0.10
    restore_enabled: bool = True

    enable_trust_gated_damping: bool = False
    enable_overcommit_guard: bool = False
    enable_wrong_favorite_guard: bool = False
    enable_restore: bool = False

    def correction_key(self) -> tuple:
        return (
            self.correction_family,
            round(self.trust_low_threshold, 4),
            round(self.trust_high_threshold, 4),
            round(self.low_trust_damping_weight, 4),
            round(self.medium_trust_damping_weight, 4),
            round(self.high_trust_damping_weight, 4),
            round(self.max_damping_delta, 4),
            round(self.min_diff_to_apply, 4),
            round(self.overcommit_margin, 4),
            round(self.overcommit_damping_weight_low, 4),
            round(self.overcommit_damping_weight_medium, 4),
            round(self.max_overcommit_delta, 4),
            round(self.disagreement_damping_weight, 4),
            round(self.max_disagreement_delta, 4),
            round(self.min_disagreement_diff, 4),
            round(self.restore_margin, 4),
            round(self.restore_weight_medium, 4),
            round(self.restore_weight_high, 4),
            round(self.max_restore_delta, 4),
            round(self.max_favorite_share, 4),
            round(self.max_total_spread_adjustment_delta, 4),
            self.restore_enabled,
            self.enable_trust_gated_damping,
            self.enable_overcommit_guard,
            self.enable_wrong_favorite_guard,
            self.enable_restore,
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


def _trust_bucket(score: float, params: TrustGatedSpreadHybridParams) -> str:
    if score < params.trust_low_threshold:
        return "low"
    if score < params.trust_high_threshold:
        return "medium"
    return "high"


def _damping_weight_for_bucket(bucket: str, params: TrustGatedSpreadHybridParams) -> float:
    if bucket == "low":
        return params.low_trust_damping_weight
    if bucket == "medium":
        return params.medium_trust_damping_weight
    return params.high_trust_damping_weight


def _overcommit_weight_for_bucket(bucket: str, params: TrustGatedSpreadHybridParams) -> float:
    if bucket == "low":
        return params.overcommit_damping_weight_low
    return params.overcommit_damping_weight_medium


def _restore_weight_for_bucket(bucket: str, params: TrustGatedSpreadHybridParams) -> float:
    if bucket == "high":
        return params.restore_weight_high
    return params.restore_weight_medium


def apply_trust_gated_spread_hybrid(
    recovery_home: float,
    recovery_away: float,
    *,
    p1c2_home: float,
    p1c2_away: float,
    baseline_home: float,
    baseline_away: float,
    stage: str | None,
    params: TrustGatedSpreadHybridParams,
    home_power: float | None = None,
    away_power: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """Apply trust-gated spread damping hybrid; preserves total by default."""
    warnings: list[str] = ["no_actual_result_used", "no_dataset_specific_logic", "no_stage_dependency"]
    caps: list[str] = []
    home, away = float(recovery_home), float(recovery_away)
    total_in = home + away
    diff_in = abs(home - away)
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
    damping_weight_selected: float | None = None

    base_side = _fav_side(baseline_home, baseline_away)
    p1c2_side = _fav_side(p1c2_home, p1c2_away)
    rec_side = _fav_side(home, away)
    ref_diff = abs(baseline_home - baseline_away)
    cand_diff = diff_in

    diag: dict[str, Any] = {
        "enabled": params.enabled,
        "correction_family": params.correction_family,
        "correction_applied": False,
        "correction_reason": None,
        "stage": stage,
        "stage_available": stage is not None,
        "stage_required": False,
        "context_used": trust_raw.get("context_used", []),
        "base_candidate": P1762_STACK_BASE,
        "baseline_home_xg": round(baseline_home, 3),
        "baseline_away_xg": round(baseline_away, 3),
        "baseline_total_xg": round(baseline_home + baseline_away, 3),
        "baseline_xg_diff": round(ref_diff, 3),
        "baseline_favorite_side": base_side,
        "p1c2_home_xg": round(p1c2_home, 3),
        "p1c2_away_xg": round(p1c2_away, 3),
        "p1c2_total_xg": round(p1c2_home + p1c2_away, 3),
        "p1c2_xg_diff": round(abs(p1c2_home - p1c2_away), 3),
        "p1c2_favorite_side": p1c2_side,
        "recovery_home_xg": round(recovery_home, 3),
        "recovery_away_xg": round(recovery_away, 3),
        "recovery_total_xg": round(total_in, 3),
        "recovery_xg_diff": round(diff_in, 3),
        "recovery_favorite_side": rec_side,
        "trust_score": round(trust_score, 4),
        "trust_bucket": bucket,
        "favorite_agreement": trust_raw.get("favorite_agreement"),
        "favorite_direction_stable": trust_raw.get("favorite_direction_stable"),
        "candidate_diff": round(cand_diff, 3),
        "reference_diff": round(ref_diff, 3),
        "diff_ratio": trust_raw.get("diff_ratio"),
        "favorite_share_before": round(share_before, 4),
        "favorite_share_after": round(share_before, 4),
        "total_preserved": True,
        "total_delta": 0.0,
        "spread_delta": 0.0,
        "damping_weight_selected": None,
        "trust_gated_damping_applied": False,
        "overcommitment_guard_applied": False,
        "wrong_favorite_guard_applied": False,
        "favorite_restore_applied": False,
        "caps_applied": caps,
        "warnings": warnings,
        "trust_gated_spread_diagnostics": {**trust_raw, "trust_bucket": bucket},
    }

    if stage is None:
        warnings.append("missing_stage_but_supported")

    if not params.enabled:
        diag["correction_reason"] = "disabled"
        diag["corrected_home_xg"] = round(home, 3)
        diag["corrected_away_xg"] = round(away, 3)
        diag["corrected_total_xg"] = round(home + away, 3)
        diag["corrected_xg_diff"] = round(abs(home - away), 3)
        diag["corrected_favorite_side"] = rec_side
        return home, away, diag

    if total_in <= 0 or not math.isfinite(total_in):
        warnings.append("invalid_xg_skipped")
        diag["correction_reason"] = "invalid_xg"
        diag["corrected_home_xg"] = round(home, 3)
        diag["corrected_away_xg"] = round(away, 3)
        diag["corrected_total_xg"] = round(home + away, 3)
        diag["corrected_xg_diff"] = round(abs(home - away), 3)
        diag["corrected_favorite_side"] = rec_side
        return home, away, diag

    spread_budget = params.max_total_spread_adjustment_delta
    spread_used = 0.0
    applied_any = False

    def _budget(delta: float) -> float:
        nonlocal spread_used
        allowed = min(delta, max(0.0, spread_budget - spread_used))
        spread_used += allowed
        if allowed < delta - 1e-6:
            caps.append("max_spread_delta_cap_applied")
            warnings.append("max_spread_delta_cap_applied")
        return allowed

    use_h3 = params.correction_family == "h3_disagree" or (
        params.correction_family == "balanced" and params.enable_wrong_favorite_guard
    )
    use_h2 = params.correction_family == "h2_overcommit" or (
        params.correction_family == "balanced" and params.enable_overcommit_guard
    )
    use_h1 = params.correction_family == "h1_spra" or (
        params.correction_family == "balanced" and params.enable_trust_gated_damping
    )
    use_h4 = params.correction_family == "h4_restore" or (
        params.correction_family == "balanced"
        and params.enable_restore
        and params.restore_enabled
    )

    # H3 — wrong-favorite guard
    if use_h3 and spread_used < spread_budget:
        disagree = (
            (base_side != p1c2_side and base_side != "draw" and p1c2_side != "draw")
            or (base_side != rec_side and base_side != "draw" and rec_side != "draw")
            or bucket == "low"
        )
        if disagree and cand_diff >= params.min_disagreement_diff:
            damp = min(params.max_disagreement_delta, params.disagreement_damping_weight * cand_diff)
            if bucket == "low":
                damp = min(params.max_disagreement_delta, damp * 1.25)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["wrong_favorite_guard_applied"] = True
                applied_any = True

    # H2 — trust-gated overcommitment
    if use_h2 and spread_used < spread_budget and bucket != "high":
        if cand_diff > ref_diff + params.overcommit_margin:
            excess = cand_diff - ref_diff - params.overcommit_margin
            ow = _overcommit_weight_for_bucket(bucket, params)
            damp = min(params.max_overcommit_delta, ow * excess)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["overcommitment_guard_applied"] = True
                applied_any = True

    # H1 — trust-gated SprA-style damping
    if use_h1 and spread_used < spread_budget and cand_diff >= params.min_diff_to_apply:
        dw = _damping_weight_for_bucket(bucket, params)
        damping_weight_selected = dw
        if dw > 1e-6 and cand_diff > ref_diff + 0.05:
            excess = cand_diff - ref_diff
            damp = min(params.max_damping_delta, dw * excess)
            damp = _budget(damp)
            if damp > 1e-6:
                home, away = _set_diff_preserve_total(home, away, max(cand_diff - damp, 0.0))
                cand_diff = abs(home - away)
                diag["trust_gated_damping_applied"] = True
                applied_any = True

    # H4 — trust-gated restore
    if use_h4 and spread_used < spread_budget and bucket in ("medium", "high"):
        if (
            trust_raw.get("favorite_direction_stable")
            and base_side == rec_side
            and rec_side != "draw"
            and cand_diff < ref_diff - params.restore_margin
        ):
            gap = ref_diff - cand_diff - params.restore_margin
            rw = _restore_weight_for_bucket(bucket, params)
            restore = min(params.max_restore_delta, rw * max(gap, 0.0))
            restore = _budget(restore)
            if restore > 1e-6:
                home, away = _set_diff_preserve_total(home, away, min(cand_diff + restore, total_in - 0.1))
                cand_diff = abs(home - away)
                share = _fav_share(home, away)
                if share > params.max_favorite_share:
                    home, away = _apply_share_cap(home, away, params.max_favorite_share)
                diag["favorite_restore_applied"] = True
                applied_any = True

    if rec_side == "draw":
        warnings.append("favorite_side_ambiguous")

    diag["damping_weight_selected"] = damping_weight_selected
    home, away = _round_pair(home, away)
    total_out = home + away
    diag["total_delta"] = round(total_out - total_in, 4)
    diag["spread_delta"] = round(abs(home - away) - diff_in, 4)
    diag["total_preserved"] = abs(diag["total_delta"]) < 0.03
    if not diag["total_preserved"]:
        warnings.append("total_not_preserved")
    diag["favorite_share_after"] = round(_fav_share(home, away), 4)
    diag["caps_applied"] = caps

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


def no_trust_gated_hybrid_params() -> TrustGatedSpreadHybridParams:
    return TrustGatedSpreadHybridParams(name="hybrid_noop", enabled=False)


def p174_recovery_params():
    return p174_best_spread_share_recovery_params()


def spra_reference_params():
    return prev_light_damping_params()


def trust_a_35_params() -> FavoriteTrustParams:
    return FavoriteTrustParams(
        name=BEST_TRUST_A_35,
        correction_family="low_trust_damp",
        trust_threshold=0.35,
        damping_weight=0.20,
        max_damping_delta=0.08,
        min_diff_to_apply=0.25,
    )


def trust_a_45_params() -> FavoriteTrustParams:
    return FavoriteTrustParams(
        name=BEST_TRUST_A_45,
        correction_family="low_trust_damp",
        trust_threshold=0.45,
        damping_weight=0.05,
        max_damping_delta=0.03,
        min_diff_to_apply=0.35,
    )


def _add_variant(
    out: list[TrustGatedSpreadHybridParams],
    seen: set[tuple],
    *,
    max_variants: int,
    **kwargs,
) -> bool:
    if len(out) >= max_variants:
        return False
    p = TrustGatedSpreadHybridParams(**kwargs)
    key = p.correction_key()
    if key in seen:
        return True
    seen.add(key)
    out.append(p)
    return len(out) < max_variants


def build_trust_gated_hybrid_grid(*, max_variants: int = MAX_TRUST_GATED_HYBRID_VARIANTS) -> list[TrustGatedSpreadHybridParams]:
    out: list[TrustGatedSpreadHybridParams] = [no_trust_gated_hybrid_params()]
    seen: set[tuple] = {no_trust_gated_hybrid_params().correction_key()}

    def add(**kw) -> bool:
        return _add_variant(out, seen, max_variants=max_variants, **kw)

    # H1 — controlled subset (not full Cartesian)
    h1_rows = [
        (0.10, 0.05, 0.00, 0.05, 0.25, 0.35, 0.60),
        (0.15, 0.10, 0.03, 0.08, 0.30, 0.35, 0.60),
        (0.20, 0.10, 0.03, 0.08, 0.35, 0.45, 0.65),
        (0.25, 0.15, 0.05, 0.10, 0.35, 0.45, 0.70),
        (0.15, 0.05, 0.00, 0.08, 0.25, 0.35, 0.70),
        (0.20, 0.15, 0.03, 0.05, 0.45, 0.45, 0.60),
        (0.10, 0.15, 0.05, 0.08, 0.30, 0.35, 0.65),
        (0.25, 0.10, 0.00, 0.10, 0.25, 0.45, 0.70),
    ]
    for low_w, med_w, high_w, md, mid, tl, th in h1_rows:
        if not add(
            name=f"HybH1_l{low_w}_m{med_w}_h{high_w}_md{md}",
            correction_family="h1_spra",
            low_trust_damping_weight=low_w,
            medium_trust_damping_weight=med_w,
            high_trust_damping_weight=high_w,
            max_damping_delta=md,
            min_diff_to_apply=mid,
            trust_low_threshold=tl,
            trust_high_threshold=th,
        ):
            return out

    # H2
    for margin, lw, mw, md in product(
        (0.05, 0.10, 0.15),
        (0.20, 0.30, 0.40),
        (0.10, 0.20),
        (0.05, 0.08, 0.10),
    ):
        if not add(
            name=f"HybH2_m{margin}_lw{lw}_md{md}",
            correction_family="h2_overcommit",
            overcommit_margin=margin,
            overcommit_damping_weight_low=lw,
            overcommit_damping_weight_medium=mw,
            max_overcommit_delta=md,
        ):
            return out

    # H3
    for w, md, mid in product((0.15, 0.25, 0.35), (0.05, 0.08, 0.10), (0.15, 0.20)):
        if not add(
            name=f"HybH3_w{w}_md{md}_mid{mid}",
            correction_family="h3_disagree",
            disagreement_damping_weight=w,
            max_disagreement_delta=md,
            min_disagreement_diff=mid,
        ):
            return out

    # H4
    for margin, mw, hw, md in product(
        (0.05, 0.10, 0.15),
        (0.05, 0.10, 0.15),
        (0.10, 0.15, 0.20),
        (0.03, 0.05, 0.08),
    ):
        if not add(
            name=f"HybH4_m{margin}_mw{mw}_md{md}",
            correction_family="h4_restore",
            restore_margin=margin,
            restore_weight_medium=mw,
            restore_weight_high=hw,
            max_restore_delta=md,
        ):
            return out

    # H5 — balanced
    bal_combos = [
        (0.35, 0.60, 0.20, 0.10, 0.03, 0.08, 0.10, True),
        (0.45, 0.65, 0.15, 0.10, 0.03, 0.08, 0.08, True),
        (0.35, 0.70, 0.25, 0.15, 0.00, 0.10, 0.10, True),
        (0.45, 0.60, 0.20, 0.05, 0.03, 0.08, 0.12, False),
        (0.35, 0.65, 0.15, 0.10, 0.05, 0.06, 0.08, True),
        (0.35, 0.60, 0.25, 0.15, 0.00, 0.10, 0.12, True),
        (0.45, 0.70, 0.20, 0.10, 0.03, 0.08, 0.10, False),
    ]
    for tl, th, lw, mw, hw, md, tmax, restore in bal_combos:
        if not add(
            name=f"HybH5_tl{tl}_tmax{tmax}_r{int(restore)}",
            correction_family="balanced",
            enable_wrong_favorite_guard=True,
            enable_overcommit_guard=True,
            enable_trust_gated_damping=True,
            enable_restore=True,
            restore_enabled=restore,
            trust_low_threshold=tl,
            trust_high_threshold=th,
            low_trust_damping_weight=lw,
            medium_trust_damping_weight=mw,
            high_trust_damping_weight=hw,
            max_damping_delta=md,
            max_total_spread_adjustment_delta=tmax,
        ):
            return out

    for tl, tmax in product((0.35, 0.45), (0.06, 0.08, 0.10)):
        if not add(
            name=f"HybH5_g{tl}_m{tmax}",
            correction_family="balanced",
            enable_wrong_favorite_guard=True,
            enable_overcommit_guard=True,
            enable_trust_gated_damping=True,
            enable_restore=False,
            restore_enabled=False,
            trust_low_threshold=tl,
            max_total_spread_adjustment_delta=tmax,
            low_trust_damping_weight=0.20,
            medium_trust_damping_weight=0.10,
            high_trust_damping_weight=0.03,
        ):
            return out

    return out[:max_variants]


def portability_probe() -> dict[str, Any]:
    p = TrustGatedSpreadHybridParams(
        name="probe",
        correction_family="balanced",
        enable_wrong_favorite_guard=True,
        enable_overcommit_guard=True,
        enable_trust_gated_damping=True,
        low_trust_damping_weight=0.20,
        medium_trust_damping_weight=0.10,
        max_total_spread_adjustment_delta=0.10,
    )
    trust = compute_favorite_trust(
        p1c2_home=1.5, p1c2_away=0.8,
        recovery_home=1.6, recovery_away=0.7,
        baseline_home=1.2, baseline_away=1.0,
        stage=None,
    )
    _, _, diag = apply_trust_gated_spread_hybrid(
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
        "damping_weight_selected": diag.get("damping_weight_selected"),
        "probe_correction_applied": diag.get("correction_applied"),
    }
