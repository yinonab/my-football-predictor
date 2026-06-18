"""Phase 2C — Multi-tournament full-pipeline shadow backtests."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import config
from core.power_effective_elo import (
    _BASELINE_SENTINEL,
    run_full_shadow_pipeline,
)
from data.tournament_data import (
    BacktestMatch,
    DATASET_REGISTRY,
    TournamentDataset,
    TournamentSnapshotDataManager,
    combined_all_matches,
    get_dataset,
    list_dataset_keys,
    resolve_dataset_key,
)


@dataclass
class MultiTournamentBacktestRow:
    dataset: str
    matches: int
    variant: str
    elo_strategy: str
    outcome_accuracy: float
    exact_score_accuracy: float
    top3_score_hit_rate: float
    mean_log_loss: float
    mean_brier: float
    favorite_calibration_error: float
    underdog_overconfidence_error: float
    avg_home_win_delta_vs_current: float
    avg_draw_delta_vs_current: float
    avg_away_win_delta_vs_current: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def serious_backtest_candidates(*, include_defense_flip: bool = False) -> list[tuple[str, str]]:
    """Default candidate set — defense flip excluded unless requested."""
    candidates: list[tuple[str, str]] = [
        ("current", "internal_only"),
        ("effective_elo_current_formula", "blended_static"),
        ("effective_elo_current_formula", "blended_confidence_weighted"),
        ("effective_elo_current_formula", "blended_disagreement_weighted"),
        ("effective_elo_adjusted_form", "blended_static"),
        ("effective_elo_adjusted_form", "blended_confidence_weighted"),
        ("effective_elo_adjusted_form", "blended_disagreement_weighted"),
    ]
    if include_defense_flip:
        for pv in (
            "effective_elo_defense_flipped",
            "effective_elo_defense_flipped_adjusted_form",
        ):
            for es in config.EFFECTIVE_ELO_STRATEGIES:
                candidates.append((pv, es))
    return candidates


def _favorite_bucket(prob: float) -> str | None:
    if prob >= 80:
        return "80+"
    if prob >= 70:
        return "70-80"
    if prob >= 60:
        return "60-70"
    if prob >= 50:
        return "50-60"
    return None


def _resolve_power_variant(power_variant: str, elo_strategy: str) -> tuple[str, str | None]:
    if power_variant == "current" and elo_strategy == "internal_only":
        return "current", None
    if power_variant == "current":
        return "effective_elo_current_formula", elo_strategy
    return power_variant, elo_strategy


def run_multitournament_backtest(
    dataset_key: str,
    power_variant: str,
    elo_strategy: str,
    *,
    matches: tuple[BacktestMatch, ...] | None = None,
    elo_map: dict[str, int] | None = None,
    dataset_label: str | None = None,
) -> MultiTournamentBacktestRow:
    from core.backtest import _brier_score, _log_loss_score, _outcome, _predicted_outcome
    from core.opponent_maher import build_opponent_index
    from core.team_ratings import build_all_matches
    from data.database import FIFA_ELO_2026

    if matches is None or elo_map is None:
        ds = get_dataset(dataset_key)
        if ds is None:
            raise ValueError("matches and elo_map required for combined 'all' dataset")
        matches = ds.matches
        elo_map = ds.elo_map
        dataset_label = ds.label

    dm = TournamentSnapshotDataManager(elo_map)
    opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    pv, eff_strategy = _resolve_power_variant(power_variant, elo_strategy)

    results: list[dict[str, Any]] = []
    bucket_errors: dict[str, list[float]] = {
        "50-60": [],
        "60-70": [],
        "70-80": [],
        "80+": [],
    }
    upset_overconf: list[float] = []

    for match in matches:
        home_key = match.home
        away_key = match.away
        if home_key not in dm.team_database or away_key not in dm.team_database:
            continue
        try:
            baseline = run_full_shadow_pipeline(
                home_key,
                away_key,
                power_variant="current",
                data_manager=dm,  # type: ignore[arg-type]
                opponent_index=opp_idx,
                advantage=0.0 if match.neutral else config.DEFAULT_HOME_ADV,
                current_baseline=_BASELINE_SENTINEL,
            )
            if pv == "current":
                pred = baseline
            else:
                pred = run_full_shadow_pipeline(
                    home_key,
                    away_key,
                    power_variant=pv,
                    effective_elo_strategy=eff_strategy,
                    data_manager=dm,  # type: ignore[arg-type]
                    opponent_index=opp_idx,
                    advantage=0.0 if match.neutral else config.DEFAULT_HOME_ADV,
                    current_baseline=baseline,
                )
        except Exception:
            continue

        probs = pred.probabilities_1x2
        base_probs = baseline.probabilities_1x2
        actual = _outcome(match.home_goals, match.away_goals)
        predicted = _predicted_outcome(probs)
        actual_score = f"{match.home_goals}-{match.away_goals}"

        fav_prob = max(probs["home_win"], probs["draw"], probs["away_win"])
        bucket = _favorite_bucket(fav_prob)
        if bucket:
            hit = 1.0 if (
                (predicted == "home" and actual == "home")
                or (predicted == "draw" and actual == "draw")
                or (predicted == "away" and actual == "away")
            ) else 0.0
            bucket_errors[bucket].append(abs(fav_prob / 100.0 - hit))

        home_elo = dm.get_team_data(home_key)["elo"]
        away_elo = dm.get_team_data(away_key)["elo"]
        elo_fav = "home" if home_elo >= away_elo else "away"
        if elo_fav != actual and actual in ("home", "away"):
            upset_overconf.append(
                max(probs["home_win"], probs["draw"], probs["away_win"]) / 100.0
            )

        prob_map = {"home": probs["home_win"], "draw": probs["draw"], "away": probs["away_win"]}
        results.append(
            {
                "outcome_correct": actual == predicted,
                "exact_hit": actual_score == pred.top_scores[0] if pred.top_scores else False,
                "top3_hit": actual_score in pred.top_scores[:3],
                "brier": _brier_score(probs, actual),
                "log_loss": _log_loss_score(prob_map[actual]),
                "home_delta": probs["home_win"] - base_probs["home_win"],
                "draw_delta": probs["draw"] - base_probs["draw"],
                "away_delta": probs["away_win"] - base_probs["away_win"],
            }
        )

    n = len(results)
    label = dataset_label or dataset_key
    if n == 0:
        return MultiTournamentBacktestRow(
            dataset=label,
            matches=0,
            variant=power_variant,
            elo_strategy=elo_strategy,
            outcome_accuracy=0.0,
            exact_score_accuracy=0.0,
            top3_score_hit_rate=0.0,
            mean_log_loss=0.0,
            mean_brier=0.0,
            favorite_calibration_error=0.0,
            underdog_overconfidence_error=0.0,
            avg_home_win_delta_vs_current=0.0,
            avg_draw_delta_vs_current=0.0,
            avg_away_win_delta_vs_current=0.0,
            notes="no evaluable matches",
        )

    fav_errs = [v for vals in bucket_errors.values() for v in vals]
    fav_calib = round(sum(fav_errs) / len(fav_errs), 4) if fav_errs else 0.0
    upset_err = round(sum(upset_overconf) / len(upset_overconf), 4) if upset_overconf else 0.0

    return MultiTournamentBacktestRow(
        dataset=label,
        matches=n,
        variant=power_variant,
        elo_strategy=elo_strategy,
        outcome_accuracy=round(sum(r["outcome_correct"] for r in results) / n * 100, 1),
        exact_score_accuracy=round(sum(r["exact_hit"] for r in results) / n * 100, 1),
        top3_score_hit_rate=round(sum(r["top3_hit"] for r in results) / n * 100, 1),
        mean_log_loss=round(sum(r["log_loss"] for r in results) / n, 4),
        mean_brier=round(sum(r["brier"] for r in results) / n, 4),
        favorite_calibration_error=fav_calib,
        underdog_overconfidence_error=upset_err,
        avg_home_win_delta_vs_current=round(sum(r["home_delta"] for r in results) / n, 2),
        avg_draw_delta_vs_current=round(sum(r["draw_delta"] for r in results) / n, 2),
        avg_away_win_delta_vs_current=round(sum(r["away_delta"] for r in results) / n, 2),
        notes="full Maher/xG/blowout pipeline",
    )


def run_dataset_backtests(
    dataset_key: str,
    *,
    include_defense_flip: bool = False,
    candidates: list[tuple[str, str]] | None = None,
) -> list[MultiTournamentBacktestRow]:
    key = resolve_dataset_key(dataset_key)
    cand = candidates or serious_backtest_candidates(include_defense_flip=include_defense_flip)
    rows: list[MultiTournamentBacktestRow] = []

    if key == "all":
        for ds_key in list_dataset_keys():
            ds = DATASET_REGISTRY[ds_key]
            for pv, es in cand:
                rows.append(
                    run_multitournament_backtest(
                        ds_key,
                        pv,
                        es,
                        matches=ds.matches,
                        elo_map=ds.elo_map,
                        dataset_label=ds.label,
                    )
                )
        for pv, es in cand:
            rows.append(
                run_multitournament_backtest(
                    "all",
                    pv,
                    es,
                    matches=combined_all_matches(),
                    elo_map=_combined_elo_map(),
                    dataset_label="All Combined",
                )
            )
        return rows

    ds = DATASET_REGISTRY[key]
    for pv, es in cand:
        rows.append(run_multitournament_backtest(key, pv, es))
    return rows


def _combined_elo_map() -> dict[str, int]:
    """Merge per-tournament Elo maps; first-seen wins (tournaments are disjoint)."""
    merged: dict[str, int] = {}
    for ds in DATASET_REGISTRY.values():
        for name, elo in ds.elo_map.items():
            merged.setdefault(name, elo)
    return merged


def run_all_multitournament_backtests(
    dataset_keys: list[str] | None = None,
    *,
    include_defense_flip: bool = False,
) -> list[MultiTournamentBacktestRow]:
    keys = dataset_keys or ["all"]
    rows: list[MultiTournamentBacktestRow] = []
    for key in keys:
        rows.extend(
            run_dataset_backtests(key, include_defense_flip=include_defense_flip)
        )
    return rows


def format_multitournament_table(rows: list[MultiTournamentBacktestRow]) -> str:
    header = (
        f"{'dataset':18} | {'n':>4} | {'variant':32} | {'elo_strat':24} | "
        f"{'1x2':>5} | {'exact':>5} | {'top3':>5} | {'log_loss':>8} | "
        f"{'brier':>6} | {'fav_err':>7} | {'upset':>5} | notes"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.dataset:18} | {row.matches:4d} | {row.variant:32} | "
            f"{row.elo_strategy:24} | {row.outcome_accuracy:5.1f} | "
            f"{row.exact_score_accuracy:5.1f} | {row.top3_score_hit_rate:5.1f} | "
            f"{row.mean_log_loss:8.4f} | {row.mean_brier:6.4f} | "
            f"{row.favorite_calibration_error:7.4f} | "
            f"{row.underdog_overconfidence_error:5.3f} | {row.notes}"
        )
    return "\n".join(lines)


def write_multitournament_csv(
    rows: list[MultiTournamentBacktestRow],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].to_dict().keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
