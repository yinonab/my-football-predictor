"""Walk-forward backtest runner for Priority 1 model variants."""

from __future__ import annotations

from typing import Any

import config
from core.backtest import _outcome
from core.backtest_metrics import (
    BacktestMatchRow,
    aggregate_backtest_metrics,
    compare_metrics_to_baseline,
    scorelines_from_matrix,
)
from core.priority1_options import PRIORITY1_VARIANTS, Priority1Config, apply_power_variant_if_enabled, resolve_global_avg
from core.temporal_backtest import (
    _resolve_snapshot_for_match,
    load_historical_matches,
    matches_before_target,
    run_temporal_shadow_pipeline,
)
from data.tournament_data import DATASET_REGISTRY, resolve_dataset_key


def _run_match_with_priority1(
    match: Any,
    *,
    prior: list[Any],
    snapshot: Any,
    dataset_key: str,
    p1: Priority1Config,
    candidate: str,
    elo_strategy: str,
    world_elo_mode: str,
    prior_mode: str,
) -> dict[str, Any]:
    """Run temporal shadow pipeline with optional Priority 1 overrides."""
    from core.blowout import apply_blowout_adjustment
    from core.opponent_maher import estimate_xg_opponent_aware
    from core.maher import (
        blend_maher_with_power,
        floor_underdog_xg,
        mismatch_gap,
        scale_rho_for_gap,
    )
    from core.math_engine import AdvancedDixonColesEngine
    from core.power_zscore import population_from_rating_snapshot
    from core.temporal_backtest import (
        TemporalSnapshotDataManager,
        build_opponent_index,
        compute_temporal_power,
        _temporal_matches_to_nt,
    )

    home = match.home_team
    away = match.away_team
    home_snap = snapshot.get_team(home)
    away_snap = snapshot.get_team(away)

    home_power, home_blend = compute_temporal_power(
        home,
        home_snap,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        dataset_key=dataset_key,
        match_date=match.date,
    )
    away_power, away_blend = compute_temporal_power(
        away,
        away_snap,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        dataset_key=dataset_key,
        match_date=match.date,
    )

    pop_teams, pop_source = population_from_rating_snapshot(snapshot)
    hp, ap, _power_diag = apply_power_variant_if_enabled(
        home_power=home_power,
        away_power=away_power,
        home_elo=home_blend,
        away_elo=away_blend,
        home_form=home_snap.form,
        home_attack=home_snap.attack,
        home_defense=home_snap.defense,
        away_form=away_snap.form,
        away_attack=away_snap.attack,
        away_defense=away_snap.defense,
        p1=p1,
        population_teams=pop_teams,
        population_source=pop_source,
    )
    home_power, away_power = hp, ap

    registry = {m.home_team for m in prior} | {m.away_team for m in prior} | {home, away}
    opp_idx = build_opponent_index(_temporal_matches_to_nt(prior), registry)
    dm = TemporalSnapshotDataManager(snapshot)
    home_data = dm.get_team_data(home)
    away_data = dm.get_team_data(away)

    base_avg = config.GLOBAL_XG_AVG
    global_avg, _dyn_diag = resolve_global_avg(
        base_avg=base_avg,
        p1=p1,
        home_attack=home_snap.attack,
        home_defense=home_snap.defense,
        away_attack=away_snap.attack,
        away_defense=away_snap.defense,
        home_power=home_power,
        away_power=away_power,
        advantage=0.0,
        home_elo=home_blend,
        away_elo=away_blend,
    )

    home_xg, away_xg, _ = estimate_xg_opponent_aware(
        home,
        away,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        opp_idx,
        global_avg=global_avg,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        home_power,
        away_power,
        0.0,
        global_avg=global_avg,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        home_power,
        away_power,
        0.0,
        home_elo=home_blend,
        away_elo=away_blend,
    )

    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        home_power,
        away_power,
        0.0,
        base_alpha=config.OVERDISPERSION_ALPHA,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    gap_for_rho = mismatch_gap(
        home_power, away_power, 0.0, home_elo=home_blend, away_elo=away_blend
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(config.DEFAULT_RHO, gap_for_rho),
        global_avg=global_avg,
        alpha=blowout.alpha,
    )
    result = engine.generate_match_prediction(
        home_power,
        away_power,
        0.0,
        top_n=5,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
        include_all_scores=True,
    )
    if getattr(p1, "nr3_fcc_shadow_enabled", False):
        from core.disabled_shadow_wiring_runtime import attach_shadow_sidecar_if_enabled

        attach_shadow_sidecar_if_enabled(
            result,
            match=match,
            prior=prior,
            snapshot=snapshot,
            dataset_key=dataset_key,
            p1=p1,
            candidate=candidate,
            elo_strategy=elo_strategy,
            world_elo_mode=world_elo_mode,
            prior_mode=prior_mode,
            run_match_fn=_run_match_with_priority1,
        )
    return result


