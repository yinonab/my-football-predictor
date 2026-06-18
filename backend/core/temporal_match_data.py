"""Phase 2E — Match date overrides, rating priors, and walk-forward data quality."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import config

DataQualityLabel = Literal["exact_datetime", "exact_date", "estimated_order", "missing_date"]
PriorMode = Literal["default_internal", "tournament_prior_file", "rolling_from_prior_dataset"]
PriorQuality = Literal["default_internal", "historical_prior", "rejected_leakage", "rolling_history"]

WARNING_MATCH_DATES_ESTIMATED = "MATCH_DATES_ESTIMATED"
WARNING_MATCH_DATES_MISSING = "MATCH_DATES_MISSING"
WARNING_PRIORS_MISSING = "PRIORS_MISSING"
WARNING_PRIOR_AS_OF_AFTER_MATCH = "PRIOR_AS_OF_AFTER_MATCH"
WARNING_INSUFFICIENT_PRIOR_HISTORY = "INSUFFICIENT_PRIOR_HISTORY"
WARNING_SAME_DAY_ORDER_AMBIGUOUS = "SAME_DAY_ORDER_AMBIGUOUS"

_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def _overrides_path() -> Path:
    return Path(config.TEMPORAL_MATCH_DATES_OVERRIDES_PATH)


def _priors_path() -> Path:
    return Path(config.TEMPORAL_RATING_PRIORS_PATH)


def load_match_date_overrides(dataset: str) -> list[dict[str, Any]]:
    path = _overrides_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    key = dataset.strip().lower()
    return list(data.get(key, []))


def _match_pair_key(home: str, away: str) -> tuple[str, str]:
    return (home.strip(), away.strip())


def apply_match_date_overrides(
    matches: list[Any],
    dataset: str,
) -> list[Any]:
    """Apply curated date/time overrides (mutates via replace on matching objects)."""
    overrides = load_match_date_overrides(dataset)
    if not overrides:
        return matches

    by_sequence: dict[int, dict[str, Any]] = {
        int(item["sequence_index"]): item
        for item in overrides
        if item.get("sequence_index") is not None
    }
    pair_queues: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in overrides:
        pair_queues.setdefault(
            _match_pair_key(item["home_team"], item["away_team"]),
            [],
        ).append(item)

    updated: list[Any] = []
    for m in matches:
        ov = by_sequence.get(int(m.sequence_index))
        if ov is None:
            key = _match_pair_key(m.home_team, m.away_team)
            queue = pair_queues.get(key, [])
            ov = queue.pop(0) if queue else None
        if not ov:
            updated.append(m)
            continue
        quality = "exact_datetime" if ov.get("kickoff_time") else "exact_date"
        updated.append(
            replace(
                m,
                date=ov.get("date", m.date),
                kickoff_time=ov.get("kickoff_time", m.kickoff_time),
                sequence_index=int(ov.get("sequence_index", m.sequence_index)),
                data_quality=quality,
                date_estimated=False,
            )
        )
    return updated


def _populate_priors_from_repo(dataset: str, block: dict[str, Any]) -> dict[str, Any]:
    """Fill empty teams dict from existing FIFA_ELO modules when schema present."""
    teams = block.get("teams") or {}
    if teams:
        return block
    key = dataset.lower()
    elo_map: dict[str, int] = {}
    if key == "wc2018":
        from data.wc2018 import WC2018_FIFA_ELO

        elo_map = dict(WC2018_FIFA_ELO)
    elif key == "euro2024":
        from data.euro2024 import EURO2024_FIFA_ELO

        elo_map = dict(EURO2024_FIFA_ELO)
    elif key == "copa2024":
        from data.copa2024 import COPA2024_FIFA_ELO

        elo_map = dict(COPA2024_FIFA_ELO)
    if not elo_map:
        return block
    block = dict(block)
    block["teams"] = {
        name: {"elo": elo, "confidence": 0.85} for name, elo in elo_map.items()
    }
    return block


def load_rating_priors(dataset: str) -> dict[str, Any] | None:
    path = _priors_path()
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    key = dataset.strip().lower()
    block = data.get(key)
    if not block:
        return None
    return _populate_priors_from_repo(key, block)


def resolve_initial_elos(
    dataset: str,
    as_of_date: str,
    *,
    prior_mode: PriorMode,
    rolling_elos: dict[str, float] | None = None,
) -> tuple[dict[str, float], PriorQuality, list[str]]:
    """Return initial Elo map, quality label, and warnings for a snapshot build."""
    warnings: list[str] = []

    if prior_mode == "default_internal":
        return {}, "default_internal", warnings

    if prior_mode == "rolling_from_prior_dataset":
        if rolling_elos:
            return dict(rolling_elos), "rolling_history", warnings
        warnings.append(WARNING_INSUFFICIENT_PRIOR_HISTORY)
        return {}, "default_internal", warnings

    priors = load_rating_priors(dataset)
    if not priors or not priors.get("teams"):
        warnings.append(WARNING_PRIORS_MISSING)
        return {}, "default_internal", warnings

    prior_as_of = priors.get("as_of", "")
    if prior_as_of and prior_as_of >= as_of_date:
        warnings.append(WARNING_PRIOR_AS_OF_AFTER_MATCH)
        return {}, "rejected_leakage", warnings

    elos = {
        team: float(info["elo"])
        for team, info in priors["teams"].items()
        if isinstance(info, dict) and "elo" in info
    }
    return elos, "historical_prior", warnings


@dataclass
class DatasetDataQualityReport:
    dataset: str
    matches: int
    exact_datetime_count: int
    exact_date_count: int
    estimated_order_count: int
    missing_date_count: int
    teams: int
    teams_with_priors: int
    prior_mode_available: bool
    leakage_label: str
    data_quality_score: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dataset_leakage_label(
    matches: list[Any],
    world_elo_mode: str = "none",
    prior_mode: str = "default_internal",
    dataset_key: str = "",
) -> str:
    from core.fixture_metadata import classify_dataset_leakage

    label, _, _ = classify_dataset_leakage(
        matches,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
        dataset_key=dataset_key,
    )
    return label


def audit_dataset_data_quality(
    dataset: str,
    *,
    prior_mode: PriorMode = "default_internal",
    world_elo_mode: str = "none",
) -> DatasetDataQualityReport:
    from core.temporal_backtest import (
        dataset_data_quality_summary,
        leakage_label_for_dataset_quality,
        load_historical_matches,
    )

    matches = load_historical_matches(dataset, apply_overrides=True)
    teams = {m.home_team for m in matches} | {m.away_team for m in matches}

    exact_dt = sum(1 for m in matches if m.data_quality == "exact_datetime")
    exact_d = sum(1 for m in matches if m.data_quality == "exact_date")
    estimated = sum(1 for m in matches if m.data_quality == "estimated_order")
    missing = sum(1 for m in matches if m.data_quality == "missing_date")

    warnings: list[str] = []
    if estimated > 0:
        warnings.append(WARNING_MATCH_DATES_ESTIMATED)
    if missing > 0:
        warnings.append(WARNING_MATCH_DATES_MISSING)

    dates_by_day: dict[str, int] = {}
    for m in matches:
        dates_by_day[m.date] = dates_by_day.get(m.date, 0) + 1
    if any(c > 1 and exact_dt == 0 for c in dates_by_day.values()):
        warnings.append(WARNING_SAME_DAY_ORDER_AMBIGUOUS)

    priors = load_rating_priors(dataset)
    teams_with_priors = len(priors.get("teams", {})) if priors else 0
    prior_available = bool(priors and priors.get("teams"))
    if prior_mode == "tournament_prior_file" and not prior_available:
        warnings.append(WARNING_PRIORS_MISSING)

    if matches:
        first_date = min(m.date for m in matches)
        if priors and priors.get("as_of", "") >= first_date:
            warnings.append(WARNING_PRIOR_AS_OF_AFTER_MATCH)

    n = len(matches) or 1
    score = round((exact_dt * 1.0 + exact_d * 0.85 + estimated * 0.5) / n, 3)

    return DatasetDataQualityReport(
        dataset=dataset,
        matches=len(matches),
        exact_datetime_count=exact_dt,
        exact_date_count=exact_d,
        estimated_order_count=estimated,
        missing_date_count=missing,
        teams=len(teams),
        teams_with_priors=teams_with_priors,
        prior_mode_available=prior_available,
        leakage_label=_dataset_leakage_label(
            matches,
            world_elo_mode,
            prior_mode=prior_mode,
            dataset_key=dataset,
        ),
        data_quality_score=score,
        warnings=warnings,
    )


def format_data_quality_table(reports: list[DatasetDataQualityReport]) -> str:
    header = (
        f"{'dataset':16} | {'n':>4} | {'ex_dt':>5} | {'ex_d':>4} | {'est':>4} | "
        f"{'miss':>4} | {'teams':>5} | {'priors':>6} | {'leak':>4} | {'score':>5} | warnings"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        warn = ",".join(r.warnings) if r.warnings else "-"
        lines.append(
            f"{r.dataset:16} | {r.matches:4d} | {r.exact_datetime_count:5d} | "
            f"{r.exact_date_count:4d} | {r.estimated_order_count:4d} | "
            f"{r.missing_date_count:4d} | {r.teams:5d} | {r.teams_with_priors:6d} | "
            f"{r.leakage_label:>4} | {r.data_quality_score:5.2f} | {warn}"
        )
    return "\n".join(lines)


def serious_walk_forward_candidates(
    *,
    include_defense_flip: bool = False,
) -> list[tuple[str, str]]:
    """Default serious walk-forward candidate set (defense flip excluded)."""
    candidates: list[tuple[str, str]] = [
        ("baseline", "internal_only"),
        ("effective_elo_current_formula", "blended_confidence_weighted"),
        ("effective_elo_current_formula", "blended_disagreement_weighted"),
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


def fifa_points_walk_forward_candidates() -> list[tuple[str, str]]:
    """External FIFA-points anchor candidates (Phase 2I)."""
    return [
        ("baseline", "internal_only"),
        ("effective_external_current_formula", "fifa_points_snapshot_static"),
        ("effective_external_current_formula", "fifa_points_confidence_weighted"),
        ("effective_external_current_formula", "fifa_points_disagreement_weighted"),
        ("effective_external_adjusted_form", "fifa_points_snapshot_static"),
        ("effective_external_adjusted_form", "fifa_points_confidence_weighted"),
        ("effective_external_adjusted_form", "fifa_points_disagreement_weighted"),
    ]


def all_shadow_walk_forward_candidates(
    *,
    include_defense_flip: bool = False,
) -> list[tuple[str, str]]:
    from core.power_effective_elo import EFFECTIVE_VARIANT_BASE

    candidates = serious_walk_forward_candidates(include_defense_flip=False)
    for pv in EFFECTIVE_VARIANT_BASE:
        for es in config.EFFECTIVE_ELO_STRATEGIES:
            pair = (pv, es)
            if pair not in candidates:
                candidates.append(pair)
    if include_defense_flip:
        return serious_walk_forward_candidates(include_defense_flip=True)
    return candidates
