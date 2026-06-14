"""Pydantic request/response models for the prediction API."""

from __future__ import annotations

from pydantic import BaseModel, Field

import config


class HealthResponse(BaseModel):
    status: str
    version: str = "1.6.0"
    live_stats_available: bool = False


class PredictRequest(BaseModel):
    home_team: str
    away_team: str
    neutral_ground: bool = True
    use_live_stats: bool = False
    rho: float = Field(default=config.DEFAULT_RHO, ge=-0.15, le=0.0)
    avg_goals: float = Field(default=config.GLOBAL_XG_AVG, ge=1.0, le=4.0)
    home_advantage: float = Field(default=config.DEFAULT_HOME_ADV, ge=0, le=200)
    alpha: float = Field(default=config.OVERDISPERSION_ALPHA, ge=0.0, le=1.0)
    altitude: int = Field(default=0, ge=0)
    star_absent: bool = False
    away_star_absent: bool = False
    top_n: int = Field(default=10, ge=1, le=15)


class ScoreProbability(BaseModel):
    score: str
    probability: float
    explanation: str = ""


class ScoreCoverage(BaseModel):
    target_percent: float
    achieved_percent: float
    scores: list[str]
    explanation: str = ""


class Probabilities1X2(BaseModel):
    home_win: float
    draw: float
    away_win: float


class OutcomeExplanations(BaseModel):
    home_win: str
    draw: str
    away_win: str


class TeamBreakdown(BaseModel):
    name: str
    power_score: float
    elo: float
    breakdown: str
    group: str | None = None


class PredictResponse(BaseModel):
    home_team: str
    away_team: str
    home_power: float
    away_power: float
    home_breakdown: TeamBreakdown
    away_breakdown: TeamBreakdown
    home_xg: float
    away_xg: float
    probabilities_1x2: Probabilities1X2
    outcome_explanations: OutcomeExplanations
    top_scores: list[ScoreProbability]
    score_coverage: ScoreCoverage
    match_summary: str = ""


class TeamsResponse(BaseModel):
    teams: list[str]


class GroupTeam(BaseModel):
    name: str
    elo: float


class GroupsResponse(BaseModel):
    groups: dict[str, list[GroupTeam]]


class TeamInfoResponse(BaseModel):
    team: str
    group: str | None
    elo: float
    group_teams: list[str]


class EloUpdateRequest(BaseModel):
    home_team: str
    away_team: str
    home_goals: int = Field(ge=0, le=20)
    away_goals: int = Field(ge=0, le=20)
    neutral_ground: bool = True
    k_factor: float = Field(default=40.0, ge=10, le=80)


class EloUpdateResponse(BaseModel):
    home_team: str
    away_team: str
    home_elo_before: float
    away_elo_before: float
    home_elo_after: float
    away_elo_after: float
    home_delta: float
    away_delta: float
    expected_home_win: float


class SimulateGroupRequest(BaseModel):
    group: str = Field(min_length=1, max_length=1)
    iterations: int = Field(default=500, ge=100, le=5000)


class GroupStandingRow(BaseModel):
    group: str
    team: str
    avg_points: float
    top2_probability: float
    win_group_probability: float


class SimulateGroupResponse(BaseModel):
    group: str
    iterations: int
    standings: list[GroupStandingRow]


class ChampionOddsRow(BaseModel):
    team: str
    probability: float


class SimulateChampionRequest(BaseModel):
    iterations: int = Field(default=1000, ge=200, le=10000)


class SimulateChampionResponse(BaseModel):
    iterations: int
    champion_odds: list[ChampionOddsRow]
