"""Logistic xG, Negative Binomial overdispersion, Dixon-Coles, normalized 1X2."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from scipy.stats import nbinom, poisson

import config

logger = logging.getLogger(__name__)


class AdvancedDixonColesEngine:
    """Negative Binomial goal model with Dixon-Coles low-score draw correction."""

    def __init__(
        self,
        rho: float = config.DEFAULT_RHO,
        global_avg: float = config.GLOBAL_XG_AVG,
        alpha: float = config.OVERDISPERSION_ALPHA,
    ) -> None:
        self.rho = rho
        self.global_avg = global_avg
        self.alpha = alpha

    def _get_nbinom_probs(self, mu: float, max_goals: int) -> list[float]:
        """Convert mean (mu) and overdispersion (alpha) into goal-count probabilities."""
        mu = max(mu, 0.01)

        if self.alpha <= 0:
            probs = [float(poisson.pmf(k, mu)) for k in range(max_goals)]
        else:
            variance = mu + self.alpha * (mu**2)
            if variance <= mu + 1e-9:
                probs = [float(poisson.pmf(k, mu)) for k in range(max_goals)]
            else:
                p = mu / variance
                n = (mu**2) / (variance - mu)
                if n <= 0 or p <= 0 or p >= 1:
                    probs = [float(poisson.pmf(k, mu)) for k in range(max_goals)]
                else:
                    probs = [float(nbinom.pmf(k, n, p)) for k in range(max_goals)]

        total = sum(probs)
        if total > 0:
            return [p / total for p in probs]
        return probs

    @staticmethod
    def _ensure_underdog_score_in_top(
        scores: dict[str, float],
        top_sorted: list[tuple[str, float]],
        top_n: int,
        *,
        home_is_favorite: bool,
    ) -> list[tuple[str, float]]:
        """If every top score is a clean sheet for the favorite, surface a 4-1 / 5-1 style line."""
        if len(top_sorted) < 2:
            return top_sorted
        dog_idx = 1 if home_is_favorite else 0
        if any(int(s.split("-")[dog_idx]) >= 1 for s, _ in top_sorted):
            return top_sorted
        dog_scores = [
            (s, p) for s, p in scores.items() if int(s.split("-")[dog_idx]) >= 1
        ]
        if not dog_scores:
            return top_sorted
        best = max(dog_scores, key=lambda x: x[1])
        if best[1] < top_sorted[-1][1] * 0.2:
            return top_sorted
        merged = sorted(top_sorted[:-1] + [best], key=lambda x: x[1], reverse=True)
        return merged[:top_n]

    def _tau_correction(
        self, h: int, a: int, lambda_h: float, lambda_a: float
    ) -> float:
        if h == 0 and a == 0:
            return 1.0 - (lambda_h * lambda_a * self.rho)
        if h == 1 and a == 0:
            return 1.0 + (lambda_a * self.rho)
        if h == 0 and a == 1:
            return 1.0 + (lambda_h * self.rho)
        if h == 1 and a == 1:
            return 1.0 - self.rho
        return 1.0

    def generate_match_prediction(
        self,
        power_home: float,
        power_away: float,
        advantage: float,
        max_goals: int = 6,
        include_all_scores: bool = False,
        top_n: int = 3,
        coverage_target: float = 50.0,
        home_xg_override: float | None = None,
        away_xg_override: float | None = None,
    ) -> dict[str, Any]:
        if home_xg_override is not None and away_xg_override is not None:
            home_xg = home_xg_override
            away_xg = away_xg_override
        else:
            delta_power = power_home - power_away + advantage
            prob_home = 1.0 / (1.0 + math.pow(10, -delta_power / 400))
            home_xg = prob_home * self.global_avg
            away_xg = (1.0 - prob_home) * self.global_avg

        home_vector = self._get_nbinom_probs(home_xg, max_goals)
        away_vector = self._get_nbinom_probs(away_xg, max_goals)

        matrix = np.zeros((max_goals, max_goals))
        for h in range(max_goals):
            for a in range(max_goals):
                tau = self._tau_correction(h, a, home_xg, away_xg)
                matrix[h, a] = tau * home_vector[h] * away_vector[a]

        raw_sum = float(np.sum(matrix))
        logger.info(
            "NB matrix sum before normalization: %.6f (home_xg=%.2f, away_xg=%.2f, alpha=%.3f)",
            raw_sum,
            home_xg,
            away_xg,
            self.alpha,
        )

        normalized = matrix / raw_sum

        home_win, draw, away_win = 0.0, 0.0, 0.0
        scores: dict[str, float] = {}

        for h in range(max_goals):
            for a in range(max_goals):
                prob = float(normalized[h, a])
                scores[f"{h}-{a}"] = round(prob * 100, 2)
                if h > a:
                    home_win += prob
                elif a > h:
                    away_win += prob
                else:
                    draw += prob

        top_n = max(1, min(top_n, len(scores)))
        top_sorted = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
        if abs(home_xg - away_xg) >= 1.0:
            top_sorted = self._ensure_underdog_score_in_top(
                scores,
                top_sorted,
                top_n,
                home_is_favorite=home_xg >= away_xg,
            )

        cumulative = 0.0
        coverage_scores: list[str] = []
        for score, prob in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            cumulative += prob
            coverage_scores.append(score)
            if cumulative >= coverage_target:
                break

        result: dict[str, Any] = {
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "probabilities_1x2": {
                "home_win": round(home_win * 100, 1),
                "draw": round(draw * 100, 1),
                "away_win": round(away_win * 100, 1),
            },
            "top_scores": [
                {"score": score, "probability": prob} for score, prob in top_sorted
            ],
            "score_coverage": {
                "target_percent": coverage_target,
                "achieved_percent": round(cumulative, 1),
                "scores": coverage_scores,
            },
        }
        if include_all_scores:
            result["all_scores"] = scores
        return result

    def sample_match_score(
        self,
        power_home: float,
        power_away: float,
        advantage: float,
        max_goals: int = 6,
        rng: np.random.Generator | None = None,
    ) -> tuple[int, int]:
        """Sample one scoreline from the normalized score matrix."""
        rng = rng or np.random.default_rng()
        prediction = self.generate_match_prediction(
            power_home,
            power_away,
            advantage,
            max_goals=max_goals,
            include_all_scores=True,
        )
        all_scores: dict[str, float] = prediction["all_scores"]
        labels = list(all_scores.keys())
        weights = np.array([all_scores[k] for k in labels], dtype=float)
        weights /= weights.sum()
        chosen = rng.choice(labels, p=weights)
        h, a = chosen.split("-")
        return int(h), int(a)
