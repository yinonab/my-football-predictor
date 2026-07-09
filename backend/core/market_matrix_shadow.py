"""Shadow-only market matrix calibration (Phase 3B — not wired to predict)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW
from core.market_types import MarketConsensus, MarketQualityResult

ScoreMatrix = dict[str, float]

# Second-pass marginal nudge uses a fraction of requested blend toward market marginals.
MARGINAL_NUDGE_BLEND_FRACTION = 0.55
MIN_MOVEMENT_GAP_PCT = 0.5
WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT = 35.0


@dataclass
class MarketMatrixShadowResult:
    """Diagnostic shadow calibration result; does not alter production predict."""

    original_model_matrix: dict[str, float]
    shadow_calibrated_matrix: dict[str, float]
    matrix_delta_by_score: dict[str, float]
    implied_1x2_before: dict[str, float]
    implied_1x2_after: dict[str, float]
    implied_total_over_2_5_before: float
    implied_total_over_2_5_after: float
    implied_btts_before: float
    implied_btts_after: float
    implied_clean_sheet_before: dict[str, float]
    implied_clean_sheet_after: dict[str, float]
    top_scores_before: list[dict[str, float | str]]
    top_scores_after: list[dict[str, float | str]]
    requested_shadow_weight_pct: int
    effective_h2h_movement_pct: dict[str, float | None]
    effective_over_2_5_movement_pct: float | None
    effective_btts_movement_pct: float | None
    effective_favorite_side_movement_pct: float | None
    calibration_notes: list[str]
    warnings: list[str]

    @property
    def market_weight_used_for_shadow(self) -> int:
        """Backward-compatible alias for requested_shadow_weight_pct."""
        return self.requested_shadow_weight_pct

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_model_matrix": self.original_model_matrix,
            "shadow_calibrated_matrix": self.shadow_calibrated_matrix,
            "matrix_delta_by_score": self.matrix_delta_by_score,
            "implied_1x2_before": self.implied_1x2_before,
            "implied_1x2_after": self.implied_1x2_after,
            "implied_total_over_2_5_before": round(self.implied_total_over_2_5_before, 4),
            "implied_total_over_2_5_after": round(self.implied_total_over_2_5_after, 4),
            "implied_btts_before": round(self.implied_btts_before, 4),
            "implied_btts_after": round(self.implied_btts_after, 4),
            "implied_clean_sheet_before": self.implied_clean_sheet_before,
            "implied_clean_sheet_after": self.implied_clean_sheet_after,
            "top_scores_before": self.top_scores_before,
            "top_scores_after": self.top_scores_after,
            "requested_shadow_weight_pct": self.requested_shadow_weight_pct,
            "market_weight_used_for_shadow": self.requested_shadow_weight_pct,
            "effective_h2h_movement_pct": self.effective_h2h_movement_pct,
            "effective_over_2_5_movement_pct": self.effective_over_2_5_movement_pct,
            "effective_btts_movement_pct": self.effective_btts_movement_pct,
            "effective_favorite_side_movement_pct": self.effective_favorite_side_movement_pct,
            "calibration_notes": self.calibration_notes,
            "warnings": self.warnings,
        }


def shadow_market_weight(quality: MarketQualityResult) -> int:
    """Diagnostic-only requested market blend weight (matches Phase 3A band policy)."""
    if quality.band == BAND_RED:
        return 30
    if quality.band == BAND_YELLOW:
        return 40
    if quality.band == BAND_GREEN:
        if quality.bookmaker_count >= 6 and quality.total_line_count >= 10:
            return 60
        return 50
    return 30


def _parse_score(score: str) -> tuple[int, int] | None:
    if "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None


def _normalize_matrix(matrix: ScoreMatrix) -> dict[str, float]:
    total = sum(v for v in matrix.values() if v > 0)
    if total <= 0:
        return {k: 0.0 for k in matrix}
    return {k: round(v / total * 100.0, 6) for k, v in matrix.items() if v > 0}


def _implied_1x2(matrix: ScoreMatrix) -> dict[str, float]:
    home = draw = away = 0.0
    for score, prob in matrix.items():
        parsed = _parse_score(score)
        if parsed is None:
            continue
        h, a = parsed
        if h > a:
            home += prob
        elif h < a:
            away += prob
        else:
            draw += prob
    return {
        "home": round(home, 4),
        "draw": round(draw, 4),
        "away": round(away, 4),
    }


def _implied_over_2_5(matrix: ScoreMatrix) -> float:
    total = 0.0
    for score, prob in matrix.items():
        parsed = _parse_score(score)
        if parsed is None:
            continue
        if sum(parsed) >= 3:
            total += prob
    return round(total, 4)


def _implied_btts(matrix: ScoreMatrix) -> float:
    total = 0.0
    for score, prob in matrix.items():
        parsed = _parse_score(score)
        if parsed is None:
            continue
        h, a = parsed
        if h > 0 and a > 0:
            total += prob
    return round(total, 4)


def _implied_clean_sheet(matrix: ScoreMatrix) -> dict[str, float]:
    home_cs = away_cs = 0.0
    for score, prob in matrix.items():
        parsed = _parse_score(score)
        if parsed is None:
            continue
        h, a = parsed
        if a == 0 and h >= 0:
            home_cs += prob
        if h == 0 and a >= 0:
            away_cs += prob
    return {"home": round(home_cs, 4), "away": round(away_cs, 4)}


def _top_scores(matrix: ScoreMatrix, n: int = 5) -> list[dict[str, float | str]]:
    ranked = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
    return [{"score": s, "probability": round(p, 4)} for s, p in ranked[:n]]


def _effective_movement(before: float, after: float, target: float) -> float | None:
    gap = target - before
    if abs(gap) < MIN_MOVEMENT_GAP_PCT:
        return None
    return round((after - before) / gap * 100.0, 2)


def _market_targets(
    consensus: MarketConsensus,
    *,
    warnings: list[str],
) -> dict[str, float]:
    h2h = consensus.h2h or {}
    targets = {
        "home": h2h.get("home", 33.33),
        "draw": h2h.get("draw", 33.33),
        "away": h2h.get("away", 33.34),
        "over_2_5": 50.0,
        "btts_yes": 50.0,
    }
    totals = consensus.totals_by_line.get("2.5")
    if totals:
        targets["over_2_5"] = totals.get("over", 50.0)
    else:
        warnings.append("totals_2_5_missing_using_neutral_50")

    if consensus.btts:
        targets["btts_yes"] = consensus.btts.get("yes", 50.0)
    else:
        warnings.append("btts_missing_using_neutral_50")

    if not consensus.h2h:
        warnings.append("h2h_missing_using_neutral_thirds")

    return targets


def _target_ratio(target_pct: float, neutral: float = 33.33) -> float:
    return target_pct / neutral


def _clamp_factor(value: float, *, low: float = 0.50, high: float = 1.85) -> float:
    return max(low, min(high, value))


def _score_market_factor(
    h: int,
    a: int,
    targets: dict[str, float],
    favorite_side: str | None,
) -> float:
    if h > a:
        side_ratio = _target_ratio(targets["home"])
    elif h < a:
        side_ratio = _target_ratio(targets["away"])
    else:
        side_ratio = _target_ratio(targets["draw"])

    side_factor = _clamp_factor(side_ratio ** 0.85)
    total = h + a
    over_ratio = targets["over_2_5"] / 50.0
    if total >= 3:
        total_factor = _clamp_factor(over_ratio ** 0.85)
    else:
        total_factor = _clamp_factor((100.0 - targets["over_2_5"]) / 50.0) ** 0.85

    btts_ratio = targets["btts_yes"] / 50.0
    if h > 0 and a > 0:
        btts_factor = _clamp_factor(btts_ratio ** 0.90)
    else:
        btts_factor = _clamp_factor(((100.0 - targets["btts_yes"]) / 50.0) ** 0.90)

    favorite_factor = 1.0
    if favorite_side == "home" and h > a:
        favorite_factor = _clamp_factor(targets["home"] / 45.0, low=0.75, high=1.55)
    elif favorite_side == "away" and a > h:
        favorite_factor = _clamp_factor(targets["away"] / 45.0, low=0.75, high=1.55)
    elif favorite_side in ("home", "away"):
        favorite_factor = 0.94

    combined = (
        side_factor ** 0.38
        * total_factor ** 0.28
        * btts_factor ** 0.28
        * favorite_factor ** 0.06
    )
    return _clamp_factor(combined, low=0.45, high=2.0)


def _soft_marginal_pass(
    matrix: ScoreMatrix,
    targets: dict[str, float],
    blend: float,
) -> dict[str, float]:
    """Gentle second pass: nudge implied marginals toward market targets."""
    impl_1x2 = _implied_1x2(matrix)
    over = _implied_over_2_5(matrix)
    btts = _implied_btts(matrix)
    strength = blend * MARGINAL_NUDGE_BLEND_FRACTION

    raw: dict[str, float] = {}
    for score, prob in matrix.items():
        parsed = _parse_score(score)
        if parsed is None or prob <= 0:
            continue
        h, a = parsed
        mult = 1.0
        if h > a:
            mult += strength * (targets["home"] - impl_1x2["home"]) / 100.0
        elif h < a:
            mult += strength * (targets["away"] - impl_1x2["away"]) / 100.0
        else:
            mult += strength * (targets["draw"] - impl_1x2["draw"]) / 100.0

        if h + a >= 3:
            mult += strength * (targets["over_2_5"] - over) / 100.0
        else:
            mult += strength * ((100.0 - targets["over_2_5"]) - (100.0 - over)) / 100.0

        if h > 0 and a > 0:
            mult += strength * (targets["btts_yes"] - btts) / 100.0
        else:
            mult += strength * ((100.0 - targets["btts_yes"]) - (100.0 - btts)) / 100.0

        raw[score] = prob * max(0.62, min(1.55, mult))

    return _normalize_matrix(raw)


def _favorite_side_from_h2h(h2h: dict[str, float] | None) -> str | None:
    if not h2h:
        return None
    sides = {"home": h2h.get("home", 0.0), "draw": h2h.get("draw", 0.0), "away": h2h.get("away", 0.0)}
    best = max(sides, key=sides.get)
    return None if best == "draw" else best


def _movement_notes(
    requested_weight: int,
    effective_h2h: dict[str, float | None],
    effective_over: float | None,
    effective_btts: float | None,
    effective_favorite: float | None,
) -> list[str]:
    notes = [
        f"shadow_weight_requested_{requested_weight}",
        "requested_weight_is_diagnostic_target_not_linear_blend",
        "calibration_v1_cell_reweight_plus_soft_marginal_pass",
    ]
    for side, eff in effective_h2h.items():
        if eff is None:
            notes.append(f"effective_h2h_{side}_movement_unavailable")
        else:
            notes.append(f"effective_h2h_{side}_movement_{eff:g}pct")
    if effective_over is None:
        notes.append("effective_over_2_5_movement_unavailable")
    else:
        notes.append(f"effective_over_2_5_movement_{effective_over:g}pct")
    if effective_btts is None:
        notes.append("effective_btts_movement_unavailable")
    else:
        notes.append(f"effective_btts_movement_{effective_btts:g}pct")
    if effective_favorite is None:
        notes.append("effective_favorite_side_movement_unavailable")
    else:
        notes.append(f"effective_favorite_side_movement_{effective_favorite:g}pct")

    weak_axes: list[str] = []
    if effective_favorite is not None and effective_favorite < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        weak_axes.append("favorite_side")
    if effective_btts is not None and effective_btts < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        weak_axes.append("btts")
    if effective_over is not None and effective_over < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        weak_axes.append("over_2_5")
    if weak_axes:
        notes.append(
            "effective_movement_below_requested_due_to_cell_normalization_conflicting_constraints_clamping:"
            + ",".join(weak_axes)
        )
    return notes


def calibrate_market_matrix_shadow(
    model_score_matrix: Mapping[str, float],
    consensus: MarketConsensus,
    quality: MarketQualityResult,
) -> MarketMatrixShadowResult:
    """Shadow-calibrate a score matrix toward market consensus (diagnostic only)."""
    warnings: list[str] = []
    base_notes = ["shadow_matrix_v1_weighted_reweight", "not_production_prediction"]

    original = _normalize_matrix(copy.deepcopy(dict(model_score_matrix)))
    if abs(sum(original.values()) - 100.0) > 0.5:
        warnings.append("input_matrix_renormalized_to_100")

    requested_weight = shadow_market_weight(quality)
    blend = requested_weight / 100.0
    base_notes.append(f"quality_band_{quality.band.lower()}")

    targets = _market_targets(consensus, warnings=warnings)
    favorite_side = _favorite_side_from_h2h(consensus.h2h)

    if quality.band == BAND_RED:
        warnings.append("red_band_limited_market_depth")
    if not consensus.spreads_by_line:
        warnings.append("spreads_missing_favorite_margin_not_used_in_v1")

    raw_adjusted: dict[str, float] = {}
    for score, prob in original.items():
        parsed = _parse_score(score)
        if parsed is None or prob <= 0:
            warnings.append(f"skipped_invalid_score:{score}")
            continue
        h, a = parsed
        factor = _score_market_factor(h, a, targets, favorite_side)
        adjusted_prob = prob * ((1.0 - blend) + blend * factor)
        raw_adjusted[score] = adjusted_prob

    first_pass = _normalize_matrix(raw_adjusted)
    calibrated = _soft_marginal_pass(first_pass, targets, blend)
    delta = {s: round(calibrated.get(s, 0.0) - original.get(s, 0.0), 6) for s in original}

    implied_1x2_before = _implied_1x2(original)
    implied_1x2_after = _implied_1x2(calibrated)
    over_before = _implied_over_2_5(original)
    over_after = _implied_over_2_5(calibrated)
    btts_before = _implied_btts(original)
    btts_after = _implied_btts(calibrated)

    effective_h2h = {
        side: _effective_movement(implied_1x2_before[side], implied_1x2_after[side], targets[side])
        for side in ("home", "draw", "away")
    }
    effective_over = _effective_movement(over_before, over_after, targets["over_2_5"])
    effective_btts = _effective_movement(btts_before, btts_after, targets["btts_yes"])
    effective_favorite = None
    if favorite_side in ("home", "away"):
        effective_favorite = effective_h2h[favorite_side]

    movement_notes = _movement_notes(
        requested_weight,
        effective_h2h,
        effective_over,
        effective_btts,
        effective_favorite,
    )
    if effective_btts is not None and effective_btts < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        warnings.append(
            "btts_effective_movement_weak_v1_conservative_calibration_and_conflicting_marginals"
        )

    return MarketMatrixShadowResult(
        original_model_matrix=original,
        shadow_calibrated_matrix=calibrated,
        matrix_delta_by_score=delta,
        implied_1x2_before=implied_1x2_before,
        implied_1x2_after=implied_1x2_after,
        implied_total_over_2_5_before=over_before,
        implied_total_over_2_5_after=over_after,
        implied_btts_before=btts_before,
        implied_btts_after=btts_after,
        implied_clean_sheet_before=_implied_clean_sheet(original),
        implied_clean_sheet_after=_implied_clean_sheet(calibrated),
        top_scores_before=_top_scores(original),
        top_scores_after=_top_scores(calibrated),
        requested_shadow_weight_pct=requested_weight,
        effective_h2h_movement_pct=effective_h2h,
        effective_over_2_5_movement_pct=effective_over,
        effective_btts_movement_pct=effective_btts,
        effective_favorite_side_movement_pct=effective_favorite,
        calibration_notes=base_notes + movement_notes,
        warnings=warnings,
    )
