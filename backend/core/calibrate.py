"""Grid-search calibration on historical tournaments."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import config
from core.backtest import BacktestReport, BacktestRunner
from core.math_engine import AdvancedDixonColesEngine


@dataclass(frozen=True)
class ModelParams:
    rho: float
    alpha: float
    avg_goals: float
    home_advantage: float

    def as_dict(self) -> dict[str, float]:
        return {
            "rho": self.rho,
            "alpha": self.alpha,
            "avg_goals": self.avg_goals,
            "home_advantage": self.home_advantage,
        }


@dataclass
class CalibrationResult:
    params: ModelParams
    report: BacktestReport
    score: float  # composite objective (lower is better)


DEFAULT_GRID: dict[str, list[float]] = {
    "rho": [-0.15, -0.12, -0.10, -0.07, -0.05, -0.03],
    "alpha": [0.0, 0.05, 0.08, 0.12, 0.18, 0.25],
    "avg_goals": [2.2, 2.4, 2.6, 2.8, 3.0],
    "home_advantage": [0.0, 30.0, 45.0, 55.0, 70.0],
}


def _composite_score(report: BacktestReport) -> float:
    """Lower is better. Brier is primary; log-loss secondary."""
    return report.mean_brier + report.mean_log_loss * 0.05 - report.top3_score_hit_rate * 0.001


def evaluate_params(params: ModelParams) -> CalibrationResult:
    engine = AdvancedDixonColesEngine(
        rho=params.rho,
        global_avg=params.avg_goals,
        alpha=params.alpha,
    )
    runner = BacktestRunner(engine=engine, home_advantage=params.home_advantage)
    report = runner.run_wc2022()
    return CalibrationResult(
        params=params,
        report=report,
        score=round(_composite_score(report), 4),
    )


def grid_search(
    grid: dict[str, list[float]] | None = None,
    top_n: int = 5,
) -> list[CalibrationResult]:
    grid = grid or DEFAULT_GRID
    results: list[CalibrationResult] = []

    for rho, alpha, avg_goals, home_adv in product(
        grid["rho"],
        grid["alpha"],
        grid["avg_goals"],
        grid["home_advantage"],
    ):
        params = ModelParams(
            rho=rho,
            alpha=alpha,
            avg_goals=avg_goals,
            home_advantage=home_adv,
        )
        results.append(evaluate_params(params))

    results.sort(key=lambda item: item.score)
    return results[:top_n]


def current_defaults_report() -> CalibrationResult:
    return evaluate_params(
        ModelParams(
            rho=config.DEFAULT_RHO,
            alpha=config.OVERDISPERSION_ALPHA,
            avg_goals=config.GLOBAL_XG_AVG,
            home_advantage=config.DEFAULT_HOME_ADV,
        )
    )
