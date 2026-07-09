"""Provider routing facade for normalized market snapshots (Phase 2)."""

from __future__ import annotations

from typing import Any

from core.market_consensus import build_market_consensus
from core.market_quality import score_market_quality
from core.market_types import MarketConsensus, MarketQualityResult, NormalizedMarketSnapshot
from core.providers.rapidapi_odds_feed_parser import parse_audit_report as parse_rapidapi_audit
from core.providers.the_odds_api_market_parser import parse_event_payload as parse_odds_api_event


def parse_rapidapi_odds_feed_audit(report: dict[str, Any]) -> NormalizedMarketSnapshot:
    return parse_rapidapi_audit(report)


def parse_the_odds_api_event(
    event: dict[str, Any],
    *,
    home_team: str | None = None,
    away_team: str | None = None,
    swapped: bool = False,
    fetched_at_utc: str | None = None,
) -> NormalizedMarketSnapshot:
    return parse_odds_api_event(
        event,
        home_team=home_team,
        away_team=away_team,
        swapped=swapped,
        fetched_at_utc=fetched_at_utc,
    )


def build_snapshot_pipeline(
    snapshot: NormalizedMarketSnapshot,
) -> tuple[MarketConsensus, MarketQualityResult]:
    """Consensus + quality for an already-normalized snapshot."""
    consensus = build_market_consensus(snapshot)
    quality = score_market_quality(snapshot, consensus)
    return consensus, quality
