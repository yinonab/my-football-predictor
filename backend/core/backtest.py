"""Backtesting harness — evaluate model on historical match results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import config
from core.math_engine import AdvancedDixonColesEngine
from core.team_power import TeamPowerEvaluator
from data.wc2022 import WC2022_MATCHES, Wc2022DataManager, Wc2022Match


@dataclass
class MatchBacktestResult:
    home: str
    away: str
    actual_score: str
    predicted_top_score: str
    actual_outcome: str
    predicted_outcome: str
    outcome_correct: bool
    top3_hit: bool
    exact_hit: bool
    brier: float
    log_loss_score: float


@dataclass
class BacktestReport:
    tournament: str
    match_count: int
    outcome_accuracy: float
    exact_score_accuracy: float
    top3_score_hit_rate: float
    mean_brier: float
    mean_log_loss: float
    baseline_outcome_accuracy: float
    baseline_exact_accuracy: float
    upsets: list[MatchBacktestResult] = field(default_factory=list)
    best_predictions: list[MatchBacktestResult] = field(default_factory=list)
    worst_predictions: list[MatchBacktestResult] = field(default_factory=list)


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _predicted_outcome(probs: dict[str, float]) -> str:
    mapping = {
        "home": probs["home_win"],
        "draw": probs["draw"],
        "away": probs["away_win"],
    }
    return max(mapping, key=mapping.get)  # type: ignore[arg-type]


def _brier_score(probs_pct: dict[str, float], actual: str) -> float:
    mapping = {
        "home": probs_pct["home_win"] / 100.0,
        "draw": probs_pct["draw"] / 100.0,
        "away": probs_pct["away_win"] / 100.0,
    }
    return sum((mapping[key] - (1.0 if key == actual else 0.0)) ** 2 for key in mapping)


def _log_loss_score(prob_pct: float) -> float:
    p = max(prob_pct / 100.0, 1e-6)
    return -math.log(p)


class BacktestRunner:
    """Run walk-forward-style evaluation on a fixed pre-tournament rating snapshot."""

    def __init__(
        self,
        data_manager: Wc2022DataManager | None = None,
        engine: AdvancedDixonColesEngine | None = None,
        home_advantage: float = config.DEFAULT_HOME_ADV,
    ) -> None:
        self._dm = data_manager or Wc2022DataManager()
        self._evaluator = TeamPowerEvaluator(self._dm)  # type: ignore[arg-type]
        self._engine = engine or AdvancedDixonColesEngine()
        self._home_advantage = home_advantage

    def _predict_match(self, match: Wc2022Match) -> dict[str, Any]:
        home_power = self._evaluator.calculate_composite_power(match.home)
        away_power = self._evaluator.calculate_composite_power(match.away)
        home_power = self._evaluator.apply_environmental_modifiers(home_power)
        advantage = 0.0 if match.neutral else self._home_advantage
        return self._engine.generate_match_prediction(
            home_power,
            away_power,
            advantage,
            include_all_scores=True,
        )

    def evaluate_match(self, match: Wc2022Match) -> MatchBacktestResult:
        prediction = self._predict_match(match)
        probs = prediction["probabilities_1x2"]
        actual = _outcome(match.home_goals, match.away_goals)
        predicted = _predicted_outcome(
            {
                "home_win": probs["home_win"],
                "draw": probs["draw"],
                "away_win": probs["away_win"],
            }
        )

        actual_score = f"{match.home_goals}-{match.away_goals}"
        top_scores = prediction["top_scores"]
        predicted_top = top_scores[0]["score"]
        top3 = {item["score"] for item in top_scores}

        all_scores: dict[str, float] = prediction.get("all_scores", {})
        actual_prob = all_scores.get(actual_score, 0.01)

        return MatchBacktestResult(
            home=match.home,
            away=match.away,
            actual_score=actual_score,
            predicted_top_score=predicted_top,
            actual_outcome=actual,
            predicted_outcome=predicted,
            outcome_correct=actual == predicted,
            top3_hit=actual_score in top3,
            exact_hit=actual_score == predicted_top,
            brier=_brier_score(probs, actual),
            log_loss_score=_log_loss_score(actual_prob),
        )

    def run_wc2022(self) -> BacktestReport:
        results = [self.evaluate_match(match) for match in WC2022_MATCHES]
        n = len(results)

        outcome_hits = sum(1 for r in results if r.outcome_correct)
        exact_hits = sum(1 for r in results if r.exact_hit)
        top3_hits = sum(1 for r in results if r.top3_hit)

        # Naive favorite baseline: higher FIFA Elo always wins, 1-0 default exact.
        baseline_outcome = 0
        baseline_exact = 0
        for match in WC2022_MATCHES:
            home_elo = self._dm.get_team_data(match.home)["elo"]
            away_elo = self._dm.get_team_data(match.away)["elo"]
            actual = _outcome(match.home_goals, match.away_goals)
            if home_elo == away_elo:
                predicted = "draw"
            elif home_elo > away_elo:
                predicted = "home"
            else:
                predicted = "away"
            if predicted == actual:
                baseline_outcome += 1
            if match.home_goals == 1 and match.away_goals == 0 and predicted == "home":
                baseline_exact += 1
            elif match.home_goals == 0 and match.away_goals == 1 and predicted == "away":
                baseline_exact += 1

        upsets = [
            r
            for r in results
            if not r.outcome_correct
            and self._dm.get_team_data(r.home)["elo"] + 80
            >= self._dm.get_team_data(r.away)["elo"]
        ]

        sorted_by_log = sorted(results, key=lambda r: r.log_loss_score)
        return BacktestReport(
            tournament="World Cup 2022",
            match_count=n,
            outcome_accuracy=round(outcome_hits / n * 100, 1),
            exact_score_accuracy=round(exact_hits / n * 100, 1),
            top3_score_hit_rate=round(top3_hits / n * 100, 1),
            mean_brier=round(sum(r.brier for r in results) / n, 4),
            mean_log_loss=round(sum(r.log_loss_score for r in results) / n, 4),
            baseline_outcome_accuracy=round(baseline_outcome / n * 100, 1),
            baseline_exact_accuracy=round(baseline_exact / n * 100, 1),
            upsets=upsets[:8],
            best_predictions=sorted_by_log[:5],
            worst_predictions=sorted(results, key=lambda r: r.log_loss_score, reverse=True)[
                :8
            ],
        )
