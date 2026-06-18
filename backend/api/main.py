"""FastAPI application — HTTP orchestrator with no mathematics."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")
from api.schemas import (
    ChampionOddsRow,
    EloUpdateRequest,
    EloUpdateResponse,
    GlobalRatingDebugResponse,
    GlobalRatingDiagnosticsResponse,
    GlobalRatingGapsResponse,
    GlobalRatingTeamDiagnosticsResponse,
    PowerComponentDiagnosticsResponse,
    PowerComponentGapBreakdownResponse,
    PowerComponentTeamResponse,
    PowerShadowCalibrationResponse,
    WarningDetailResponse,
    GroupStandingRow,
    GroupTeam,
    GroupsResponse,
    HealthResponse,
    OutcomeExplanations,
    MatchContextResponse,
    ModelDiagnosticsResponse,
    PredictRequest,
    PredictResponse,
    RefreshHistoryResponse,
    Probabilities1X2,
    ScoreCoverage,
    ScoreProbability,
    SimulateChampionRequest,
    SimulateChampionResponse,
    SimulateGroupRequest,
    SimulateGroupResponse,
    TeamBreakdown,
    TeamInfoResponse,
    TeamsResponse,
)
from core.elo_updater import update_elo_pair
from core.explanations import (
    build_match_summary,
    explain_exact_score,
    explain_outcome_1x2,
    explain_score_coverage,
)
from core.h2h_adjustment import H2HStore, apply_h2h_adjustment, load_h2h_index
from core.match_store import append_live_match, load_live_matches
from core.blowout import apply_blowout_adjustment
from core.global_ratings import (
    apply_experimental_power_nudge,
    build_match_diagnostics,
)
from core.context_adjustments import apply_xg_context_delta, compute_context_adjustments
from core.match_context import MatchContextGatherer
from core.maher import blend_maher_with_power, floor_underdog_xg, mismatch_gap, scale_rho_for_gap
from core.opponent_maher import build_opponent_index, estimate_xg_opponent_aware
from core.team_ratings import build_all_matches, build_and_save_ratings
from core.math_engine import AdvancedDixonColesEngine
from core.odds_ensemble import OddsClient, blend_1x2
from core.cloud_persist import is_configured as cloud_persist_configured, pull_all as cloud_pull_all
from core.elo_store import load_elo_overrides, save_elo_overrides
from core.team_power import TeamPowerEvaluator
from core.tournament_sim import TournamentSimulator
from data.api_football import ApiFootballClient
from data.database import FIFA_ELO_2026, LiveDataManager, compute_derived_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Football Predictor API",
    description="Dixon-Coles match prediction engine — WC 2026",
    version="2.1.3",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if cloud_persist_configured():
    cloud_pull_all()

_data_manager = LiveDataManager()
_power_evaluator = TeamPowerEvaluator(_data_manager)
_api_client = ApiFootballClient()
_h2h_store = H2HStore()
_odds_client = OddsClient()
_context_gatherer = MatchContextGatherer(_api_client)

_opponent_index = build_opponent_index(
    build_all_matches(),
    set(FIFA_ELO_2026.keys()),
)


def _refresh_model_data() -> None:
    """Reload ratings, H2H and per-opponent Maher index."""
    global _opponent_index
    build_and_save_ratings()
    _data_manager.reload_history()
    _h2h_store._index = load_h2h_index()
    _opponent_index = build_opponent_index(
        build_all_matches(),
        set(FIFA_ELO_2026.keys()),
    )


def _team_breakdown(team_input: str, *, use_live: bool) -> TeamBreakdown:
    resolved, _ = _data_manager.resolve_team(team_input)
    bd = _power_evaluator.get_team_breakdown(resolved, use_live=use_live)
    group = _data_manager.get_group(resolved)
    return TeamBreakdown(**bd, group=group)


def _global_rating_response(
    diag,
) -> GlobalRatingDiagnosticsResponse:
    power_diag = None
    if diag.power_component_diagnostics is not None:
        pcd = diag.power_component_diagnostics
        power_diag = PowerComponentDiagnosticsResponse(
            home=PowerComponentTeamResponse(**pcd["home"]),
            away=PowerComponentTeamResponse(**pcd["away"]),
            gap_breakdown=PowerComponentGapBreakdownResponse(**pcd["gap_breakdown"]),
        )
    return GlobalRatingDiagnosticsResponse(
        home=GlobalRatingTeamDiagnosticsResponse(**diag.home.to_dict()),
        away=GlobalRatingTeamDiagnosticsResponse(**diag.away.to_dict()),
        gaps=GlobalRatingGapsResponse(**diag.gaps.to_dict()),
        warnings=diag.warnings,
        warning_details=[
            WarningDetailResponse(**w.to_dict()) for w in diag.warning_details
        ],
        experimental_adjustment_applied=diag.experimental_adjustment_applied,
        power_component_diagnostics=power_diag,
        power_shadow_calibration=(
            PowerShadowCalibrationResponse(**diag.power_shadow_calibration)
            if diag.power_shadow_calibration is not None
            else None
        ),
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        live_stats_available=_api_client.is_available,
        odds_available=_odds_client.is_available,
        cloud_persist_available=cloud_persist_configured(),
    )


@app.get("/api/teams", response_model=TeamsResponse)
def list_teams() -> TeamsResponse:
    return TeamsResponse(teams=_data_manager.list_teams())


@app.get("/api/groups", response_model=GroupsResponse)
def list_groups() -> GroupsResponse:
    raw = _data_manager.list_groups()
    groups = {
        letter: [GroupTeam(**row) for row in rows]
        for letter, rows in raw.items()
    }
    return GroupsResponse(groups=groups)


@app.get("/api/teams/info", response_model=TeamInfoResponse)
def team_info(name: str) -> TeamInfoResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="יש להזין שם נבחרת")
    info = _data_manager.get_group_info(name.strip())
    return TeamInfoResponse(**info)


@app.post("/api/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    if request.home_team.strip() == request.away_team.strip():
        raise HTTPException(status_code=400, detail="יש לבחור שתי נבחרות שונות")

    if not request.home_team.strip() or not request.away_team.strip():
        raise HTTPException(status_code=400, detail="יש להזין שם לשתי הנבחרות")

    home_resolved, _ = _data_manager.resolve_team(request.home_team)
    away_resolved, _ = _data_manager.resolve_team(request.away_team)

    home_power = _power_evaluator.calculate_composite_power(
        home_resolved, use_live=request.use_live_stats
    )
    away_power = _power_evaluator.calculate_composite_power(
        away_resolved, use_live=request.use_live_stats
    )

    home_power = _power_evaluator.apply_environmental_modifiers(
        home_power,
        altitude=request.altitude,
        star_absent=request.star_absent,
    )
    away_power = _power_evaluator.apply_environmental_modifiers(
        away_power,
        altitude=request.altitude,
        star_absent=request.away_star_absent,
    )

    h2h_summary = _h2h_store.get(home_resolved, away_resolved)
    home_power, away_power, h2h_note = apply_h2h_adjustment(
        home_power,
        away_power,
        h2h_summary,
    )

    ctx_info = _context_gatherer.gather(
        home_resolved,
        away_resolved,
        match_date=request.match_date,
        venue_city=request.venue_city,
        enabled=request.use_match_context,
    )
    ctx_adj = compute_context_adjustments(
        home_rest_days=ctx_info.home_rest_days,
        away_rest_days=ctx_info.away_rest_days,
        away_travel_km=ctx_info.away_travel_km,
        home_travel_km=ctx_info.home_travel_km,
        rain_mm=ctx_info.weather_rain_mm,
        temp_c=ctx_info.weather_temp_c,
        stage=ctx_info.stage,
    )
    if request.use_match_context:
        home_power *= ctx_adj.home_power_mult
        away_power *= ctx_adj.away_power_mult

    ctx_notes = list(ctx_info.notes or []) + list(ctx_adj.notes)
    match_context = MatchContextResponse(
        enabled=request.use_match_context,
        data_source=ctx_info.data_source,
        home_rest_days=ctx_info.home_rest_days,
        away_rest_days=ctx_info.away_rest_days,
        home_last_city=ctx_info.home_last_city,
        away_last_city=ctx_info.away_last_city,
        venue_city=ctx_info.venue_city,
        match_date=ctx_info.match_date,
        stage=ctx_info.stage,
        away_travel_km=ctx_info.away_travel_km,
        home_travel_km=ctx_info.home_travel_km,
        weather_summary=ctx_info.weather_summary,
        weather_temp_c=ctx_info.weather_temp_c,
        weather_rain_mm=ctx_info.weather_rain_mm,
        home_power_mult=round(ctx_adj.home_power_mult, 3),
        away_power_mult=round(ctx_adj.away_power_mult, 3),
        xg_total_delta=round(ctx_adj.xg_total_delta, 3),
        notes=ctx_notes,
    )

    advantage = 0.0 if request.neutral_ground else request.home_advantage

    home_data = _data_manager.get_team_data(home_resolved, use_live=request.use_live_stats)
    away_data = _data_manager.get_team_data(away_resolved, use_live=request.use_live_stats)
    home_elo = float(home_data["elo"])
    away_elo = float(away_data["elo"])
    home_raw_form = float(home_data.get("form", 0.5))
    away_raw_form = float(away_data.get("form", 0.5))

    from core.active_model_activation import (
        build_model_diagnostics,
        try_apply_active_candidate_powers,
    )

    active_power = try_apply_active_candidate_powers(
        home_resolved,
        away_resolved,
        baseline_home_power=home_power,
        baseline_away_power=away_power,
        baseline_home_elo=home_elo,
        baseline_away_elo=away_elo,
        data_manager=_data_manager,
    )
    model_diag_payload = build_model_diagnostics(
        activation_applied=active_power.applied,
        fallback_reasons=active_power.fallback_reasons,
    )
    if active_power.applied:
        home_power = active_power.home_power
        away_power = active_power.away_power
        home_elo = active_power.home_elo
        away_elo = active_power.away_elo

    experimental_global_diag = None
    if config.GLOBAL_RATINGS_ENABLED and config.GLOBAL_RATINGS_AFFECT_PREDICTION:
        pre_diag = build_match_diagnostics(
            home_resolved,
            away_resolved,
            home_power=home_power,
            away_power=away_power,
            home_internal_elo=home_elo,
            away_internal_elo=away_elo,
            home_raw_form=home_raw_form,
            away_raw_form=away_raw_form,
        )
        home_power, away_power, experimental_global_diag = apply_experimental_power_nudge(
            home_power, away_power, pre_diag
        )

    home_xg, away_xg, maher_note = estimate_xg_opponent_aware(
        home_resolved,
        away_resolved,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        _opponent_index,
        global_avg=request.avg_goals,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        global_avg=request.avg_goals,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    if request.use_match_context and abs(ctx_adj.xg_total_delta) > 1e-6:
        home_xg, away_xg = apply_xg_context_delta(
            home_xg,
            away_xg,
            ctx_adj.xg_total_delta,
        )
    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        base_alpha=request.alpha,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg

    gap_for_rho = mismatch_gap(
        home_power,
        away_power,
        advantage,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(request.rho, gap_for_rho),
        global_avg=request.avg_goals,
        alpha=blowout.alpha,
    )
    result = engine.generate_match_prediction(
        home_power,
        away_power,
        advantage,
        top_n=request.top_n,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )

    model_probs_raw = dict(result["probabilities_1x2"])

    market_odds = _odds_client.fetch_match_odds(
        home_name := request.home_team.strip(),
        away_name := request.away_team.strip(),
    )
    probs = blend_1x2(result["probabilities_1x2"], market_odds)
    result["probabilities_1x2"] = probs

    logger.info(
        "Prediction: %s vs %s | 1X2: %s | Maher xG %.2f-%.2f",
        home_name,
        away_name,
        probs,
        result["home_xg"],
        result["away_xg"],
    )

    coverage = result["score_coverage"]

    top_with_expl = []
    for rank, item in enumerate(result["top_scores"], start=1):
        top_with_expl.append(
            ScoreProbability(
                score=item["score"],
                probability=item["probability"],
                explanation=explain_exact_score(
                    item["score"],
                    item["probability"],
                    home_xg=result["home_xg"],
                    away_xg=result["away_xg"],
                    home_team=home_name,
                    away_team=away_name,
                    rank=rank,
                ),
            )
        )

    coverage_model = ScoreCoverage(
        **coverage,
        explanation=explain_score_coverage(
            coverage["scores"], coverage["achieved_percent"]
        ),
    )

    return PredictResponse(
        home_team=home_name,
        away_team=away_name,
        home_power=round(home_power, 2),
        away_power=round(away_power, 2),
        home_breakdown=_team_breakdown(home_name, use_live=request.use_live_stats),
        away_breakdown=_team_breakdown(away_name, use_live=request.use_live_stats),
        home_xg=result["home_xg"],
        away_xg=result["away_xg"],
        probabilities_1x2=Probabilities1X2(**probs),
        outcome_explanations=OutcomeExplanations(
            home_win=explain_outcome_1x2(
                "home",
                probs["home_win"],
                home_power=home_power,
                away_power=away_power,
                home_xg=result["home_xg"],
                away_xg=result["away_xg"],
                home_team=home_name,
                away_team=away_name,
            ),
            draw=explain_outcome_1x2(
                "draw",
                probs["draw"],
                home_power=home_power,
                away_power=away_power,
                home_xg=result["home_xg"],
                away_xg=result["away_xg"],
                home_team=home_name,
                away_team=away_name,
            ),
            away_win=explain_outcome_1x2(
                "away",
                probs["away_win"],
                home_power=home_power,
                away_power=away_power,
                home_xg=result["home_xg"],
                away_xg=result["away_xg"],
                home_team=home_name,
                away_team=away_name,
            ),
        ),
        top_scores=top_with_expl,
        score_coverage=coverage_model,
        match_summary=build_match_summary(
            home_team=home_name,
            away_team=away_name,
            home_power=home_power,
            away_power=away_power,
            home_xg=result["home_xg"],
            away_xg=result["away_xg"],
            probs=probs,
        )
        + (f"\n{h2h_note}" if h2h_note else "")
        + (f"\n{maher_note}" if maher_note else "")
        + (f"\n{blowout.note}" if blowout.active else "")
        + (
            "\nהקשר משחק: " + "; ".join(ctx_notes)
            if request.use_match_context and ctx_notes
            else ""
        ),
        h2h_summary=h2h_note,
        match_context=match_context,
        global_rating_diagnostics=_build_global_diagnostics_for_response(
            home_resolved=home_resolved,
            away_resolved=away_resolved,
            home_power=home_power,
            away_power=away_power,
            home_elo=home_elo,
            away_elo=away_elo,
            home_raw_form=home_raw_form,
            away_raw_form=away_raw_form,
            model_probs_raw=model_probs_raw,
            market_odds=market_odds,
            experimental_global_diag=experimental_global_diag,
            h2h_summary=h2h_summary,
            home_context_mult=ctx_adj.home_power_mult if request.use_match_context else 1.0,
            away_context_mult=ctx_adj.away_power_mult if request.use_match_context else 1.0,
            home_altitude=request.altitude,
            away_altitude=request.altitude,
            home_star_absent=request.star_absent,
            away_star_absent=request.away_star_absent,
            use_live=request.use_live_stats,
        ),
        model_diagnostics=ModelDiagnosticsResponse(**model_diag_payload.to_dict()),
    )


def _build_global_diagnostics_for_response(
    *,
    home_resolved: str,
    away_resolved: str,
    home_power: float,
    away_power: float,
    home_elo: float,
    away_elo: float,
    home_raw_form: float,
    away_raw_form: float,
    model_probs_raw: dict[str, float],
    market_odds: dict[str, float] | None,
    experimental_global_diag,
    h2h_summary=None,
    home_context_mult: float = 1.0,
    away_context_mult: float = 1.0,
    home_altitude: int = 0,
    away_altitude: int = 0,
    home_star_absent: bool = False,
    away_star_absent: bool = False,
    use_live: bool = False,
) -> GlobalRatingDiagnosticsResponse | None:
    if not config.GLOBAL_RATINGS_ENABLED:
        return None
    diag = build_match_diagnostics(
        home_resolved,
        away_resolved,
        home_power=home_power,
        away_power=away_power,
        home_internal_elo=home_elo,
        away_internal_elo=away_elo,
        home_raw_form=home_raw_form,
        away_raw_form=away_raw_form,
        model_probs=model_probs_raw,
        market_probs=market_odds,
    )
    if config.POWER_COMPONENT_DIAGNOSTICS_ENABLED:
        from core.power_component_audit import (
            build_power_component_warnings,
            build_power_path_diagnostics,
        )

        power_path = build_power_path_diagnostics(
            home_resolved,
            away_resolved,
            _power_evaluator,
            h2h_summary=h2h_summary,
            home_context_mult=home_context_mult,
            away_context_mult=away_context_mult,
            home_altitude=home_altitude,
            away_altitude=away_altitude,
            home_star_absent=home_star_absent,
            away_star_absent=away_star_absent,
            use_live=use_live,
        )
        diag.power_component_diagnostics = power_path
        power_warnings = build_power_component_warnings(
            gap_breakdown=power_path["gap_breakdown"],
            internal_elo_gap=diag.gaps.internal_elo_gap,
            world_elo_gap=diag.gaps.world_elo_gap,
            home_team_diag=power_path["home"],
            away_team_diag=power_path["away"],
        )
        for pw in power_warnings:
            if pw.code not in diag.warnings:
                diag.warnings.append(pw.code)
            diag.warning_details.append(pw)
    if config.POWER_SHADOW_CALIBRATION_ENABLED:
        from core.power_shadow_calibration import build_matchup_shadow_comparison

        diag.power_shadow_calibration = build_matchup_shadow_comparison(
            home_resolved,
            away_resolved,
            data_manager=_data_manager,
            opponent_index=_opponent_index,
            include_xg=True,
        )
        from core.power_effective_elo import build_effective_elo_anchor_matchup

        diag.power_shadow_calibration["effective_elo_anchor"] = (
            build_effective_elo_anchor_matchup(
                home_resolved,
                away_resolved,
                data_manager=_data_manager,
                opponent_index=_opponent_index,
                api_mode=True,
            )
        )
        from core.model_activation_gate import activation_diagnostic_fields

        diag.power_shadow_calibration.update(activation_diagnostic_fields())
    if experimental_global_diag and experimental_global_diag.experimental_adjustment_applied:
        merged_warnings = list(experimental_global_diag.warnings)
        for w in diag.warnings:
            if w not in merged_warnings:
                merged_warnings.append(w)
        diag.warnings = merged_warnings
        diag.experimental_adjustment_applied = True
    return _global_rating_response(diag)


@app.get("/api/debug/global-ratings", response_model=GlobalRatingDebugResponse)
def debug_global_ratings(home_team: str, away_team: str) -> GlobalRatingDebugResponse:
    """Rating-stack diagnostics only — no Dixon-Coles / xG engine."""
    if not home_team.strip() or not away_team.strip():
        raise HTTPException(status_code=400, detail="יש להזין שם לשתי הנבחרות")

    home_resolved, home_data = _data_manager.resolve_team(home_team.strip())
    away_resolved, away_data = _data_manager.resolve_team(away_team.strip())

    home_power = _power_evaluator.calculate_composite_power(home_resolved)
    away_power = _power_evaluator.calculate_composite_power(away_resolved)

    diag = build_match_diagnostics(
        home_resolved,
        away_resolved,
        home_power=home_power,
        away_power=away_power,
        home_internal_elo=float(home_data["elo"]),
        away_internal_elo=float(away_data["elo"]),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
    )

    return GlobalRatingDebugResponse(
        home_team=home_resolved,
        away_team=away_resolved,
        global_rating_diagnostics=_global_rating_response(diag),
    )


@app.post("/api/elo/update", response_model=EloUpdateResponse)
def elo_update(request: EloUpdateRequest) -> EloUpdateResponse:
    home_resolved, home_data = _data_manager.resolve_team(request.home_team)
    away_resolved, away_data = _data_manager.resolve_team(request.away_team)

    home_elo = home_data["elo"]
    away_elo = away_data["elo"]
    home_adv = 0.0 if request.neutral_ground else config.DEFAULT_HOME_ADV

    new_home, new_away, meta = update_elo_pair(
        home_elo,
        away_elo,
        request.home_goals,
        request.away_goals,
        k=request.k_factor,
        home_advantage=home_adv,
    )

    if home_resolved in _data_manager.team_database:
        _data_manager.team_database[home_resolved]["elo"] = new_home
    if away_resolved in _data_manager.team_database:
        _data_manager.team_database[away_resolved]["elo"] = new_away

    overrides = load_elo_overrides()
    overrides[home_resolved] = new_home
    overrides[away_resolved] = new_away
    save_elo_overrides(overrides)

    match_recorded = False
    ratings_rebuilt = False
    if request.record_match:
        append_live_match(
            home_key=home_resolved,
            away_key=away_resolved,
            home_goals=request.home_goals,
            away_goals=request.away_goals,
            neutral=request.neutral_ground,
        )
        match_recorded = True
        _refresh_model_data()
        ratings_rebuilt = True

    logger.info(
        "Elo update: %s (%.0f→%.0f) vs %s (%.0f→%.0f)",
        home_resolved,
        home_elo,
        new_home,
        away_resolved,
        away_elo,
        new_away,
    )

    return EloUpdateResponse(
        home_team=home_resolved,
        away_team=away_resolved,
        home_elo_before=home_elo,
        away_elo_before=away_elo,
        home_elo_after=new_home,
        away_elo_after=new_away,
        home_delta=meta["home_delta"],
        away_delta=meta["away_delta"],
        expected_home_win=meta["expected_home"],
        match_recorded=match_recorded,
        ratings_rebuilt=ratings_rebuilt,
        live_match_count=len(load_live_matches()),
    )


@app.post("/api/admin/refresh-history", response_model=RefreshHistoryResponse)
def refresh_history() -> RefreshHistoryResponse:
    """Fetch NT history from API-Football when API_FOOTBALL_KEY is set."""
    if not _api_client.is_available:
        raise HTTPException(
            status_code=400,
            detail="API_FOOTBALL_KEY לא מוגדר — הוסף מפתח ב-Render או ב-backend/.env",
        )

    try:
        from run_fetch_quota_safe import fetch_quota_safe
        from run_fetch_nt_history import save_fetched_matches

        matches, api_calls = fetch_quota_safe(budget=80)
        save_fetched_matches(matches)
        _refresh_model_data()
    except Exception as exc:
        logger.exception("History refresh failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_matches = build_all_matches()
    return RefreshHistoryResponse(
        fetched_matches=len(matches),
        total_matches=len(all_matches),
        teams_rated=len(_data_manager.list_teams()),
        h2h_pairs=_h2h_store.pair_count(),
        api_calls_used=api_calls,
    )


@app.post("/api/simulate/group", response_model=SimulateGroupResponse)
def simulate_group(request: SimulateGroupRequest) -> SimulateGroupResponse:
    letter = request.group.upper()
    groups = _data_manager.list_groups()
    if letter not in groups:
        raise HTTPException(status_code=404, detail=f"בית {letter} לא קיים")

    sim = TournamentSimulator(_data_manager)
    standings = sim.simulate_group(letter, iterations=request.iterations)
    return SimulateGroupResponse(
        group=letter,
        iterations=request.iterations,
        standings=[GroupStandingRow(**s.__dict__) for s in standings],
    )


@app.post("/api/simulate/champion", response_model=SimulateChampionResponse)
def simulate_champion(request: SimulateChampionRequest) -> SimulateChampionResponse:
    sim = TournamentSimulator(_data_manager)
    odds = sim.simulate_champion(iterations=request.iterations)
    return SimulateChampionResponse(
        iterations=request.iterations,
        champion_odds=[ChampionOddsRow(**c.__dict__) for c in odds],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
