"""Priority 1.7B.4 — Generalized R16/knockout stage recovery on P1C2 shadow candidate."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any

from core.strength_based_xg_generator import p1c2_shadow_params

MAX_RECOVERY_VARIANTS = 150
MAX_TOTAL_RECOVERY_FOCUS_VARIANTS = 160
KNOCKOUT_STAGES = frozenset({"r16", "qf", "sf", "final", "3rd"})
P1C2_BASE_NAME = "P1C2_fav_b0.06_st0.58_mx0.68"
P174_BEST_RECOVERY_NAME = "R16rec_r16_only_tw0.0_mtd0.2_sw0.15_msd0.05_fw0.5_mx0.7"


@dataclass(frozen=True)
class StageRecoveryParams:
    """Stage-aware recovery layered on P1C2 xG (shadow-only, never production default)."""

    name: str
    enabled: bool = True
    stage_scope: str = "r16_only"  # r16_only | knockout_all
    total_recovery_weight: float = 0.0
    max_total_recovery_delta: float = 0.20
    spread_recovery_weight: float = 0.0
    max_spread_recovery_delta: float = 0.10
    favorite_share_recovery_weight: float = 0.0
    max_favorite_share: float = 0.70
    min_underdog_share: float = 0.30

    def recovery_key(self) -> tuple:
        return (
            self.stage_scope,
            round(self.total_recovery_weight, 4),
            round(self.max_total_recovery_delta, 4),
            round(self.spread_recovery_weight, 4),
            round(self.max_spread_recovery_delta, 4),
            round(self.favorite_share_recovery_weight, 4),
            round(self.max_favorite_share, 4),
            round(self.min_underdog_share, 4),
        )


def stage_recovery_applies(stage: str | None, params: StageRecoveryParams) -> bool:
    if not params.enabled or stage is None:
        return False
    if params.stage_scope == "r16_only":
        return stage == "r16"
    if params.stage_scope == "knockout_all":
        return stage in KNOCKOUT_STAGES or (stage != "group" and stage is not None)
    return False


def _round_pair(h: float, a: float) -> tuple[float, float]:
    return round(h, 2), round(a, 2)


def apply_stage_recovery(
    p1c2_home: float,
    p1c2_away: float,
    ref_home: float,
    ref_away: float,
    stage: str | None,
    params: StageRecoveryParams,
) -> tuple[float, float, dict[str, Any]]:
    """Apply bounded total/spread/share recovery toward baseline reference xG."""
    warnings: list[str] = []
    caps: list[str] = []
    home, away = float(p1c2_home), float(p1c2_away)
    p1c2_total = home + away
    p1c2_diff = abs(home - away)
    fav_share_before = max(home, away) / p1c2_total if p1c2_total > 0 else 0.5

    diag: dict[str, Any] = {
        "enabled": params.enabled,
        "stage_scope": params.stage_scope,
        "match_stage": stage,
        "recovery_applied": False,
        "recovery_reason": None,
        "base_candidate": P1C2_BASE_NAME,
        "baseline_reference_home_xg": round(ref_home, 3),
        "baseline_reference_away_xg": round(ref_away, 3),
        "baseline_reference_total_xg": round(ref_home + ref_away, 3),
        "p1c2_home_xg": round(p1c2_home, 3),
        "p1c2_away_xg": round(p1c2_away, 3),
        "p1c2_total_xg": round(p1c2_total, 3),
        "p1c2_xg_diff": round(p1c2_diff, 3),
        "total_recovery_weight": params.total_recovery_weight,
        "max_total_recovery_delta": params.max_total_recovery_delta,
        "total_recovery_delta_raw": 0.0,
        "total_recovery_delta_applied": 0.0,
        "total_recovery_delta": 0.0,
        "total_recovery_cap_applied": False,
        "spread_recovery_weight": params.spread_recovery_weight,
        "max_spread_recovery_delta": params.max_spread_recovery_delta,
        "spread_recovery_delta_applied": 0.0,
        "spread_recovery_delta": 0.0,
        "favorite_share_recovery_weight": params.favorite_share_recovery_weight,
        "favorite_share_before": round(fav_share_before, 4),
        "favorite_share_after": round(fav_share_before, 4),
        "max_favorite_share": params.max_favorite_share,
        "total_preserved_for_share_recovery": True,
        "caps_applied": caps,
        "warnings": warnings,
        "uses_global_xg_avg": False,
        "uses_fixed_2_6": False,
    }

    if not params.enabled:
        diag["recovery_reason"] = "disabled"
        diag["recovered_home_xg"] = round(home, 3)
        diag["recovered_away_xg"] = round(away, 3)
        diag["recovered_total_xg"] = round(home + away, 3)
        diag["recovered_xg_diff"] = round(abs(home - away), 3)
        return home, away, diag

    if stage is None:
        warnings.append("missing_stage_no_recovery")
        diag["recovery_reason"] = "missing_stage"
        diag["recovered_home_xg"] = round(home, 3)
        diag["recovered_away_xg"] = round(away, 3)
        diag["recovered_total_xg"] = round(home + away, 3)
        diag["recovered_xg_diff"] = round(abs(home - away), 3)
        return home, away, diag

    if not stage_recovery_applies(stage, params):
        warnings.append("no_recovery_needed")
        diag["recovery_reason"] = "stage_out_of_scope"
        diag["recovered_home_xg"] = round(home, 3)
        diag["recovered_away_xg"] = round(away, 3)
        diag["recovered_total_xg"] = round(home + away, 3)
        diag["recovered_xg_diff"] = round(abs(home - away), 3)
        return home, away, diag

    if p1c2_total <= 0 or not math.isfinite(p1c2_total):
        warnings.append("skipped_due_to_invalid_xg")
        diag["recovery_reason"] = "invalid_p1c2_xg"
        diag["recovered_home_xg"] = round(home, 3)
        diag["recovered_away_xg"] = round(away, 3)
        diag["recovered_total_xg"] = round(home + away, 3)
        diag["recovered_xg_diff"] = round(abs(home - away), 3)
        return home, away, diag

    ref_total = ref_home + ref_away
    ref_diff = abs(ref_home - ref_away)
    applied_any = False

    # A. Total recovery — proportional scale, capped
    total_gap = max(0.0, ref_total - p1c2_total)
    if params.total_recovery_weight > 0:
        if total_gap <= 1e-6:
            warnings.append("reference_total_not_higher")
            warnings.append("no_total_recovery_needed")
        else:
            raw_delta = params.total_recovery_weight * total_gap
            total_delta = min(raw_delta, params.max_total_recovery_delta)
            diag["total_recovery_delta_raw"] = round(raw_delta, 4)
            if total_delta > 1e-6:
                factor = (p1c2_total + total_delta) / p1c2_total
                home *= factor
                away *= factor
                diag["total_recovery_delta_applied"] = round(total_delta, 4)
                diag["total_recovery_delta"] = round(total_delta, 4)
                applied_any = True
                if raw_delta > params.max_total_recovery_delta + 1e-6:
                    caps.append("total_cap_applied")
                    warnings.append("total_cap_applied")
                    diag["total_recovery_cap_applied"] = True
                if total_delta > 0.35:
                    warnings.append("total_recovery_too_large")
            else:
                warnings.append("no_total_recovery_needed")

    total_now = home + away

    # B. Spread recovery — favorite up, underdog down, preserve total
    cand_diff = abs(home - away)
    spread_gap = max(0.0, ref_diff - cand_diff)
    if params.spread_recovery_weight > 0 and spread_gap > 1e-6 and total_now > 0:
        raw_spread = params.spread_recovery_weight * spread_gap
        spread_delta = min(raw_spread, params.max_spread_recovery_delta)
        if spread_delta > 1e-6:
            if home >= away:
                home += spread_delta / 2.0
                away -= spread_delta / 2.0
            elif away > home:
                away += spread_delta / 2.0
                home -= spread_delta / 2.0
            else:
                warnings.append("favorite_side_ambiguous")
            away = max(away, 0.05)
            home = max(home, 0.05)
            # re-normalize to preserve total
            cur = home + away
            if cur > 0:
                home = total_now * home / cur
                away = total_now * away / cur
            diag["spread_recovery_delta_applied"] = round(spread_delta, 4)
            diag["spread_recovery_delta"] = round(spread_delta, 4)
            applied_any = True
            if raw_spread > params.max_spread_recovery_delta:
                caps.append("spread_cap_applied")
                warnings.append("spread_cap_applied")

    # C. Favorite-share recovery — preserve total
    total_now = home + away
    if total_now > 0 and params.favorite_share_recovery_weight > 0:
        ref_share = max(ref_home, ref_away) / max(ref_total, 1e-9)
        cur_share = max(home, away) / total_now
        share_gap = max(0.0, ref_share - cur_share)
        if share_gap > 1e-6:
            max_fav = min(params.max_favorite_share, 1.0 - params.min_underdog_share)
            new_share = cur_share + params.favorite_share_recovery_weight * share_gap
            if new_share > max_fav:
                new_share = max_fav
                caps.append("favorite_share_cap_applied")
                warnings.append("favorite_share_cap_applied")
            if new_share > cur_share + 1e-6:
                if home >= away:
                    home = total_now * new_share
                    away = total_now * (1.0 - new_share)
                else:
                    away = total_now * new_share
                    home = total_now * (1.0 - new_share)
                diag["favorite_share_after"] = round(new_share, 4)
                diag["total_preserved_for_share_recovery"] = abs((home + away) - total_now) < 0.02
                applied_any = True

    home, away = _round_pair(home, away)
    if not applied_any:
        warnings.append("no_recovery_needed")
        diag["recovery_reason"] = "no_gap_to_recover"
    else:
        diag["recovery_applied"] = True
        diag["recovery_reason"] = "stage_recovery_applied"

    diag["favorite_share_after"] = round(
        max(home, away) / max(home + away, 1e-9), 4
    )
    diag["caps_applied"] = caps
    diag["recovered_home_xg"] = round(home, 3)
    diag["recovered_away_xg"] = round(away, 3)
    diag["recovered_total_xg"] = round(home + away, 3)
    diag["recovered_xg_diff"] = round(abs(home - away), 3)
    return home, away, diag


def p1c2_no_recovery_params() -> StageRecoveryParams:
    """P1C2 reference — recovery disabled."""
    return StageRecoveryParams(name=P1C2_BASE_NAME, enabled=False)


def p174_best_spread_share_recovery_params() -> StageRecoveryParams:
    """Best P1.7B.4 spread/share recovery — total_recovery_weight=0 reference."""
    return StageRecoveryParams(
        name=P174_BEST_RECOVERY_NAME,
        enabled=True,
        stage_scope="r16_only",
        total_recovery_weight=0.0,
        max_total_recovery_delta=0.20,
        spread_recovery_weight=0.15,
        max_spread_recovery_delta=0.05,
        favorite_share_recovery_weight=0.50,
        max_favorite_share=0.70,
    )


def _recovery_name(
    scope: str,
    tw: float,
    mtd: float,
    sw: float,
    msd: float,
    fw: float,
    mfs: float,
) -> str:
    return f"R16rec_{scope}_tw{tw}_mtd{mtd}_sw{sw}_msd{msd}_fw{fw}_mx{mfs}"


def _append_recovery(
    out: list[StageRecoveryParams],
    seen: set[tuple],
    *,
    scope: str,
    tw: float,
    mtd: float,
    sw: float,
    msd: float,
    fw: float,
    mfs: float,
    max_variants: int,
) -> bool:
    if len(out) >= max_variants:
        return False
    p = StageRecoveryParams(
        name=_recovery_name(scope, tw, mtd, sw, msd, fw, mfs),
        enabled=True,
        stage_scope=scope,
        total_recovery_weight=tw,
        max_total_recovery_delta=mtd,
        spread_recovery_weight=sw,
        max_spread_recovery_delta=msd,
        favorite_share_recovery_weight=fw,
        max_favorite_share=mfs,
    )
    key = p.recovery_key()
    if key in seen:
        return True
    seen.add(key)
    out.append(p)
    return len(out) < max_variants


def build_total_recovery_focus_grid(*, max_variants: int = MAX_TOTAL_RECOVERY_FOCUS_VARIANTS) -> list[StageRecoveryParams]:
    """P1.7B.4.1 — focused grid with mandatory total_recovery_weight > 0 for most candidates."""
    out: list[StageRecoveryParams] = [
        p1c2_no_recovery_params(),
        p174_best_spread_share_recovery_params(),
    ]
    seen: set[tuple] = {p.recovery_key() for p in out}

    def add(**kwargs) -> bool:
        return _append_recovery(out, seen, max_variants=max_variants, **kwargs)

    # Phase 4 — total-only (r16_only)
    for tw, mtd in product(
        (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40),
        (0.10, 0.15, 0.20, 0.25, 0.30, 0.35),
    ):
        if not add(scope="r16_only", tw=tw, mtd=mtd, sw=0.0, msd=0.10, fw=0.0, mfs=0.70):
            return out

    # Phase 5 — total + previous best spread/share
    for tw, mtd in product(
        (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40),
        (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35),
    ):
        if not add(
            scope="r16_only", tw=tw, mtd=mtd, sw=0.15, msd=0.05, fw=0.50, mfs=0.70,
        ):
            return out

    # Phase 6 — sensitivity around previous best (matched tw/mtd pairs, limited spread/share)
    for tw, mtd in ((0.10, 0.10), (0.20, 0.20), (0.30, 0.30)):
        for sw, msd in ((0.10, 0.05), (0.15, 0.05), (0.20, 0.10), (0.25, 0.05)):
            for fw, mfs in ((0.50, 0.70), (0.35, 0.68)):
                if not add(
                    scope="r16_only", tw=tw, mtd=mtd, sw=sw, msd=msd, fw=fw, mfs=mfs,
                ):
                    return out

    # Phase 7 — knockout_all control subset
    for tw, mtd in product((0.10, 0.20, 0.30), (0.10, 0.20)):
        if not add(
            scope="knockout_all", tw=tw, mtd=mtd, sw=0.15, msd=0.05, fw=0.50, mfs=0.70,
        ):
            return out

    return out


def build_recovery_grid(*, max_variants: int = MAX_RECOVERY_VARIANTS) -> list[StageRecoveryParams]:
    """Controlled recovery grid capped at max_variants (includes P1C2 no-recovery reference)."""
    scopes = ("r16_only", "knockout_all")
    total_weights = (0.0, 0.15, 0.25, 0.35, 0.50)
    max_total_deltas = (0.10, 0.20, 0.30, 0.40)
    spread_weights = (0.0, 0.15, 0.25, 0.35, 0.50)
    max_spread_deltas = (0.05, 0.10, 0.15, 0.20)
    share_weights = (0.0, 0.20, 0.35, 0.50)
    max_fav_shares = (0.68, 0.70, 0.72)

    out: list[StageRecoveryParams] = [p1c2_no_recovery_params()]
    seen: set[tuple] = {p1c2_no_recovery_params().recovery_key()}

    for scope, tw, mtd, sw, msd, fw, mfs in product(
        scopes, total_weights, max_total_deltas, spread_weights, max_spread_deltas,
        share_weights, max_fav_shares,
    ):
        if tw == 0 and sw == 0 and fw == 0:
            continue
        if tw == 0 and mtd != 0.20:
            continue
        if sw == 0 and msd != 0.10:
            continue
        if fw == 0 and mfs != 0.70:
            continue
        name = (
            f"R16rec_{scope}_tw{tw}_mtd{mtd}_sw{sw}_msd{msd}_fw{fw}_mx{mfs}"
        )
        p = StageRecoveryParams(
            name=name,
            enabled=True,
            stage_scope=scope,
            total_recovery_weight=tw,
            max_total_recovery_delta=mtd,
            spread_recovery_weight=sw,
            max_spread_recovery_delta=msd,
            favorite_share_recovery_weight=fw,
            max_favorite_share=mfs,
        )
        key = p.recovery_key()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= max_variants:
            return out
    return out


def source_uses_global_xg_avg_in_recovery() -> bool:
    import inspect

    src = inspect.getsource(apply_stage_recovery)
    return "GLOBAL_XG_AVG" in src or "config.GLOBAL" in src
