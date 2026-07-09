"""Normalized multi-market snapshot types (Phase 2 — not wired to predict)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MarketFamily(str, Enum):
    H2H = "h2h"
    TOTALS = "totals"
    SPREADS = "spreads"
    BTTS = "btts"
    ALTERNATE_TOTALS = "alternate_totals"
    ALTERNATE_SPREADS = "alternate_spreads"
    UNKNOWN = "unknown"


# Families parsed in Phase 2 infrastructure.
SUPPORTED_FAMILIES: frozenset[MarketFamily] = frozenset(
    {
        MarketFamily.H2H,
        MarketFamily.TOTALS,
        MarketFamily.SPREADS,
        MarketFamily.BTTS,
        MarketFamily.ALTERNATE_TOTALS,
        MarketFamily.ALTERNATE_SPREADS,
    }
)


def parse_market_family(value: str) -> MarketFamily:
    try:
        return MarketFamily(value)
    except ValueError:
        return MarketFamily.UNKNOWN


@dataclass(frozen=True)
class OutcomeQuote:
    """Single outcome within a bookmaker market line."""

    name: str
    decimal_odds: float
    raw_implied: float
    fair_probability: float


@dataclass(frozen=True)
class BookmakerMarketLine:
    """De-vigged odds for one bookmaker on one market variant."""

    bookmaker_id: str
    bookmaker_name: str
    family: MarketFamily
    provider_market_key: str
    line: float | None
    outcomes: tuple[OutcomeQuote, ...]
    overround: float
    placing: str | None = None
    period: str | None = None


@dataclass
class NormalizedMarketSnapshot:
    """Provider-agnostic market state for one fixture."""

    provider: str
    event_id: str
    home_team: str
    away_team: str
    tournament: str | None = None
    fetched_at_utc: str | None = None
    lines: list[BookmakerMarketLine] = field(default_factory=list)
    providers_seen: tuple[str, ...] = ()

    def families_present(self) -> set[MarketFamily]:
        return {line.family for line in self.lines if line.family != MarketFamily.UNKNOWN}

    def distinct_lines_for(self, family: MarketFamily) -> set[float]:
        out: set[float] = set()
        for line in self.lines:
            if line.family == family and line.line is not None:
                out.add(float(line.line))
        return out

    def bookmaker_count_for(self, family: MarketFamily) -> int:
        books = {
            line.bookmaker_id
            for line in self.lines
            if line.family == family and line.bookmaker_id
        }
        return len(books)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "event_id": self.event_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "tournament": self.tournament,
            "fetched_at_utc": self.fetched_at_utc,
            "providers_seen": list(self.providers_seen),
            "line_count": len(self.lines),
            "families": sorted(f.value for f in self.families_present()),
        }


@dataclass
class MarketConsensus:
    """Cross-bookmaker fair-probability consensus."""

    h2h: dict[str, float] | None = None
    totals_by_line: dict[str, dict[str, float]] = field(default_factory=dict)
    spreads_by_line: dict[str, dict[str, float]] = field(default_factory=dict)
    btts: dict[str, float] | None = None
    bookmaker_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "h2h": self.h2h,
            "totals_by_line": self.totals_by_line,
            "spreads_by_line": self.spreads_by_line,
            "btts": self.btts,
            "bookmaker_counts": self.bookmaker_counts,
        }


@dataclass(frozen=True)
class MarketQualityResult:
    """Readiness band for future market-matrix weighting (not used in predict yet)."""

    score: float
    band: str
    families_present: tuple[str, ...]
    bookmaker_count: int
    provider_count: int
    total_line_count: int
    spread_line_count: int
    has_btts: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "band": self.band,
            "families_present": list(self.families_present),
            "bookmaker_count": self.bookmaker_count,
            "provider_count": self.provider_count,
            "total_line_count": self.total_line_count,
            "spread_line_count": self.spread_line_count,
            "has_btts": self.has_btts,
            "notes": list(self.notes),
        }
