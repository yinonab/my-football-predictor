"""Phase 4B — Unified match feature layer (skeleton).

Gathers match input data in one structured object before strength/probability
computation. Does not fetch odds or run prediction logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from data.database import FIFA_ELO_2026, LiveDataManager


@dataclass
class MatchFeatures:
    """Everything known about a match before strength and probability steps."""

    # Core identity
    home_team: str
    away_team: str
    resolved_home_team: str
    resolved_away_team: str
    neutral_ground: bool

    # Raw team payloads (copies — safe to inspect without mutating manager state)
    home_team_data: dict[str, Any]
    away_team_data: dict[str, Any]

    # Rating / power inputs
    home_internal_elo: float
    away_internal_elo: float
    home_attack_strength: float
    away_attack_strength: float
    home_defense_strength: float
    away_defense_strength: float
    home_raw_form: float
    away_raw_form: float
    home_fifa_points: float | None = None
    away_fifa_points: float | None = None
    external_rating_gap: float | None = None
    rating_disagreement: float | None = None

    # Context placeholders (populated in later phases)
    h2h_signal: dict[str, Any] | None = None
    context_signal: dict[str, Any] | None = None
    rest_days: dict[str, int | None] | None = None
    weather_signal: dict[str, Any] | None = None
    tournament_stage: str | None = None
    group_context: str | None = None
    must_win_context: str | None = None
    odds_market_signal: dict[str, Any] | None = None

    # Diagnostics
    data_quality_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_debug_dict(self) -> dict[str, Any]:
        """Developer/test helper — full serializable snapshot."""
        return asdict(self)


def build_match_features(
    *,
    home_team: str,
    away_team: str,
    neutral_ground: bool,
    use_live_stats: bool,
    data_manager: LiveDataManager,
) -> MatchFeatures:
    """Build MatchFeatures using the same resolution and data paths as predict()."""
    home_input = home_team.strip()
    away_input = away_team.strip()

    resolved_home, _ = data_manager.resolve_team(home_input)
    resolved_away, _ = data_manager.resolve_team(away_input)

    home_data = dict(
        data_manager.get_team_data(resolved_home, use_live=use_live_stats)
    )
    away_data = dict(
        data_manager.get_team_data(resolved_away, use_live=use_live_stats)
    )

    flags: list[str] = []
    if resolved_home not in data_manager.team_database:
        flags.append(f"unknown_home_team:{resolved_home}")
    if resolved_away not in data_manager.team_database:
        flags.append(f"unknown_away_team:{resolved_away}")
    if int(home_data.get("matches_used", 0)) == 0:
        flags.append(f"limited_history_home:{resolved_home}")
    if int(away_data.get("matches_used", 0)) == 0:
        flags.append(f"limited_history_away:{resolved_away}")

    home_fifa_raw = FIFA_ELO_2026.get(resolved_home)
    away_fifa_raw = FIFA_ELO_2026.get(resolved_away)
    home_fifa = float(home_fifa_raw) if home_fifa_raw is not None else None
    away_fifa = float(away_fifa_raw) if away_fifa_raw is not None else None

    home_elo = float(home_data["elo"])
    away_elo = float(away_data["elo"])

    external_gap: float | None = None
    if home_fifa is not None and away_fifa is not None:
        home_delta = abs(home_elo - home_fifa)
        away_delta = abs(away_elo - away_fifa)
        external_gap = round((home_delta + away_delta) / 2.0, 2)

    group_home = data_manager.get_group(resolved_home)
    group_away = data_manager.get_group(resolved_away)
    group_context: str | None = None
    if group_home and group_away:
        group_context = (
            group_home
            if group_home == group_away
            else f"{group_home}|{group_away}"
        )

    return MatchFeatures(
        home_team=home_input,
        away_team=away_input,
        resolved_home_team=resolved_home,
        resolved_away_team=resolved_away,
        neutral_ground=neutral_ground,
        home_team_data=home_data,
        away_team_data=away_data,
        home_internal_elo=home_elo,
        away_internal_elo=away_elo,
        home_attack_strength=float(home_data.get("attack", 0.5)),
        away_attack_strength=float(away_data.get("attack", 0.5)),
        home_defense_strength=float(home_data.get("defense", 0.5)),
        away_defense_strength=float(away_data.get("defense", 0.5)),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
        home_fifa_points=home_fifa,
        away_fifa_points=away_fifa,
        external_rating_gap=external_gap,
        rating_disagreement=None,
        group_context=group_context,
        data_quality_flags=flags,
        warnings=[],
    )
