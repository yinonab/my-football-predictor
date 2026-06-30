"""Minimal offline stub for NR3+FCC shadow test wiring only (not full P1.7B.16 prototype)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from core.priority1_options import Priority1Config


@dataclass(frozen=True)
class FavoriteConfidenceCurveParams:
    name: str = "FCC_FIXED_MONOTONIC_FAVORITE_SHARE_LIFT"
    status: str = "SHADOW_ONLY_RESEARCH"


def fcc_fixed_params() -> FavoriteConfidenceCurveParams:
    return FavoriteConfidenceCurveParams()


def build_fcc_stack(
    strength_params: Any,
    fcc_params: FavoriteConfidenceCurveParams | None = None,
) -> Priority1Config:
    """Build shadow Priority1Config with FCC params attached; offline test helper only."""
    _ = strength_params
    return replace(
        Priority1Config.baseline(),
        favorite_confidence_curve_params=fcc_params or fcc_fixed_params(),
    )
