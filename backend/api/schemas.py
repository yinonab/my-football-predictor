"""Pydantic request/response models for the prediction API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import config


class HealthResponse(BaseModel):
    status: str
    version: str = "2.1.3"
    live_stats_available: bool = False
    odds_available: bool = False
    cloud_persist_available: bool = False
    # Phase 4A — operational model visibility (config-only; no predict() call)
    app_version: str = "2.1.3"
    active_model_version: str = config.BASELINE_MODEL_VERSION
    baseline_model_version: str = config.BASELINE_MODEL_VERSION
    activation_enabled: bool = False
    active_candidate: str | None = None
    power_candidate_affects_prediction: bool = False
    odds_affect_prediction: bool = config.ODDS_AFFECT_PREDICTION
    probability_calibration_enabled: bool = config.PROBABILITY_CALIBRATION_ENABLED


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
    top_n: int = Field(default=3, ge=1, le=15)
    use_match_context: bool = True
    match_date: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD for weather/rest reference",
    )
    venue_city: str | None = Field(
        default=None,
        description="Host city for travel/weather (e.g. Miami)",
    )


class MatchContextResponse(BaseModel):
    enabled: bool = True
    data_source: str = "offline"
    home_rest_days: int | None = None
    away_rest_days: int | None = None
    home_last_city: str | None = None
    away_last_city: str | None = None
    venue_city: str | None = None
    match_date: str | None = None
    stage: str | None = None
    away_travel_km: float | None = None
    home_travel_km: float | None = None
    weather_summary: str | None = None
    weather_temp_c: float | None = None
    weather_rain_mm: float | None = None
    home_power_mult: float = 1.0
    away_power_mult: float = 1.0
    xg_total_delta: float = 0.0
    notes: list[str] = Field(default_factory=list)


class VenueDiagnosticsResponse(BaseModel):
    name: str | None = None
    city: str | None = None
    country: str | None = None
    altitude_meters: int | None = None


class ActualScoreResponse(BaseModel):
    home: int
    away: int


class MatchContextDiagnosticsResponse(BaseModel):
    """Phase 4L — fixture state, host/venue visibility (additive; does not alter prediction math)."""

    fixture_status: str = "unknown"
    prediction_valid: bool = True
    prediction_mode: str = "unknown"
    actual_score: ActualScoreResponse | None = None
    kickoff_time_utc: str | None = None
    fixture_source: str = "unavailable"
    fixture_source_available: bool = False
    venue: VenueDiagnosticsResponse = Field(default_factory=VenueDiagnosticsResponse)
    neutral_ground_requested: bool = True
    host_country_match: bool = False
    host_advantage_candidate_team: str | None = None
    host_advantage_applied: bool = False
    home_advantage_value: float = 0.0
    venue_context_available: bool = False
    altitude_applied: bool = False
    warnings: list[str] = Field(default_factory=list)


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


class GlobalRatingGapsResponse(BaseModel):
    internal_elo_gap: float
    world_elo_gap: float
    power_gap: float
    global_strength_gap: float
    power_vs_global_gap_delta: float
    global_strength_gap_raw: float
    global_strength_gap_label: str
    power_compression_ratio: float
    world_power_compression_ratio: float
    power_vs_elo_gap_delta: float
    power_vs_world_gap_delta: float


class WarningDetailResponse(BaseModel):
    code: str
    severity: str
    message: str
    metrics: dict[str, float | int | str | list[str] | None] = Field(default_factory=dict)


class GlobalRatingTeamDiagnosticsResponse(BaseModel):
    team: str
    internal_elo: float
    world_elo: float
    fifa_points: float | None = None
    fifa_rank: int | None = None
    raw_form: float
    opponent_adjusted_form: float
    rating_confidence: float
    global_strength_score: float
    internal_external_elo_delta: float
    avg_opponent_elo: float | None = None
    opponent_history_matches: int = 0
    external_source: str = "fallback"


class PowerComponentGapBreakdownResponse(BaseModel):
    total_power_gap: float
    elo_component_gap: float
    form_component_gap: float
    attack_component_gap: float
    defense_component_gap: float
    context_component_gap: float
    h2h_component_gap: float
    modifier_component_gap: float
    top_compression_driver: str


class PowerComponentTeamResponse(BaseModel):
    team: str
    total_power: float
    internal_elo: float
    components: dict[str, float | None]
    raw_inputs: dict[str, float | int | None]
    weights: dict[str, float]


class PowerComponentDiagnosticsResponse(BaseModel):
    home: PowerComponentTeamResponse
    away: PowerComponentTeamResponse
    gap_breakdown: PowerComponentGapBreakdownResponse


class PowerShadowCalibrationResponse(BaseModel):
    enabled: bool = True
    affects_prediction: bool = False
    variants: dict[str, Any] = Field(default_factory=dict)
    matchup_comparison: dict[str, Any] = Field(default_factory=dict)
    effective_elo_anchor: dict[str, Any] | None = None
    activation_candidate_status: str = "not_evaluated"
    activation_overall_status: str = "not_evaluated"
    temporal_data_status: str = "not_evaluated"
    model_candidate_status: str = "not_evaluated"


class GlobalRatingDiagnosticsResponse(BaseModel):
    home: GlobalRatingTeamDiagnosticsResponse
    away: GlobalRatingTeamDiagnosticsResponse
    gaps: GlobalRatingGapsResponse
    warnings: list[str] = Field(default_factory=list)
    warning_details: list[WarningDetailResponse] = Field(default_factory=list)
    experimental_adjustment_applied: bool = False
    power_component_diagnostics: PowerComponentDiagnosticsResponse | None = None
    power_shadow_calibration: PowerShadowCalibrationResponse | None = None


class ModelDiagnosticsResponse(BaseModel):
    model_version: str = config.BASELINE_MODEL_VERSION
    baseline_model_version: str = config.BASELINE_MODEL_VERSION
    activation_enabled: bool = False
    active_candidate: str | None = None
    active_external_rating_mode: str | None = None
    active_external_rating_strategy: str | None = None
    fallback_to_baseline: bool = False
    fallback_reasons: list[str] = Field(default_factory=list)
    candidate_metrics_source: str = "phase2j_walk_forward"
    candidate_gate_status: str = "MODEL_ACTIVATION_PASS"
    # Phase 4C — explicit strength layer (additive, optional for clients)
    baseline_home_power: float | None = None
    baseline_away_power: float | None = None
    active_home_power: float | None = None
    active_away_power: float | None = None
    final_home_power: float | None = None
    final_away_power: float | None = None
    gap_delta: float | None = None


class ScorelineCandidateResponse(BaseModel):
    home_goals: int
    away_goals: int
    probability: float
    outcome: str


class ScoreGroupsResponse(BaseModel):
    home_win: list[ScorelineCandidateResponse] = Field(default_factory=list)
    draw: list[ScorelineCandidateResponse] = Field(default_factory=list)
    away_win: list[ScorelineCandidateResponse] = Field(default_factory=list)


class ScorelineDecisionResponse(BaseModel):
    """Phase 4M — user-facing primary exact score (additive; top_scores unchanged)."""

    favorite_outcome: str
    favorite_outcome_probability: float
    second_outcome: str
    second_outcome_probability: float
    outcome_margin: float
    confidence_label: str
    primary_predicted_score: ScorelineCandidateResponse | None = None
    primary_score_reason: str = ""
    top_exact_score_overall: ScorelineCandidateResponse | None = None
    top_exact_score_differs_from_primary: bool = False
    favorite_outcome_top_scores: list[ScorelineCandidateResponse] = Field(default_factory=list)
    score_groups: ScoreGroupsResponse = Field(default_factory=ScoreGroupsResponse)
    warnings: list[str] = Field(default_factory=list)


class ProbabilityCoherenceResponse(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    advisory_reasons: list[str] = Field(default_factory=list)


class ProbabilityDiagnosticsResponse(BaseModel):
    probability_sum: float
    probability_sum_valid: bool
    odds_available: bool = False
    odds_affect_prediction: bool = False
    odds_blend_applied: bool = False
    market_probabilities_1x2: dict[str, float] | None = None
    raw_probabilities_1x2: dict[str, float]
    final_probabilities_1x2: dict[str, float]
    favorite_from_final_1x2: str | None = None
    favorite_from_xg: str | None = None
    favorite_from_top_score: str | None = None
    coherence_warnings: list[str] = Field(default_factory=list)
    odds_source: str | None = None
    odds_blend_weight_model: float | None = None
    odds_blend_weight_market: float | None = None
    score_matrix_source: str = "dixon_coles"
    calibration_enabled: bool = False
    calibration_method: str = "temperature"
    calibration_temperature: float = 1.35
    calibration_applied: bool = False
    calibration_blocked_reason: str | None = None


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
    h2h_summary: str = ""
    match_context: MatchContextResponse | None = None
    global_rating_diagnostics: GlobalRatingDiagnosticsResponse | None = None
    model_diagnostics: ModelDiagnosticsResponse | None = None
    probability_diagnostics: ProbabilityDiagnosticsResponse | None = None
    probability_coherence: ProbabilityCoherenceResponse | None = None
    match_context_diagnostics: MatchContextDiagnosticsResponse | None = None
    scoreline_decision: ScorelineDecisionResponse | None = None


class GlobalRatingDebugResponse(BaseModel):
    home_team: str
    away_team: str
    global_rating_diagnostics: GlobalRatingDiagnosticsResponse


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
    record_match: bool = True


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
    match_recorded: bool = False
    ratings_rebuilt: bool = False
    live_match_count: int = 0


class RefreshHistoryResponse(BaseModel):
    fetched_matches: int
    total_matches: int
    teams_rated: int
    h2h_pairs: int
    api_calls_used: int = 0


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
