"""Market-primary prediction — separate interpreted mode from model primary and market influence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

import config
from core.market_event_map import normalize_team_for_event_map
from core.market_matrix_shadow import (
    _normalize_matrix,
    _parse_score,
)
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW
from core.market_types import MarketConsensus, MarketQualityResult

if TYPE_CHECKING:
    from core.market_resolution import MarketResolutionContext

OutcomeKey = Literal["home_win", "draw", "away_win"]
GoalTrend = Literal["under_2_5", "over_2_5", "neutral", "unavailable"]
BttsSignal = Literal["yes", "no", "neutral", "unavailable"]
SpreadSignal = Literal[
    "slight_home_favorite",
    "clear_home_favorite",
    "strong_home_favorite",
    "slight_away_favorite",
    "clear_away_favorite",
    "strong_away_favorite",
    "neutral",
    "unavailable",
]

_BAND_WEIGHTS: dict[str, tuple[int, int]] = {
    BAND_GREEN: (70, 30),
    BAND_YELLOW: (45, 55),
}

_EDGE_BALANCED_PP = 4.0
_EDGE_SLIGHT_PP = 4.0
_EDGE_CLEAR_PP = 8.0
_EDGE_STRONG_PP = 15.0
_FAVORITE_OVERRIDE_EDGE_PP = 6.0
_FAVORITE_OVERRIDE_GAP_PP = 5.0
_FAVORITE_OVERRIDE_RATIO = 0.65
_GOAL_TREND_EDGE_PP = 4.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketPrimaryPredictionResult:
    applied: bool
    payload: dict[str, Any] | None = None


def _outcome_for_score(h: int, a: int) -> OutcomeKey:
    if h > a:
        return "home_win"
    if h < a:
        return "away_win"
    return "draw"


def _rank_h2h(h2h: Mapping[str, float]) -> tuple[OutcomeKey, float, OutcomeKey, float, float]:
    ranked = sorted(
        (
            ("home_win", float(h2h.get("home", h2h.get("home_win", 0)))),
            ("draw", float(h2h.get("draw", 0))),
            ("away_win", float(h2h.get("away", h2h.get("away_win", 0)))),
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    fav, fav_p = ranked[0]
    second, second_p = ranked[1]
    return fav, fav_p, second, second_p, fav_p - second_p


def _rank_outcome(probs: Mapping[str, float]) -> tuple[OutcomeKey, float, OutcomeKey, float, float]:
    return _rank_h2h(
        {
            "home": probs.get("home_win", 0),
            "draw": probs.get("draw", 0),
            "away": probs.get("away_win", 0),
        }
    )


def _market_h2h_triplet(consensus: MarketConsensus) -> dict[str, float] | None:
    h2h = consensus.h2h
    if not h2h:
        return None
    return {
        "home": round(float(h2h.get("home", 0)), 2),
        "draw": round(float(h2h.get("draw", 0)), 2),
        "away": round(float(h2h.get("away", 0)), 2),
    }


def _pick_totals_line(consensus: MarketConsensus) -> tuple[str | None, dict[str, float] | None, list[str]]:
    notes: list[str] = []
    totals = consensus.totals_by_line or {}
    if not totals:
        return None, None, notes
    if "2.5" in totals:
        return "2.5", totals["2.5"], notes
    best_line: str | None = None
    best_dist = 999.0
    for line, values in totals.items():
        try:
            dist = abs(float(line) - 2.5)
        except ValueError:
            continue
        if dist < best_dist:
            best_dist = dist
            best_line = line
            best_values = values
    if best_line is not None:
        notes.append(f"totals_line_{best_line}_used_instead_of_2_5")
        return best_line, best_values, notes
    return None, None, notes


def _derive_goal_trend(totals: dict[str, float] | None) -> GoalTrend:
    if not totals:
        return "unavailable"
    over = float(totals.get("over", 50.0))
    under = float(totals.get("under", 50.0))
    edge = abs(over - under)
    if edge < _GOAL_TREND_EDGE_PP:
        return "neutral"
    return "over_2_5" if over > under else "under_2_5"


def _derive_btts_signal(btts: dict[str, float] | None) -> BttsSignal:
    if not btts:
        return "unavailable"
    yes = float(btts.get("yes", 50.0))
    no = float(btts.get("no", 50.0))
    edge = abs(yes - no)
    if edge < _GOAL_TREND_EDGE_PP:
        return "neutral"
    return "yes" if yes > no else "no"


def _derive_spread_signal(
    consensus: MarketConsensus,
    *,
    market_favorite: str,
) -> tuple[SpreadSignal, float | None]:
    spreads = consensus.spreads_by_line or {}
    if not spreads or market_favorite in ("balanced", "Draw"):
        return "unavailable", None
    best_line = None
    best_values: dict[str, float] | None = None
    best_abs = 999.0
    for line, values in spreads.items():
        try:
            point = abs(float(line))
        except ValueError:
            continue
        if point < best_abs:
            best_abs = point
            best_line = line
            best_values = values
    if best_values is None or best_line is None:
        return "unavailable", None
    try:
        signed = float(best_line)
    except ValueError:
        signed = 0.0
    home_cover = float(best_values.get("home", 50.0))
    away_cover = float(best_values.get("away", 50.0))
    cover_edge = abs(home_cover - away_cover)
    favors_home = home_cover >= away_cover
    if cover_edge < _EDGE_BALANCED_PP:
        return "neutral", signed
    if favors_home:
        if cover_edge >= _EDGE_STRONG_PP:
            return "strong_home_favorite", signed
        if cover_edge >= _EDGE_CLEAR_PP:
            return "clear_home_favorite", signed
        return "slight_home_favorite", signed
    if cover_edge >= _EDGE_STRONG_PP:
        return "strong_away_favorite", signed
    if cover_edge >= _EDGE_CLEAR_PP:
        return "clear_away_favorite", signed
    return "slight_away_favorite", signed


def _market_favorite_label(
    *,
    home_team: str,
    away_team: str,
    h2h: dict[str, float],
) -> str:
    home = normalize_team_for_event_map(home_team)
    away = normalize_team_for_event_map(away_team)
    ranked = sorted(
        (("home", h2h["home"]), ("draw", h2h["draw"]), ("away", h2h["away"])),
        key=lambda x: x[1],
        reverse=True,
    )
    top_side, top_p = ranked[0]
    second_p = ranked[1][1]
    if top_p - second_p < _EDGE_BALANCED_PP:
        return "balanced"
    if top_side == "draw":
        return "Draw"
    return home if top_side == "home" else away


def _blend_probs(
    base: dict[str, float],
    market: dict[str, float],
    *,
    market_weight_pct: int,
) -> dict[str, float]:
    mw = market_weight_pct / 100.0
    bw = 1.0 - mw
    return {
        "home_win": round(base["home_win"] * bw + market["home"] * mw, 4),
        "draw": round(base["draw"] * bw + market["draw"] * mw, 4),
        "away_win": round(base["away_win"] * bw + market["away"] * mw, 4),
    }


def _outcome_fit(score_outcome: OutcomeKey, target_outcome: OutcomeKey) -> float:
    if score_outcome == target_outcome:
        return 1.0
    if target_outcome == "draw":
        return 0.35 if score_outcome != "draw" else 1.0
    return 0.2


def _goal_trend_fit(total_goals: int, trend: GoalTrend) -> float:
    if trend == "unavailable" or trend == "neutral":
        return 0.75
    if trend == "under_2_5":
        return 1.0 if total_goals <= 2 else (0.55 if total_goals == 3 else 0.25)
    return 1.0 if total_goals >= 3 else (0.55 if total_goals == 2 else 0.25)


def _btts_fit(h: int, a: int, signal: BttsSignal) -> float:
    if signal == "unavailable" or signal == "neutral":
        return 0.75
    both_score = h > 0 and a > 0
    if signal == "yes":
        return 1.0 if both_score else 0.35
    return 1.0 if not both_score else 0.35


def _spread_fit(h: int, a: int, signal: SpreadSignal, target_outcome: OutcomeKey) -> float:
    if signal == "unavailable" or signal == "neutral":
        return 0.75
    margin = abs(h - a)
    if signal.endswith("home_favorite"):
        if target_outcome != "home_win":
            return 0.3
        if "slight" in signal:
            return 1.0 if margin == 1 else (0.8 if margin == 2 else 0.5)
        if "clear" in signal:
            return 1.0 if margin in (1, 2) else (0.7 if margin == 3 else 0.4)
        return 1.0 if margin >= 2 else 0.6
    if signal.endswith("away_favorite"):
        if target_outcome != "away_win":
            return 0.3
        if "slight" in signal:
            return 1.0 if margin == 1 else (0.8 if margin == 2 else 0.5)
        if "clear" in signal:
            return 1.0 if margin in (1, 2) else (0.7 if margin == 3 else 0.4)
        return 1.0 if margin >= 2 else 0.6
    return 0.75


def _xg_realism_penalty(h: int, a: int, *, home_xg: float, away_xg: float) -> float:
    total_xg = max(home_xg, 0.01) + max(away_xg, 0.01)
    total_goals = h + a
    if total_xg < 2.2 and total_goals >= 4:
        return 0.35
    if total_xg < 2.5 and total_goals >= 5:
        return 0.25
    if total_goals > total_xg + 2.5:
        return 0.5
    return 1.0


def _candidate_scores(
    matrix: Mapping[str, float],
    *,
    market_weight_pct: int,
    model_weight_pct: int,
    target_outcome: OutcomeKey,
    goal_trend: GoalTrend,
    btts_signal: BttsSignal,
    spread_signal: SpreadSignal,
    home_xg: float,
    away_xg: float,
) -> list[dict[str, Any]]:
    mw = market_weight_pct / 100.0
    bw = model_weight_pct / 100.0
    ranked = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
    candidates = ranked[:20]
    if len(candidates) < 12:
        for score, prob in ranked[20:40]:
            candidates.append((score, prob))
    results: list[dict[str, Any]] = []
    for score, base_prob in candidates:
        parsed = _parse_score(score)
        if parsed is None or base_prob <= 0:
            continue
        h, a = parsed
        outcome = _outcome_for_score(h, a)
        base_component = base_prob / 100.0
        market_component = (
            _outcome_fit(outcome, target_outcome)
            * _goal_trend_fit(h + a, goal_trend)
            * _btts_fit(h, a, btts_signal)
            * _spread_fit(h, a, spread_signal, target_outcome)
            * _xg_realism_penalty(h, a, home_xg=home_xg, away_xg=away_xg)
        )
        combined = (bw * base_component + mw * market_component) * 100.0
        results.append(
            {
                "score": score,
                "probability": round(combined, 4),
                "outcome": outcome,
                "base_probability": round(base_prob, 4),
            }
        )
    results.sort(key=lambda row: row["probability"], reverse=True)
    return results


def _select_score(
    candidates: list[dict[str, Any]],
    *,
    target_outcome: OutcomeKey,
    market_edge_pp: float,
    market_favorite: str,
) -> dict[str, Any]:
    if not candidates:
        return {}
    top = candidates[0]
    if market_favorite == "balanced" or market_edge_pp < _FAVORITE_OVERRIDE_EDGE_PP:
        return top
    favorite_candidates = [c for c in candidates if c["outcome"] == target_outcome]
    if not favorite_candidates:
        return top
    best_fav = favorite_candidates[0]
    gap = top["probability"] - best_fav["probability"]
    ratio = best_fav["probability"] / top["probability"] if top["probability"] > 0 else 0.0
    if gap <= _FAVORITE_OVERRIDE_GAP_PP or ratio >= _FAVORITE_OVERRIDE_RATIO:
        return best_fav
    return top


def _build_explanation(
    *,
    selected_score: str,
    selected_outcome: OutcomeKey,
    market_favorite: str,
    goal_trend: GoalTrend,
    btts_signal: BttsSignal,
    home_team: str,
    away_team: str,
) -> str:
    home = normalize_team_for_event_map(home_team)
    away = normalize_team_for_event_map(away_team)
    fav = market_favorite
    if fav == "balanced":
        fav_text = "a balanced market"
    elif fav == "Draw":
        fav_text = "a draw"
    elif fav == home:
        fav_text = f"{home}"
    else:
        fav_text = f"{away}"

    goal_text = {
        "under_2_5": "a relatively low-scoring match",
        "over_2_5": "a higher-scoring match",
        "neutral": "a neutral goal environment",
        "unavailable": "limited totals market data",
    }[goal_trend]
    btts_text = {
        "yes": "both teams likely to score",
        "no": "a clean-sheet tendency",
        "neutral": "neutral BTTS signals",
        "unavailable": "limited BTTS data",
    }[btts_signal]

    if selected_outcome == "draw":
        return (
            f"Market odds pointed to {fav_text} with {goal_text} and {btts_text}. "
            f"The market-primary prediction is therefore {selected_score}."
        )
    winner = home if selected_outcome == "home_win" else away
    return (
        f"Market odds favored {fav_text} overall, while goal markets pointed to {goal_text} "
        f"and {btts_text}. The market-primary prediction is therefore {selected_score} "
        f"({winner} win)."
    )


def build_market_primary_prediction(
    *,
    home_team: str,
    away_team: str,
    model_score_matrix: Mapping[str, float] | None,
    base_probabilities_1x2: Mapping[str, float] | None,
    home_xg: float | None = None,
    away_xg: float | None = None,
    resolution_context: MarketResolutionContext | None = None,
    shadow_diagnostics_enabled: bool | None = None,
    live_fetch_enabled: bool | None = None,
) -> MarketPrimaryPredictionResult:
    """Build market-primary prediction block; never raises."""
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
    if not shadow_on or not live_on:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "provider_disabled", "notes": []},
        )

    consensus = resolution_context.consensus if resolution_context else None
    quality = resolution_context.quality if resolution_context else None
    if consensus is None or quality is None:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "market_unavailable", "notes": []},
        )

    if quality.band == BAND_RED:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={
                "applied": False,
                "reason": "quality_below_minimum",
                "confidence": BAND_RED,
                "notes": ["red_band_no_market_primary"],
            },
        )

    weights = _BAND_WEIGHTS.get(quality.band)
    if weights is None:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "quality_below_minimum", "notes": []},
        )
    market_weight_pct, model_weight_pct = weights

    h2h = _market_h2h_triplet(consensus)
    if not h2h:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "missing_h2h", "notes": []},
        )

    if not model_score_matrix:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "missing_score_matrix", "notes": []},
        )

    matrix = _normalize_matrix(dict(model_score_matrix))
    base_probs = {
        "home_win": float((base_probabilities_1x2 or {}).get("home_win", 33.33)),
        "draw": float((base_probabilities_1x2 or {}).get("draw", 33.33)),
        "away_win": float((base_probabilities_1x2 or {}).get("away_win", 33.34)),
    }
    market_probs = {"home": h2h["home"], "draw": h2h["draw"], "away": h2h["away"]}
    target_probs = _blend_probs(base_probs, market_probs, market_weight_pct=market_weight_pct)

    totals_line, totals_values, notes = _pick_totals_line(consensus)
    goal_trend = _derive_goal_trend(totals_values)
    btts_signal = _derive_btts_signal(consensus.btts)
    market_favorite = _market_favorite_label(home_team=home_team, away_team=away_team, h2h=h2h)
    spread_signal, spread_line = _derive_spread_signal(consensus, market_favorite=market_favorite)

    fav_outcome, fav_prob, _, second_prob, edge_pp = _rank_h2h(market_probs)
    if market_favorite == "balanced":
        target_outcome, _, _, _, _ = _rank_outcome(target_probs)
    else:
        target_outcome = fav_outcome

    hxg = float(home_xg or 1.2)
    axg = float(away_xg or 1.2)
    candidates = _candidate_scores(
        matrix,
        market_weight_pct=market_weight_pct,
        model_weight_pct=model_weight_pct,
        target_outcome=target_outcome,
        goal_trend=goal_trend,
        btts_signal=btts_signal,
        spread_signal=spread_signal,
        home_xg=hxg,
        away_xg=axg,
    )
    if not candidates:
        return MarketPrimaryPredictionResult(
            applied=False,
            payload={"applied": False, "reason": "missing_score_matrix", "notes": notes},
        )

    selected = _select_score(
        candidates,
        target_outcome=target_outcome,
        market_edge_pp=edge_pp,
        market_favorite=market_favorite,
    )
    selected_score = str(selected.get("score", ""))
    selected_outcome = str(selected.get("outcome", target_outcome))

    explanation = _build_explanation(
        selected_score=selected_score,
        selected_outcome=selected_outcome,  # type: ignore[arg-type]
        market_favorite=market_favorite,
        goal_trend=goal_trend,
        btts_signal=btts_signal,
        home_team=home_team,
        away_team=away_team,
    )

    top_scores = [
        {"score": row["score"], "probability": row["probability"]}
        for row in candidates[:5]
    ]

    payload: dict[str, Any] = {
        "applied": True,
        "reason": "applied",
        "market_weight_pct": market_weight_pct,
        "model_weight_pct": model_weight_pct,
        "selected_score": selected_score,
        "selected_outcome": selected_outcome,
        "market_favorite": market_favorite,
        "confidence": quality.band,
        "market_goal_trend": goal_trend,
        "btts_signal": btts_signal,
        "spread_signal": spread_signal,
        "explanation": explanation,
        "inputs": {
            "h2h": h2h,
            "totals": {
                "line": float(totals_line) if totals_line else None,
                "over": round(float(totals_values["over"]), 2) if totals_values else None,
                "under": round(float(totals_values["under"]), 2) if totals_values else None,
            },
            "btts": {
                "yes": round(float(consensus.btts["yes"]), 2) if consensus.btts else None,
                "no": round(float(consensus.btts["no"]), 2) if consensus.btts else None,
            },
            "spread": spread_line,
        },
        "top_scores": top_scores,
        "notes": notes,
    }
    return MarketPrimaryPredictionResult(applied=True, payload=payload)
