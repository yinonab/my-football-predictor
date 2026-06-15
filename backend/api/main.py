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
from api.schemas import (
    ChampionOddsRow,
    EloUpdateRequest,
    EloUpdateResponse,
    GroupStandingRow,
    GroupTeam,
    GroupsResponse,
    HealthResponse,
    OutcomeExplanations,
    PredictRequest,
    PredictResponse,
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
from core.h2h_adjustment import H2HStore, apply_h2h_adjustment
from core.maher import estimate_xg_pair
from core.math_engine import AdvancedDixonColesEngine
from core.odds_ensemble import OddsClient, blend_1x2
from core.elo_store import load_elo_overrides, save_elo_overrides
from core.team_power import TeamPowerEvaluator
from core.tournament_sim import TournamentSimulator
from data.api_football import ApiFootballClient
from data.database import LiveDataManager, compute_derived_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Football Predictor API",
    description="Dixon-Coles match prediction engine — WC 2026",
    version="1.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_data_manager = LiveDataManager()
_power_evaluator = TeamPowerEvaluator(_data_manager)
_api_client = ApiFootballClient()
_h2h_store = H2HStore()
_odds_client = OddsClient()


def _team_breakdown(team_input: str, *, use_live: bool) -> TeamBreakdown:
    resolved, _ = _data_manager.resolve_team(team_input)
    bd = _power_evaluator.get_team_breakdown(resolved, use_live=use_live)
    group = _data_manager.get_group(resolved)
    return TeamBreakdown(**bd, group=group)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        live_stats_available=_api_client.is_available,
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

    advantage = 0.0 if request.neutral_ground else request.home_advantage

    home_data = _data_manager.get_team_data(home_resolved, use_live=request.use_live_stats)
    away_data = _data_manager.get_team_data(away_resolved, use_live=request.use_live_stats)
    home_xg, away_xg = estimate_xg_pair(
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        global_avg=request.avg_goals,
    )

    engine = AdvancedDixonColesEngine(
        rho=request.rho,
        global_avg=request.avg_goals,
        alpha=request.alpha,
    )
    result = engine.generate_match_prediction(
        home_power,
        away_power,
        advantage,
        top_n=request.top_n,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )

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
        + (f"\n{h2h_note}" if h2h_note else ""),
        h2h_summary=h2h_note,
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
