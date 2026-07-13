"""Phase 6A — optional market influence on exact-score prediction (gated, fail-safe)."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

import config
from core.market_event_map import make_event_map_key, normalize_team_for_event_map
from core.market_event_resolver import EventResolverResult, try_auto_resolve_provider_event_id
from core.market_live_fetch import MarketLiveFetchError, fetch_live_market_audit_report
from core.market_matrix_shadow import calibrate_market_matrix_shadow
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW

if TYPE_CHECKING:
    from core.market_resolution import MarketResolutionContext

_BAND_RANK = {BAND_RED: 0, BAND_YELLOW: 1, BAND_GREEN: 2}
_DEFAULT_PROVIDER = "rapidapi_odds_feed"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketInfluenceResult:
    applied: bool
    top_scores: list[dict[str, Any]] | None = None
    calibrated_matrix: dict[str, float] | None = None
    metadata: dict[str, Any] | None = None
    status: dict[str, Any] | None = None


def map_resolver_match_reason(match_reason: str | None) -> str:
    """Map internal resolver match_reason to API market_influence_status.reason."""
    reason = (match_reason or "").strip().lower()
    if reason in (
        "ambiguous_forward",
        "ambiguous_reversed",
        "ambiguous_forward_fuzzy",
        "ambiguous_reversed_fuzzy",
    ):
        return "resolver_ambiguous"
    if reason == "outside_window":
        return "resolver_outside_window"
    if reason == "no_match":
        return "resolver_no_match"
    if reason in ("provider_error", "call_budget_exceeded"):
        return "provider_event_id_missing"
    return "resolver_no_match"


def build_market_influence_status(
    *,
    attempted: bool,
    applied: bool,
    reason: str,
    provider_event_id: str | None = None,
    resolver_window_hours: int | None = None,
    provider: str | None = _DEFAULT_PROVIDER,
    resolver_result: EventResolverResult | None = None,
) -> dict[str, Any]:
    """Non-sensitive status block for /api/predict (no secrets or raw provider payloads)."""
    status = {
        "attempted": attempted,
        "applied": applied,
        "reason": reason,
        "provider": provider,
        "resolver_window_hours": resolver_window_hours,
        "provider_event_id": str(provider_event_id).strip() if provider_event_id else None,
    }
    if resolver_result is not None:
        if resolver_result.pages_fetched is not None:
            status["resolver_pages_fetched"] = resolver_result.pages_fetched
        if resolver_result.events_seen is not None:
            status["resolver_events_seen"] = resolver_result.events_seen
        if resolver_result.discovery_status:
            status["resolver_discovery_status"] = resolver_result.discovery_status
        if resolver_result.api_lookback_hours is not None:
            status["resolver_api_lookback_hours"] = resolver_result.api_lookback_hours
        if resolver_result.api_lookahead_hours is not None:
            status["resolver_api_lookahead_hours"] = resolver_result.api_lookahead_hours
        if resolver_result.list_cache_status in ("hit", "miss"):
            status["resolver_cache_status"] = resolver_result.list_cache_status
    return status


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
    resolution_context: MarketResolutionContext | None = None,
) -> MarketInfluenceResult:
    """Apply gated market influence to exact-score outputs; never raises to caller."""
    influence_on = (
        config.market_influence_enabled() if influence_enabled is None else influence_enabled
    )
    if not influence_on:
        return MarketInfluenceResult(applied=False)

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
    resolver_window_hours = config.market_event_resolver_lookahead_hours()

    if not shadow_on or not live_on:
        return MarketInfluenceResult(
            applied=False,
            status=build_market_influence_status(
                attempted=False,
                applied=False,
                reason="provider_disabled",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
            ),
        )

    resolved_event_id = resolve_provider_event_id(
        home_team=home_team,
        away_team=away_team,
        request_event_id=provider_event_id,
        event_map=event_map,
    )
    mapped_event_id = resolved_event_id
    resolver_result: EventResolverResult | None = None
    shared_snapshot = None
    shared_consensus = None
    shared_quality = None
    shared_fetch_cache_status: str | None = None
    shared_fetch_call_count = 0

    if resolution_context is not None:
        resolved_event_id = resolution_context.provider_event_id or resolved_event_id
        resolver_result = resolution_context.resolver_result
        shared_snapshot = resolution_context.snapshot
        shared_consensus = resolution_context.consensus
        shared_quality = resolution_context.quality
        shared_fetch_cache_status = resolution_context.fetch_cache_status
        shared_fetch_call_count = resolution_context.markets_fetch_call_count
    elif not resolved_event_id:
        resolver_result = try_auto_resolve_provider_event_id(
            home_team=home_team,
            away_team=away_team,
            influence_enabled=influence_on,
            shadow_diagnostics_enabled=shadow_on,
            live_fetch_enabled=live_on,
            request_event_id=provider_event_id,
            mapped_event_id=mapped_event_id,
        )
        resolved_event_id = resolver_result.event_id
        if not resolved_event_id and resolver_result.match_reason:
            logger.info(
                "influence_fallback_reason=resolver_%s home=%s away=%s",
                resolver_result.match_reason,
                normalize_team_for_event_map(home_team),
                normalize_team_for_event_map(away_team),
            )

    if not market_influence_gates_satisfied(
        influence_enabled=influence_on,
        shadow_diagnostics_enabled=shadow_on,
        live_fetch_enabled=live_on,
        provider_event_id=resolved_event_id,
    ):
        if resolved_event_id is None and influence_on and shadow_on and live_on:
            logger.info(
                "influence_fallback_reason=no_provider_event_id home=%s away=%s",
                normalize_team_for_event_map(home_team),
                normalize_team_for_event_map(away_team),
            )
        if resolved_event_id:
            status_reason = "provider_event_id_missing"
        elif resolver_result is not None and resolver_result.match_reason:
            status_reason = map_resolver_match_reason(resolver_result.match_reason)
        else:
            status_reason = "provider_event_id_missing"
        return MarketInfluenceResult(
            applied=False,
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason=status_reason,
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
                resolver_result=resolver_result,
            ),
        )

    if not model_score_matrix:
        return MarketInfluenceResult(
            applied=False,
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="provider_event_id_missing",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
        )

    try:
        if shared_snapshot is not None and shared_consensus is not None and shared_quality is not None:
            snapshot = shared_snapshot
            consensus = shared_consensus
            quality = shared_quality
            fetch_cache_status = shared_fetch_cache_status or "disabled"
            fetch_call_count = shared_fetch_call_count
        else:
            fetch_result = fetch_live_market_audit_report(
                provider=_DEFAULT_PROVIDER,
                provider_event_id=str(resolved_event_id),
                home_team=home_team,
                away_team=away_team,
                live_fetch_enabled=True,
                region=market_region,
            )
            snapshot = parse_rapidapi_odds_feed_audit(fetch_result.audit_report)
            consensus, quality = build_snapshot_pipeline(snapshot)
            fetch_cache_status = fetch_result.cache_status
            fetch_call_count = fetch_result.provider_call_count
    except MarketLiveFetchError as exc:
        logger.warning(
            "influence_fallback_reason=live_fetch_error home=%s away=%s detail=%s",
            normalize_team_for_event_map(home_team),
            normalize_team_for_event_map(away_team),
            str(exc),
        )
        return MarketInfluenceResult(
            applied=False,
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="live_fetch_failed",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
        )

    min_band = (
        config.market_influence_min_quality() if min_quality_band is None else min_quality_band
    )
    if not quality_meets_minimum(quality.band, min_band):
        logger.info(
            "influence_fallback_reason=quality_below_minimum band=%s home=%s away=%s",
            quality.band,
            normalize_team_for_event_map(home_team),
            normalize_team_for_event_map(away_team),
        )
        return MarketInfluenceResult(
            applied=False,
            metadata={
                "market_influence_applied": False,
                "quality_band": quality.band,
                "fallback_reason": "quality_below_minimum",
            },
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="quality_below_minimum",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
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
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="quality_below_minimum",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
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
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="quality_below_minimum",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
        )

    top_scores = [
        {"score": row["score"], "probability": float(row["probability"])}
        for row in calibration.top_scores_after
    ]
    if not top_scores:
        return MarketInfluenceResult(
            applied=False,
            status=build_market_influence_status(
                attempted=True,
                applied=False,
                reason="quality_below_minimum",
                provider=_DEFAULT_PROVIDER,
                resolver_window_hours=resolver_window_hours,
                provider_event_id=resolved_event_id,
            ),
        )

    applied_status = build_market_influence_status(
        attempted=True,
        applied=True,
        reason="applied",
        provider=_DEFAULT_PROVIDER,
        resolver_window_hours=resolver_window_hours,
        provider_event_id=resolved_event_id,
        resolver_result=resolver_result,
    )
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
            "cache_status": fetch_cache_status,
            "provider_call_count": fetch_call_count,
            "primary_score_reason": "market_influence_applied",
            "market_source": "live",
        },
        status=applied_status,
    )
