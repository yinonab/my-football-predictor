"""Phase 2C/2J — Qualitative regression suite for diagnostic matchups."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import config
from core.global_ratings import english_name
from core.model_activation_gate import WARNING_BALANCED_SHIFT, check_balanced_match_shift
from core.power_effective_elo import _BASELINE_SENTINEL, run_full_shadow_pipeline
from data.database import LiveDataManager


@dataclass
class RegressionMatchupResult:
    home: str
    away: str
    issue: str
    expect: str
    current_1x2: dict[str, float]
    candidate_1x2: dict[str, float]
    delta_1x2: dict[str, float]
    current_xg: dict[str, float]
    candidate_xg: dict[str, float]
    warnings: list[str]
    improves_known_issue: bool
    notes: str = ""
    external_rating_mode: str = "none"
    candidate: str = ""
    strategy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_diagnostic_matchups(path: Path | None = None) -> dict[str, Any]:
    p = path or Path(__file__).resolve().parent.parent / "data" / "diagnostic_matchups.json"
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def _evaluate_expectation(
    expect: str,
    *,
    current: dict[str, float],
    candidate: dict[str, float],
    delta: dict[str, float],
) -> tuple[bool, str]:
    if expect == "candidate_should_increase_brazil_home_win_vs_baseline":
        ok = delta["home_win"] > 0
        return ok, "Brazil home-win should rise" if ok else "Brazil home-win did not improve"
    if expect == "candidate_should_keep_portugal_strong_favorite":
        ok = candidate["home_win"] >= 60.0
        return ok, "Portugal remains strong favorite" if ok else "Portugal home-win below 60%"
    if expect == "candidate_should_not_under_rate_germany":
        ok = candidate["home_win"] >= current["home_win"] - 2.0
        return ok, "Germany not under-rated" if ok else "Germany home-win dropped materially"
    if expect == "candidate_should_keep_spain_favorite":
        ok = candidate["home_win"] > candidate["away_win"]
        return ok, "Spain remains favorite" if ok else "Spain no longer favorite"
    if expect == "candidate_should_not_reverse_favorite":
        cur_fav = max(
            ("home_win", "draw", "away_win"),
            key=lambda k: current[k],
        )
        cand_fav = max(
            ("home_win", "draw", "away_win"),
            key=lambda k: candidate[k],
        )
        ok = cur_fav == cand_fav
        return ok, "Favorite direction preserved" if ok else "Favorite reversed"
    if expect == "candidate_should_remain_balanced_no_large_shift":
        ok = all(abs(delta[k]) <= config.BALANCED_MATCH_MAX_SHIFT_PP for k in delta)
        return ok, "Balanced match stable" if ok else "Balanced match shifted too much"
    if expect == "candidate_should_not_create_extreme_shift":
        ok = all(abs(delta[k]) <= config.BALANCED_MATCH_MAX_SHIFT_PP + 3.0 for k in delta)
        return ok, "No extreme shift" if ok else "Large probability shift detected"
    return True, "No expectation rule"


def _team_snapshot_from_live(team_key: str, dm: LiveDataManager):
    from core.temporal_backtest import TeamRatingSnapshot

    data = dm.get_team_data(team_key)
    return TeamRatingSnapshot(
        team=team_key,
        internal_elo=float(data.get("elo", 1500.0)),
        form=float(data.get("form", 0.0)),
        attack=float(data.get("attack", 0.0)),
        defense=float(data.get("defense", 0.0)),
        goals_for_per_game=float(data.get("goals_for_per_game", 0.0)),
        goals_against_per_game=float(data.get("goals_against_per_game", 0.0)),
        match_count=int(data.get("match_count", 0)),
        avg_opponent_elo=float(data.get("avg_opponent_elo", 1500.0)),
        opponent_adjusted_form=float(data.get("opponent_adjusted_form", 0.0)),
        rating_confidence=float(data.get("rating_confidence", 0.85)),
    )


def run_fifa_external_shadow_matchup(
    home_key: str,
    away_key: str,
    *,
    candidate: str,
    strategy: str,
    dataset_key: str = "wc2022",
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
) -> dict[str, Any]:
    """Shadow prediction using normalized FIFA-points external anchor (not production)."""
    from core.temporal_backtest import RatingSnapshot, run_temporal_shadow_pipeline

    dm = data_manager or LiveDataManager()
    if opponent_index is None:
        from core.opponent_maher import build_opponent_index
        from core.team_ratings import build_all_matches
        from data.database import FIFA_ELO_2026

        opponent_index = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    home_en = english_name(home_key) or home_key.split(" (")[0]
    away_en = english_name(away_key) or away_key.split(" (")[0]

    snapshot = RatingSnapshot(
        as_of_date="diagnostic",
        teams={
            home_en: _team_snapshot_from_live(home_key, dm),
            away_en: _team_snapshot_from_live(away_key, dm),
        },
    )

    return run_temporal_shadow_pipeline(
        home_en,
        away_en,
        snapshot=snapshot,
        prior_matches=[],
        candidate=candidate,
        elo_strategy=strategy,
        world_elo_mode="none",
        dataset_key=dataset_key,
        match_date="2099-01-01",
    )


def run_regression_diagnostic_matchup(
    home: str,
    away: str,
    *,
    issue: str = "",
    expect: str = "",
    power_variant: str | None = None,
    elo_strategy: str | None = None,
    external_rating_mode: str = "none",
    fifa_dataset_key: str = "wc2022",
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
) -> RegressionMatchupResult:
    dm = data_manager or LiveDataManager()
    if opponent_index is None:
        from core.opponent_maher import build_opponent_index
        from core.team_ratings import build_all_matches
        from data.database import FIFA_ELO_2026

        opponent_index = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    home_key, _ = dm.resolve_team(home)
    away_key, _ = dm.resolve_team(away)

    pv = power_variant or config.ACTIVATION_GATE_DEFAULT_CANDIDATE[0]
    es = elo_strategy or config.ACTIVATION_GATE_DEFAULT_CANDIDATE[1]

    baseline = run_full_shadow_pipeline(
        home_key,
        away_key,
        power_variant="current",
        data_manager=dm,
        opponent_index=opponent_index,
        current_baseline=_BASELINE_SENTINEL,
    )

    if external_rating_mode == "fifa_points_snapshot":
        from core.power_effective_elo import ShadowPredictionResult

        fifa_pred = run_fifa_external_shadow_matchup(
            home_key,
            away_key,
            candidate=pv,
            strategy=es,
            dataset_key=fifa_dataset_key,
            data_manager=dm,
            opponent_index=opponent_index,
        )
        cand = ShadowPredictionResult(
            variant=pv,
            effective_elo_strategy=es,
            home_power=0.0,
            away_power=0.0,
            home_xg=float(fifa_pred["home_xg"]),
            away_xg=float(fifa_pred["away_xg"]),
            probabilities_1x2=fifa_pred["probabilities_1x2"],
            top_scores=fifa_pred.get("top_scores", []),
            power_gap=0.0,
            delta_vs_current={},
        )
    else:
        candidate = run_full_shadow_pipeline(
            home_key,
            away_key,
            power_variant=pv,
            effective_elo_strategy=es,
            data_manager=dm,
            opponent_index=opponent_index,
            current_baseline=baseline,
        )
        cand = candidate

    cur = baseline.probabilities_1x2
    cand_probs = cand.probabilities_1x2
    delta = {
        "home_win": round(cand_probs["home_win"] - cur["home_win"], 2),
        "draw": round(cand_probs["draw"] - cur["draw"], 2),
        "away_win": round(cand_probs["away_win"] - cur["away_win"], 2),
    }

    warnings: list[str] = []
    shift = check_balanced_match_shift(cur, cand_probs)
    if shift:
        warnings.append(shift)

    improves, note = _evaluate_expectation(expect, current=cur, candidate=cand_probs, delta=delta)

    return RegressionMatchupResult(
        home=home_key.split(" (")[0],
        away=away_key.split(" (")[0],
        issue=issue,
        expect=expect,
        current_1x2=cur,
        candidate_1x2=cand_probs,
        delta_1x2=delta,
        current_xg={"home": baseline.home_xg, "away": baseline.away_xg},
        candidate_xg={"home": cand.home_xg, "away": cand.away_xg},
        warnings=warnings,
        improves_known_issue=improves,
        notes=note,
        external_rating_mode=external_rating_mode,
        candidate=pv,
        strategy=es,
    )


def run_all_regression_diagnostics(
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
    config_path: Path | None = None,
    external_rating_mode: str = "none",
    power_variant: str | None = None,
    elo_strategy: str | None = None,
    fifa_dataset_key: str = "wc2022",
) -> list[RegressionMatchupResult]:
    spec = _load_diagnostic_matchups(config_path)
    default = spec.get("default_candidate", {})
    pv = power_variant or default.get("power_variant", config.ACTIVATION_GATE_DEFAULT_CANDIDATE[0])
    es = elo_strategy or default.get("elo_strategy", config.ACTIVATION_GATE_DEFAULT_CANDIDATE[1])

    results: list[RegressionMatchupResult] = []
    for item in spec.get("matchups", []):
        results.append(
            run_regression_diagnostic_matchup(
                item["home"],
                item["away"],
                issue=item.get("issue", ""),
                expect=item.get("expect", ""),
                power_variant=pv,
                elo_strategy=es,
                external_rating_mode=external_rating_mode,
                fifa_dataset_key=fifa_dataset_key,
                data_manager=data_manager,
                opponent_index=opponent_index,
            )
        )
    return results


def collect_balanced_match_warnings(
    results: list[RegressionMatchupResult],
) -> list[str]:
    warnings: list[str] = []
    for r in results:
        for w in r.warnings:
            if w not in warnings:
                warnings.append(w)
    return warnings


def format_regression_table(results: list[RegressionMatchupResult]) -> str:
    header = (
        f"{'home':10} | {'away':12} | {'c_hw':>5} | {'s_hw':>5} | "
        f"{'d_hw':>5} | {'improves':>8} | warnings"
    )
    lines = [header, "-" * len(header)]
    for r in results:
        lines.append(
            f"{r.home:10} | {r.away:12} | {r.current_1x2['home_win']:5.1f} | "
            f"{r.candidate_1x2['home_win']:5.1f} | {r.delta_1x2['home_win']:+5.1f} | "
            f"{str(r.improves_known_issue):>8} | {','.join(r.warnings) or r.notes or '-'}"
        )
    return "\n".join(lines)
