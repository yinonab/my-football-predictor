"""Phase 6A — optional market influence on exact-score prediction (gated, fail-safe)."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping

import config
from core.market_live_fetch import MarketLiveFetchError, fetch_live_market_audit_report
from core.market_matrix_shadow import calibrate_market_matrix_shadow
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW

_BAND_RANK = {BAND_RED: 0, BAND_YELLOW: 1, BAND_GREEN: 2}
_DEFAULT_PROVIDER = "rapidapi_odds_feed"


@dataclass(frozen=True)
class MarketInfluenceResult:
    applied: bool
    top_scores: list[dict[str, Any]] | None = None
    calibrated_matrix: dict[str, float] | None = None
    metadata: dict[str, Any] | None = None


def normalize_team_for_event_map(name: str) -> str:
    cleaned = re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip()
    return re.sub(r"\s+", " ", cleaned)


def make_event_map_key(home_team: str, away_team: str) -> str:
    return f"{normalize_team_for_event_map(home_team)}|{normalize_team_for_event_map(away_team)}"


def resolve_provider_event_id(
    *,
    home_team: str,
    away_team: str,
    request_event_id: str | None,
    event_map: Mapping[str, str] | None = None,
) -> str | None:
    explicit = str(request_event_id or "").strip()
    if explicit:
        return explicit
    mapping = dict(event_map or config.load_market_provider_event_map())
    if not mapping:
        return None
    home = normalize_team_for_event_map(home_team)
    away = normalize_team_for_event_map(away_team)
    for key in (f"{home}|{away}", f"{away}|{home}"):
        hit = mapping.get(key)
        if hit:
            return str(hit).strip()
    return None


def quality_meets_minimum(band: str, min_band: str) -> bool:
    return _BAND_RANK.get(band, 0) >= _BAND_RANK.get(min_band, 1)


def influence_weight_pct(*, quality_band: str, max_weight: float) -> int | None:
    max_pct = max(0, min(100, int(round(max_weight * 100))))
    if quality_band == BAND_RED:
        return None
    if quality_band == BAND_YELLOW:
        return min(30, max_pct)
    if quality_band == BAND_GREEN:
        return max_pct
    return None


def market_influence_gates_satisfied(
    *,
    influence_enabled: bool,
    shadow_diagnostics_enabled: bool,
    live_fetch_enabled: bool,
    provider_event_id: str | None,
) -> bool:
    if not influence_enabled or not shadow_diagnostics_enabled or not live_fetch_enabled:
        return False
    return bool(str(provider_event_id or "").strip())


def _matrix_usable(matrix: Mapping[str, float]) -> bool:
    if not matrix:
        return False
    total = sum(v for v in matrix.values() if v > 0)
    return total > 0


def try_apply_market_influence_to_predict(
    *,
    home_team: str,
    away_team: str,
    model_score_matrix: Mapping[str, float] | None,
    provider_event_id: str | None = None,
    market_region: str | None = None,
    influence_enabled: bool | None = None,
    shadow_diagnostics_enabled: bool | None = None,
    live_fetch_enabled: bool | None = None,
    max_weight: float | None = None,
    min_quality_band: str | None = None,
    event_map: Mapping[str, str] | None = None,
) -> MarketInfluenceResult:
    """Apply gated market influence to exact-score outputs; never raises to caller."""
    influence_on = (
        config.market_influence_enabled() if influence_enabled is None else influence_enabled
    )
    shadow_on = (
        config.market_shadow_diagnostics_enabled()
        if shadow_diagnostics_enabled is None
        else shadow_diagnostics_enabled
    )
    live_on = (
        config.market_live_provider_fetch_enabled()
        if live_fetch_enabled is None
        else live_fetch_enabled
    )
    resolved_event_id = resolve_provider_event_id(
        home_team=home_team,
        away_team=away_team,
        request_event_id=provider_event_id,
        event_map=event_map,
    )
    if not market_influence_gates_satisfied(
        influence_enabled=influence_on,
        shadow_diagnostics_enabled=shadow_on,
        live_fetch_enabled=live_on,
        provider_event_id=resolved_event_id,
    ):
        return MarketInfluenceResult(applied=False)

    if not model_score_matrix:
        return MarketInfluenceResult(applied=False)

    try:
        fetch_result = fetch_live_market_audit_report(
            provider=_DEFAULT_PROVIDER,
            provider_event_id=str(resolved_event_id),
            home_team=home_team,
            away_team=away_team,
            live_fetch_enabled=True,
            region=market_region,
        )
        snapshot = parse_rapidapi_odds_feed_audit(fetch_result.audit_report)
    except MarketLiveFetchError:
        return MarketInfluenceResult(applied=False)

    consensus, quality = build_snapshot_pipeline(snapshot)
    min_band = (
        config.market_influence_min_quality() if min_quality_band is None else min_quality_band
    )
    if not quality_meets_minimum(quality.band, min_band):
        return MarketInfluenceResult(
            applied=False,
            metadata={
                "market_influence_applied": False,
                "quality_band": quality.band,
                "fallback_reason": "quality_below_minimum",
            },
        )

    weight_pct = influence_weight_pct(
        quality_band=quality.band,
        max_weight=config.market_influence_max_weight() if max_weight is None else max_weight,
    )
    if weight_pct is None:
        return MarketInfluenceResult(
            applied=False,
            metadata={
                "market_influence_applied": False,
                "quality_band": quality.band,
                "fallback_reason": "red_band_no_influence",
            },
        )

    matrix_work = copy.deepcopy(dict(model_score_matrix))
    calibration = calibrate_market_matrix_shadow(
        matrix_work,
        consensus,
        quality,
        requested_weight_pct=weight_pct,
    )
    calibrated = dict(calibration.shadow_calibrated_matrix)
    if not _matrix_usable(calibrated):
        return MarketInfluenceResult(
            applied=False,
            metadata={
                "market_influence_applied": False,
                "quality_band": quality.band,
                "fallback_reason": "calibrated_matrix_invalid",
            },
        )

    top_scores = [
        {"score": row["score"], "probability": float(row["probability"])}
        for row in calibration.top_scores_after
    ]
    if not top_scores:
        return MarketInfluenceResult(applied=False)

    return MarketInfluenceResult(
        applied=True,
        top_scores=top_scores,
        calibrated_matrix=calibrated,
        metadata={
            "market_influence_applied": True,
            "quality_band": quality.band,
            "quality_score": quality.score,
            "influence_weight_pct": weight_pct,
            "provider": _DEFAULT_PROVIDER,
            "provider_event_id": str(resolved_event_id),
            "cache_status": fetch_result.cache_status,
            "provider_call_count": fetch_result.provider_call_count,
            "primary_score_reason": "market_influence_applied",
            "market_source": "live",
        },
    )
