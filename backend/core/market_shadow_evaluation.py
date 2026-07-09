"""Shadow evaluation harness for market matrix diagnostics (Phase 3C — not wired to predict)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from core.market_consensus import build_market_consensus
from core.market_matrix_shadow import (
    WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT,
    calibrate_market_matrix_shadow,
)
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW
from core.market_shadow import build_market_shadow_report
from core.market_types import MarketConsensus, MarketQualityResult, NormalizedMarketSnapshot

VERDICT_PASS = "PASS"
VERDICT_REVIEW = "REVIEW"
VERDICT_FAIL = "FAIL"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


@dataclass
class ShadowEvaluationReport:
    """Per-case shadow evaluation output (diagnostic only)."""

    fixture: str
    home_team: str
    away_team: str
    model_primary_score: str | None
    model_top_scores: list[dict[str, Any]]
    market_favorite: str
    market_h2h: dict[str, float]
    totals_pressure: dict[str, Any] | None
    btts_pressure: dict[str, Any] | None
    spread_pressure: dict[str, Any] | None
    quality_band: str
    requested_shadow_weight_pct: int
    effective_movement: dict[str, Any]
    shadow_top_scores_after: list[dict[str, Any]]
    shadow_direction_reasonable: bool
    direction_notes: list[str]
    warnings: list[str]
    verdict: str
    verdict_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "model_primary_score": self.model_primary_score,
            "model_top_scores": self.model_top_scores,
            "market_favorite": self.market_favorite,
            "market_h2h": self.market_h2h,
            "totals_pressure": self.totals_pressure,
            "btts_pressure": self.btts_pressure,
            "spread_pressure": self.spread_pressure,
            "quality_band": self.quality_band,
            "requested_shadow_weight_pct": self.requested_shadow_weight_pct,
            "effective_movement": self.effective_movement,
            "shadow_top_scores_after": self.shadow_top_scores_after,
            "shadow_direction_reasonable": self.shadow_direction_reasonable,
            "direction_notes": self.direction_notes,
            "warnings": self.warnings,
            "verdict": self.verdict,
            "verdict_reasons": self.verdict_reasons,
        }


def _load_market_snapshot(case: Mapping[str, Any]) -> NormalizedMarketSnapshot:
    if "inline_market" in case:
        return parse_rapidapi_odds_feed_audit(case["inline_market"])
    fixture_name = str(case.get("fixture") or case.get("market_fixture") or "")
    path = FIXTURES_DIR / fixture_name
    if not path.exists():
        raise FileNotFoundError(f"market fixture not found: {path}")
    import json

    report = json.loads(path.read_text(encoding="utf-8"))
    return parse_rapidapi_odds_feed_audit(report)


def _pressure_dict(report_dict: dict[str, Any], key: str) -> dict[str, Any] | None:
    val = report_dict.get(key)
    return val if isinstance(val, dict) else None


def _direction_reasonable(
    shadow: dict[str, Any],
    matrix_result: Any,
    quality: MarketQualityResult,
) -> tuple[bool, list[str], list[str]]:
    notes: list[str] = []
    warnings: list[str] = list(matrix_result.warnings)

    h2h = shadow.get("market_h2h") or {}
    favorite_side = shadow.get("market_favorite_side")
    fav_name = shadow.get("market_favorite")

    impl_before = matrix_result.implied_1x2_before
    impl_after = matrix_result.implied_1x2_after
    over_before = matrix_result.implied_total_over_2_5_before
    over_after = matrix_result.implied_total_over_2_5_after
    btts_before = matrix_result.implied_btts_before
    btts_after = matrix_result.implied_btts_after

    direction_ok = True

    if favorite_side in ("home", "away"):
        before_fav = impl_before[favorite_side]
        after_fav = impl_after[favorite_side]
        target_fav = h2h.get(favorite_side, before_fav)
        if target_fav > before_fav + 0.5 and after_fav < before_fav - 0.01:
            direction_ok = False
            notes.append(f"favorite_{favorite_side}_moved_opposite_market")
        elif target_fav < before_fav - 0.5 and after_fav > before_fav + 0.01:
            direction_ok = False
            notes.append(f"favorite_{favorite_side}_moved_opposite_market")
        else:
            notes.append(f"favorite_{fav_name}_direction_aligned")

    totals = _pressure_dict(shadow, "totals_pressure")
    if totals:
        over_target = totals.get("value_pct", 50.0)
        if over_target > 52.0 and over_after < over_before - 0.01:
            direction_ok = False
            notes.append("over_2_5_moved_opposite_market")
        elif over_target < 48.0 and over_after > over_before + 0.01:
            direction_ok = False
            notes.append("under_2_5_moved_opposite_market")
        else:
            notes.append("totals_direction_aligned")

    btts = _pressure_dict(shadow, "btts_pressure")
    if btts:
        yes_target = btts.get("value_pct", 50.0)
        if yes_target > 52.0 and btts_after < btts_before - 0.01:
            direction_ok = False
            notes.append("btts_yes_moved_opposite_market")
        elif yes_target < 48.0 and btts_after > btts_before + 0.01:
            direction_ok = False
            notes.append("btts_no_moved_opposite_market")
        else:
            notes.append("btts_direction_aligned")

    all_notes = list(matrix_result.calibration_notes) + list(shadow.get("notes") or [])
    if any("favorite_win_pressure_unavailable" in n for n in all_notes):
        warnings.append("handicap_win_line_unavailable")
    if "asian_handicap_line_point_is_home_perspective" not in " ".join(all_notes):
        warnings.append("handicap_convention_note_missing")

    if quality.band in (BAND_RED, BAND_YELLOW):
        warnings.append(f"quality_band_{quality.band.lower()}_limited_depth")

    eff_fav = matrix_result.effective_favorite_side_movement_pct
    if eff_fav is not None and eff_fav < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        warnings.append("effective_movement_weak")

    return direction_ok, notes, warnings


def compute_shadow_verdict(
    *,
    matrix_sum: float,
    input_mutated: bool,
    direction_reasonable: bool,
    quality_band: str,
    warnings: list[str],
    effective_favorite: float | None,
    opposite_movement: bool = False,
    handicap_incoherent: bool = False,
) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if input_mutated:
        reasons.append("model_input_mutated")
    if abs(matrix_sum - 100.0) > 0.5:
        reasons.append("probabilities_not_normalized")
    if opposite_movement or not direction_reasonable:
        reasons.append("shadow_direction_opposite_or_incoherent")
    if handicap_incoherent:
        reasons.append("handicap_sign_incoherent")

    if reasons:
        return VERDICT_FAIL, reasons

    if quality_band in (BAND_RED, BAND_YELLOW):
        reasons.append("limited_market_quality")
        return VERDICT_REVIEW, reasons

    if effective_favorite is not None and effective_favorite < WEAK_EFFECTIVE_MOVEMENT_THRESHOLD_PCT:
        reasons.append("effective_movement_below_threshold")
        return VERDICT_REVIEW, reasons

    if any("effective_movement_weak" in w for w in warnings):
        reasons.append("effective_movement_weak_warning")
        return VERDICT_REVIEW, reasons

    if any("conflicting" in w for w in warnings):
        reasons.append("conflicting_market_signals")
        return VERDICT_REVIEW, reasons

    reasons.append("coherent_green_fixture_shadow_behavior")
    return VERDICT_PASS, reasons


def evaluate_shadow_case(case: Mapping[str, Any]) -> ShadowEvaluationReport:
    """Run shadow diagnostics + matrix calibration for one static evaluation case."""
    name = str(case.get("name") or case.get("fixture") or "unnamed")
    snapshot = _load_market_snapshot(case)
    consensus, quality = build_snapshot_pipeline(snapshot)

    home_team = str(case.get("home_team") or snapshot.home_team)
    away_team = str(case.get("away_team") or snapshot.away_team)
    matrix_in = copy.deepcopy(dict(case["model_score_matrix"]))
    model_sample = {
        "primary_score": case.get("model_primary_score"),
        "top_scores": copy.deepcopy(case.get("model_top_scores") or []),
    }
    matrix_before = copy.deepcopy(matrix_in)

    shadow = build_market_shadow_report(model_sample, consensus, quality, snapshot=snapshot)
    shadow_dict = shadow.to_dict()
    matrix_result = calibrate_market_matrix_shadow(matrix_in, consensus, quality)

    input_mutated = matrix_in != matrix_before or model_sample != {
        "primary_score": case.get("model_primary_score"),
        "top_scores": case.get("model_top_scores") or [],
    }

    direction_ok, direction_notes, warnings = _direction_reasonable(shadow_dict, matrix_result, quality)
    matrix_sum = sum(matrix_result.shadow_calibrated_matrix.values())

    verdict, verdict_reasons = compute_shadow_verdict(
        matrix_sum=matrix_sum,
        input_mutated=input_mutated,
        direction_reasonable=direction_ok,
        quality_band=quality.band,
        warnings=warnings,
        effective_favorite=matrix_result.effective_favorite_side_movement_pct,
    )

    return ShadowEvaluationReport(
        fixture=name,
        home_team=home_team,
        away_team=away_team,
        model_primary_score=model_sample.get("primary_score"),
        model_top_scores=model_sample.get("top_scores") or [],
        market_favorite=shadow.market_favorite,
        market_h2h=shadow.market_h2h,
        totals_pressure=_pressure_dict(shadow_dict, "totals_pressure"),
        btts_pressure=_pressure_dict(shadow_dict, "btts_pressure"),
        spread_pressure=_pressure_dict(shadow_dict, "spread_pressure"),
        quality_band=quality.band,
        requested_shadow_weight_pct=matrix_result.requested_shadow_weight_pct,
        effective_movement={
            "h2h": matrix_result.effective_h2h_movement_pct,
            "over_2_5": matrix_result.effective_over_2_5_movement_pct,
            "btts": matrix_result.effective_btts_movement_pct,
            "favorite_side": matrix_result.effective_favorite_side_movement_pct,
        },
        shadow_top_scores_after=matrix_result.top_scores_after,
        shadow_direction_reasonable=direction_ok,
        direction_notes=direction_notes,
        warnings=warnings + list(matrix_result.warnings),
        verdict=verdict,
        verdict_reasons=verdict_reasons,
    )


def run_shadow_evaluation(cases: list[Mapping[str, Any]]) -> list[ShadowEvaluationReport]:
    return [evaluate_shadow_case(case) for case in cases]


def load_evaluation_cases(path: Path | None = None) -> list[dict[str, Any]]:
    import json

    cases_path = path or (FIXTURES_DIR / "market_shadow_eval_cases.json")
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])
