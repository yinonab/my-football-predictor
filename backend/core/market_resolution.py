"""Shared per-request market resolution for predict (resolver + single odds-feed fetch)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

import config
from core.market_consensus import build_market_consensus
from core.market_event_resolver import EventResolverResult, try_auto_resolve_provider_event_id
from core.market_influence import resolve_provider_event_id
from core.market_live_fetch import MarketLiveFetchError, fetch_live_market_audit_report
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_types import MarketConsensus, MarketFamily, MarketQualityResult, NormalizedMarketSnapshot
from core.odds_ensemble import BookmakerOddsLine, OddsMarketFetch

_DEFAULT_PROVIDER = "rapidapi_odds_feed"
logger = logging.getLogger(__name__)


@dataclass
class MarketResolutionContext:
    provider: str = _DEFAULT_PROVIDER
    provider_event_id: str | None = None
    resolved_via: str | None = None  # explicit | map | resolver | none
    resolver_reason: str | None = None
    resolver_result: EventResolverResult | None = None
    resolver_cache_status: str = "disabled"
    resolver_call_count: int = 0
    fetch_cache_status: str | None = None
    markets_fetch_call_count: int = 0
    fetch_error: str | None = None
    snapshot: NormalizedMarketSnapshot | None = None
    consensus: MarketConsensus | None = None
    quality: MarketQualityResult | None = None
    odds_market_fetch: OddsMarketFetch | None = None
    diagnostics_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def provider_call_count(self) -> int:
        return self.resolver_call_count + self.markets_fetch_call_count


def odds_feed_snapshot_to_market_fetch(
    snapshot: NormalizedMarketSnapshot,
    consensus: MarketConsensus,
) -> OddsMarketFetch | None:
    """Map odds-feed h2h snapshot into legacy OddsMarketFetch shape for Market tab."""
    h2h = consensus.h2h
    if not h2h:
        return None

    consensus_1x2 = {
        "home_win": round(float(h2h["home"]), 2),
        "draw": round(float(h2h["draw"]), 2),
        "away_win": round(float(h2h["away"]), 2),
    }
    bookmakers: list[BookmakerOddsLine] = []
    for line in snapshot.lines:
        if line.family != MarketFamily.H2H:
            continue
        by_name = {o.name: o for o in line.outcomes}
        home_o = by_name.get("home")
        draw_o = by_name.get("draw")
        away_o = by_name.get("away")
        if home_o is None or draw_o is None or away_o is None:
            continue
        bookmakers.append(
            BookmakerOddsLine(
                id=line.bookmaker_id,
                display_name=line.bookmaker_name,
                region="global",
                home_decimal_odds=home_o.decimal_odds,
                draw_decimal_odds=draw_o.decimal_odds,
                away_decimal_odds=away_o.decimal_odds,
                implied_1x2_percent={
                    "home_win": round(home_o.fair_probability, 2),
                    "draw": round(draw_o.fair_probability, 2),
                    "away_win": round(away_o.fair_probability, 2),
                },
                source_key=_DEFAULT_PROVIDER,
            )
        )

    if not bookmakers:
        return None

    return OddsMarketFetch(
        sport_key=_DEFAULT_PROVIDER,
        bookmakers=bookmakers,
        consensus_1x2_percent=consensus_1x2,
    )


def _should_auto_resolve(
    *,
    resolved_event_id: str | None,
    request_event_id: str | None,
    influence_enabled: bool,
    shadow_diagnostics_enabled: bool,
    live_fetch_enabled: bool,
) -> bool:
    if resolved_event_id:
        return False
    if str(request_event_id or "").strip():
        return False
    if not config.market_auto_event_resolver_enabled():
        return False
    if not live_fetch_enabled:
        return False
    if influence_enabled and shadow_diagnostics_enabled:
        return True
    return True


def _should_fetch_markets(
    *,
    provider_event_id: str | None,
    live_fetch_enabled: bool,
) -> bool:
    return bool(str(provider_event_id or "").strip()) and live_fetch_enabled


def build_market_resolution_context(
    *,
    home_team: str,
    away_team: str,
    provider_event_id: str | None = None,
    market_region: str | None = None,
    event_map: Mapping[str, str] | None = None,
    influence_enabled: bool | None = None,
    shadow_diagnostics_enabled: bool | None = None,
    live_fetch_enabled: bool | None = None,
) -> MarketResolutionContext:
    """Resolve provider_event_id and optionally fetch odds-feed markets once per predict."""
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

    ctx = MarketResolutionContext(provider=_DEFAULT_PROVIDER)
    explicit = str(provider_event_id or "").strip()
    if explicit:
        ctx.provider_event_id = explicit
        ctx.resolved_via = "explicit"
    else:
        mapped = resolve_provider_event_id(
            home_team=home_team,
            away_team=away_team,
            request_event_id=None,
            event_map=event_map,
        )
        if mapped:
            ctx.provider_event_id = mapped
            ctx.resolved_via = "map"

    if _should_auto_resolve(
        resolved_event_id=ctx.provider_event_id,
        request_event_id=provider_event_id,
        influence_enabled=influence_on,
        shadow_diagnostics_enabled=shadow_on,
        live_fetch_enabled=live_on,
    ):
        for_diagnostics = not (influence_on and shadow_on)
        resolver_result = try_auto_resolve_provider_event_id(
            home_team=home_team,
            away_team=away_team,
            influence_enabled=influence_on,
            shadow_diagnostics_enabled=shadow_on,
            live_fetch_enabled=live_on,
            request_event_id=provider_event_id,
            mapped_event_id=ctx.provider_event_id,
            for_diagnostics=for_diagnostics,
        )
        ctx.resolver_result = resolver_result
        ctx.resolver_reason = resolver_result.match_reason
        ctx.resolver_cache_status = resolver_result.cache_status
        ctx.resolver_call_count = resolver_result.provider_call_count
        if resolver_result.event_id:
            ctx.provider_event_id = resolver_result.event_id
            ctx.resolved_via = "resolver"

    if not _should_fetch_markets(provider_event_id=ctx.provider_event_id, live_fetch_enabled=live_on):
        return ctx

    try:
        fetch_result = fetch_live_market_audit_report(
            provider=_DEFAULT_PROVIDER,
            provider_event_id=str(ctx.provider_event_id),
            home_team=home_team,
            away_team=away_team,
            live_fetch_enabled=True,
            region=market_region,
        )
        snapshot = parse_rapidapi_odds_feed_audit(fetch_result.audit_report)
        consensus, quality = build_snapshot_pipeline(snapshot)
        odds_fetch = odds_feed_snapshot_to_market_fetch(snapshot, consensus)
        ctx.fetch_cache_status = fetch_result.cache_status
        ctx.markets_fetch_call_count = fetch_result.provider_call_count
        ctx.snapshot = snapshot
        ctx.consensus = consensus
        ctx.quality = quality
        ctx.odds_market_fetch = odds_fetch
        ctx.diagnostics_metadata = {
            "cache_status": fetch_result.cache_status,
            "provider_call_count": ctx.provider_call_count,
            "bookmaker_count": len(odds_fetch.bookmakers) if odds_fetch else 0,
            "has_h2h": bool(consensus.h2h),
        }
    except MarketLiveFetchError as exc:
        ctx.fetch_error = str(exc)
        logger.info(
            "market_resolution_fetch_failed home=%s away=%s detail=%s",
            home_team,
            away_team,
            str(exc),
        )

    return ctx