def collect_priority1_rows(
    dataset: str,
    *,
    variant_name: str,
    p1: Priority1Config,
    candidate: str = "effective_external_current_formula",
    elo_strategy: str = "fifa_points_confidence_weighted",
    world_elo_mode: str = "none",
    prior_mode: str = "tournament_prior_file",
) -> list[BacktestMatchRow]:
    from core.external_rating_mode import resolve_external_rating_mode, world_elo_mode_for_resolve

    ext_mode = resolve_external_rating_mode(
        external_rating_mode="fifa_points_snapshot",
        world_elo_mode=world_elo_mode,
    )
    resolved_world = world_elo_mode_for_resolve(ext_mode)

    eval_matches = load_historical_matches(dataset)
    full_history = load_historical_matches("all")
    key = resolve_dataset_key(dataset)
    label = DATASET_REGISTRY[key].label if key in DATASET_REGISTRY else key
    pv = "current" if candidate in ("baseline", "current") else candidate

    rows: list[BacktestMatchRow] = []
    for match in eval_matches:
        match_p1 = Priority1Config(
            power_variant=p1.power_variant,
            zscore_defense_sign=p1.zscore_defense_sign,
            xg_total_variant=p1.xg_total_variant,
            market_calibration_mode=p1.market_calibration_mode,
            odds_affect_prediction=p1.odds_affect_prediction,
            dataset_key=key,
            stage=getattr(match, "stage", None) or p1.stage,
            weather_xg_delta=p1.weather_xg_delta,
            market_probs_pct=p1.market_probs_pct,
            market_total_goals=p1.market_total_goals,
            books_count=p1.books_count,
            dynamic_goals_tuning=p1.dynamic_goals_tuning,
            tuning_label=p1.tuning_label,
            nr3_fcc_shadow_enabled=p1.nr3_fcc_shadow_enabled,
        )
        prior = matches_before_target(full_history, match)
        snap = _resolve_snapshot_for_match(
            match,
            full_history,
            dataset_key=key,
            prior_mode=prior_mode,  # type: ignore[arg-type]
        )
        pred = _run_match_with_priority1(
            match,
            prior=prior,
            snapshot=snap,
            dataset_key=key,
            p1=match_p1,
            candidate=pv,
            elo_strategy=elo_strategy,
            world_elo_mode=resolved_world,  # type: ignore[arg-type]
            prior_mode=prior_mode,
        )
        actual = _outcome(match.home_goals, match.away_goals)
        actual_score = f"{match.home_goals}-{match.away_goals}"
        all_scores = pred.get("all_scores") or {}
        scorelines = scorelines_from_matrix(all_scores, top_k=5)
        if not scorelines:
            scorelines = [item["score"] for item in pred.get("top_scores", [])[:5]]

        rows.append(
            BacktestMatchRow(
                predicted_probs={
                    "home_win": pred["probabilities_1x2"]["home_win"],
                    "draw": pred["probabilities_1x2"]["draw"],
                    "away_win": pred["probabilities_1x2"]["away_win"],
                },
                actual_outcome=actual,
                actual_score=actual_score,
                predicted_scorelines=scorelines,
                dataset=label,
                variant=variant_name,
            )
        )
    return rows


def evaluate_priority1_variant(
    datasets: list[str],
    *,
    variant_name: str,
    p1: Priority1Config,
) -> dict[str, Any]:
    per_dataset: dict[str, Any] = {}
    all_rows: list[BacktestMatchRow] = []
    for ds in datasets:
        rows = collect_priority1_rows(ds, variant_name=variant_name, p1=p1)
        per_dataset[ds] = aggregate_backtest_metrics(rows)
        all_rows.extend(rows)
    return {
        "variant": variant_name,
        "config": {
            "power_variant": p1.power_variant,
            "xg_total_variant": p1.xg_total_variant,
            "market_calibration_mode": p1.market_calibration_mode,
        },
        "per_dataset": per_dataset,
        "overall": aggregate_backtest_metrics(all_rows),
    }


def run_priority1_comparison(
    datasets: list[str] | None = None,
    *,
    variants: dict[str, Priority1Config] | None = None,
) -> dict[str, Any]:
    datasets = list(datasets or ("wc2018", "wc2022", "euro2024", "copa2024", "qualifiers2026"))
    variants = variants or PRIORITY1_VARIANTS
    results: dict[str, Any] = {}
    baseline_key = "baseline_current"
    for name, cfg in variants.items():
        results[name] = evaluate_priority1_variant(datasets, variant_name=name, p1=cfg)

    baseline = results.get(baseline_key, {}).get("overall", {})
    deltas: dict[str, Any] = {}
    for name, payload in results.items():
        if name == baseline_key:
            continue
        deltas[name] = {
            "overall": compare_metrics_to_baseline(payload["overall"], baseline),
            "per_dataset": {
                ds: compare_metrics_to_baseline(
                    payload["per_dataset"].get(ds, {}),
                    results[baseline_key]["per_dataset"].get(ds, {}),
                )
                for ds in datasets
            },
        }
    return {
        "datasets": datasets,
        "variants": results,
        "deltas_vs_baseline": deltas,
        "baseline_variant": baseline_key,
    }
