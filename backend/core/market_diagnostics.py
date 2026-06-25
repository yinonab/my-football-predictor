"""Betting market diagnostics for /api/predict (display + optional blend)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import config
from core.odds_ensemble import (
    MODEL_WEIGHT,
    MARKET_WEIGHT,
    OddsClient,
    OddsLookupResult,
    OddsMarketFetch,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MarketDiagnostics:
    available: bool = False
    status: str = "unavailable"
    primary_source: str | None = None
    fetched_at_utc: str | None = None
    bookmakers: list[dict[str, Any]] = field(default_factory=list)
    consensus_1x2_percent: dict[str, float] | None = None
    blend_mode: str = "diagnostic_only"
    odds_affect_prediction: bool = False
    odds_key_configured: bool = False
    requests_remaining: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "primary_source": self.primary_source,
            "fetched_at_utc": self.fetched_at_utc,
            "bookmakers": self.bookmakers,
            "consensus_1x2_percent": self.consensus_1x2_percent,
            "blend_mode": self.blend_mode,
            "odds_affect_prediction": self.odds_affect_prediction,
            "odds_key_configured": self.odds_key_configured,
            "requests_remaining": self.requests_remaining,
            "notes": list(self.notes),
        }


def _blend_mode_label(*, odds_affect: bool) -> str:
    if odds_affect:
        return "active_blend"
    return "diagnostic_only"


def build_market_diagnostics(
    *,
    home_team: str,
    away_team: str,
    odds_client: OddsClient | None = None,
    fetch: OddsMarketFetch | None = None,
    lookup: OddsLookupResult | None = None,
    odds_affect_prediction: bool | None = None,
) -> MarketDiagnostics:
    """Build market_diagnostics block for API responses."""
    client = odds_client or OddsClient()
    notes: list[str] = []
    odds_affect = (
        config.ODDS_AFFECT_PREDICTION
        if odds_affect_prediction is None
        else odds_affect_prediction
    )
    odds_key_configured = client.is_available
    requests_remaining: int | None = None
    status = "unavailable"

    if lookup is None and fetch is None and client.is_available:
        lookup = client.lookup_match_market(home_team, away_team)
    if lookup is not None:
        odds_key_configured = lookup.odds_key_configured
        requests_remaining = lookup.requests_remaining
        status = lookup.status
        notes.extend(lookup.notes)
        if fetch is None:
            fetch = lookup.fetch

    if not odds_key_configured:
        notes.append("THE_ODDS_API_KEY not configured on server")
        return MarketDiagnostics(
            status="not_configured",
            blend_mode=_blend_mode_label(odds_affect=odds_affect),
            odds_affect_prediction=odds_affect,
            odds_key_configured=False,
            notes=notes,
        )

    if status in ("quota_exceeded", "api_error"):
        return MarketDiagnostics(
            status=status,
            primary_source="the_odds_api",
            blend_mode=_blend_mode_label(odds_affect=odds_affect),
            odds_affect_prediction=odds_affect,
            odds_key_configured=True,
            requests_remaining=requests_remaining,
            notes=notes,
        )

    if fetch is None or not fetch.bookmakers:
        if lookup is None and fetch is not None:
            status = "ok"
        if status == "unavailable":
            status = "no_odds_for_matchup"
        if not any("No betting odds" in n for n in notes):
            notes.append("No betting odds found for this matchup in The Odds API")
        return MarketDiagnostics(
            status=status,
            primary_source="the_odds_api",
            blend_mode=_blend_mode_label(odds_affect=odds_affect),
            odds_affect_prediction=odds_affect,
            odds_key_configured=True,
            requests_remaining=requests_remaining,
            notes=notes,
        )

    bookmakers = [b.to_dict() for b in fetch.bookmakers]
    consensus = fetch.consensus_1x2_percent
    primary_source = "the_odds_api"
    if fetch.sport_key.startswith("oddspapi"):
        primary_source = "oddspapi"

    if odds_affect and consensus:
        notes.append(
            f"Market blend active: model {int(MODEL_WEIGHT * 100)}% / "
            f"market {int(MARKET_WEIGHT * 100)}%"
        )
    else:
        notes.append(
            "Market shown for comparison only — odds blend disabled in request"
        )

    return MarketDiagnostics(
        available=True,
        status="ok",
        primary_source=primary_source,
        fetched_at_utc=utc_now_iso(),
        bookmakers=bookmakers,
        consensus_1x2_percent=consensus,
        blend_mode=_blend_mode_label(odds_affect=odds_affect),
        odds_affect_prediction=odds_affect,
        odds_key_configured=True,
        requests_remaining=requests_remaining,
        notes=notes,
    )
