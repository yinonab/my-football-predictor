"""Phase 2I — External rating mode resolution and FIFA-points normalization."""

from __future__ import annotations

import math
from typing import Any, Literal

import config

ExternalRatingMode = Literal[
    "none",
    "world_elo_snapshot",
    "fifa_points_snapshot",
    "current_static_world_elo",
]

LegacyWorldEloMode = Literal["none", "current_static", "snapshot_file", "proxy_from_internal"]

NORMALIZATION_METHOD = "tournament_zscore_to_internal_field"


def resolve_external_rating_mode(
    *,
    external_rating_mode: str | None = None,
    world_elo_mode: str | None = None,
) -> ExternalRatingMode:
    """Resolve mode; external_rating_mode takes precedence over legacy world_elo_mode."""
    if external_rating_mode:
        key = external_rating_mode.strip().lower()
        allowed = (
            "none",
            "world_elo_snapshot",
            "fifa_points_snapshot",
            "current_static_world_elo",
        )
        if key not in allowed:
            raise ValueError(f"Unknown external_rating_mode: {external_rating_mode}")
        return key  # type: ignore[return-value]
    legacy = (world_elo_mode or "none").strip().lower()
    mapping: dict[str, ExternalRatingMode] = {
        "none": "none",
        "current_static": "current_static_world_elo",
        "snapshot_file": "world_elo_snapshot",
        "proxy_from_internal": "none",
    }
    if legacy not in mapping:
        raise ValueError(f"Unknown world_elo_mode: {world_elo_mode}")
    return mapping[legacy]


def legacy_world_elo_mode(mode: ExternalRatingMode) -> str:
    """Map external rating mode to legacy world_elo_mode string for rows/reports."""
    reverse: dict[str, str] = {
        "none": "none",
        "world_elo_snapshot": "snapshot_file",
        "fifa_points_snapshot": "none",
        "current_static_world_elo": "current_static",
    }
    return reverse[mode]


def world_elo_mode_for_resolve(mode: ExternalRatingMode) -> str:
    """Legacy world_elo_mode passed to resolve_world_elo."""
    mapping: dict[str, str] = {
        "none": "none",
        "world_elo_snapshot": "snapshot_file",
        "fifa_points_snapshot": "none",
        "current_static_world_elo": "current_static",
    }
    return mapping[mode]


def external_rating_type_label(mode: ExternalRatingMode) -> str:
    if mode == "fifa_points_snapshot":
        return "fifa_points"
    if mode == "world_elo_snapshot":
        return "world_elo"
    if mode == "current_static_world_elo":
        return "world_elo"
    return "none"


def is_fifa_points_strategy(strategy: str) -> bool:
    return strategy.startswith("fifa_points_")


def is_external_anchor_strategy(strategy: str) -> bool:
    return is_fifa_points_strategy(strategy) or strategy.startswith("blended_")


def normalize_fifa_points_to_elo_like(
    fifa_points: float,
    dataset: str,
    *,
    internal_elos: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Map FIFA ranking points to internal-Elo-scale anchor (not World Elo)."""
    from core.external_rating_snapshots import (
        dataset_fifa_points_map,
        dataset_internal_prior_elos,
    )

    fifa_map = dataset_fifa_points_map(dataset)
    internal_map = internal_elos or dataset_internal_prior_elos(dataset)
    fifa_values = [float(v) for v in fifa_map.values() if v is not None]
    internal_values = [
        float(internal_map[t])
        for t in fifa_map
        if t in internal_map and fifa_map[t] is not None
    ]

    if not fifa_values or not internal_values:
        return {
            "original_fifa_points": fifa_points,
            "normalized_external_rating": None,
            "normalization_method": NORMALIZATION_METHOD,
            "fifa_mean": 0.0,
            "fifa_std": 0.0,
            "internal_mean": 0.0,
            "internal_std": 0.0,
        }

    fifa_mean = sum(fifa_values) / len(fifa_values)
    internal_mean = sum(internal_values) / len(internal_values)
    fifa_var = sum((v - fifa_mean) ** 2 for v in fifa_values) / len(fifa_values)
    internal_var = sum((v - internal_mean) ** 2 for v in internal_values) / len(
        internal_values
    )
    fifa_std = math.sqrt(fifa_var) if fifa_var > 1e-9 else 1.0
    internal_std = math.sqrt(internal_var) if internal_var > 1e-9 else 1.0

    z = (fifa_points - fifa_mean) / fifa_std
    normalized = internal_mean + z * internal_std

    return {
        "original_fifa_points": fifa_points,
        "normalized_external_rating": round(normalized, 1),
        "normalization_method": NORMALIZATION_METHOD,
        "fifa_mean": round(fifa_mean, 2),
        "fifa_std": round(fifa_std, 2),
        "internal_mean": round(internal_mean, 2),
        "internal_std": round(internal_std, 2),
    }


def build_fifa_normalization_context(dataset: str) -> dict[str, Any]:
    """Precompute per-team normalized FIFA anchors for a tournament dataset."""
    from core.external_rating_snapshots import dataset_fifa_points_map

    fifa_map = dataset_fifa_points_map(dataset)
    per_team: dict[str, dict[str, Any]] = {}
    for team, points in fifa_map.items():
        if points is None:
            continue
        per_team[team] = normalize_fifa_points_to_elo_like(float(points), dataset)
    return {
        "dataset": dataset,
        "normalization_method": NORMALIZATION_METHOD,
        "teams": per_team,
    }
