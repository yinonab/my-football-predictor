"""Phase 4L — Fixture state model for scheduled / live / completed awareness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FixtureStatus = Literal["scheduled", "live", "completed", "unknown"]
PredictionMode = Literal["pre_match", "live", "historical", "unknown"]
FixtureSource = Literal[
    "api_football",
    "curated_fixture",
    "manual_override",
    "football-data.org",
    "unavailable",
]

# Warning codes (stable API contract)
MATCH_ALREADY_COMPLETED = "MATCH_ALREADY_COMPLETED"
FIXTURE_STATE_UNAVAILABLE = "FIXTURE_STATE_UNAVAILABLE"
EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE = "EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE"
API_FOOTBALL_UNAVAILABLE = "API_FOOTBALL_UNAVAILABLE"
API_FOOTBALL_ACCOUNT_SUSPENDED = "API_FOOTBALL_ACCOUNT_SUSPENDED"
HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO = "HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO"
FOOTBALL_DATA_UNAVAILABLE = "FOOTBALL_DATA_UNAVAILABLE"
FOOTBALL_DATA_RATE_LIMITED = "FOOTBALL_DATA_RATE_LIMITED"
MATCH_IN_PROGRESS = "MATCH_IN_PROGRESS"
FIXTURE_POSTPONED_OR_CANCELLED = "FIXTURE_POSTPONED_OR_CANCELLED"


@dataclass
class FixtureState:
    """Resolved fixture state for a matchup — diagnostics-first; does not block predict."""

    home_team: str
    away_team: str
    fixture_status: FixtureStatus = "unknown"
    prediction_valid: bool = True
    prediction_mode: PredictionMode = "unknown"
    kickoff_time_utc: str | None = None
    actual_home_goals: int | None = None
    actual_away_goals: int | None = None
    actual_score_available: bool = False
    source: FixtureSource = "unavailable"
    source_available: bool = False
    source_error: str | None = None
    venue_name: str | None = None
    venue_city: str | None = None
    venue_country: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_fixture_state_rules(state: FixtureState) -> FixtureState:
    """Apply prediction_valid / prediction_mode / warning rules after resolution."""
    warnings = list(state.warnings)

    if state.fixture_status == "completed":
        state.prediction_valid = False
        state.prediction_mode = "historical"
        if MATCH_ALREADY_COMPLETED not in warnings:
            warnings.append(MATCH_ALREADY_COMPLETED)
        if state.actual_home_goals is not None and state.actual_away_goals is not None:
            state.actual_score_available = True
    elif state.fixture_status == "live":
        state.prediction_valid = True
        state.prediction_mode = "live"
    elif state.fixture_status == "scheduled":
        state.prediction_valid = True
        state.prediction_mode = "pre_match"
    else:
        state.prediction_mode = "unknown"
        if not state.source_available:
            if FIXTURE_STATE_UNAVAILABLE not in warnings:
                warnings.append(FIXTURE_STATE_UNAVAILABLE)

    state.warnings = warnings
    return state
