"""Minimal offline stub for NR3 finalist spec (shadow test wiring only)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _ShadowStrengthParams:
    name: str
    scale: float = 1.0
    gap_weight: float = 0.46
    overall_weight: float = 0.06
    opponent_overall_weight: float = 0.14
    favorite_share_boost: float = 0.05
    favorite_share_boost_start: float = 0.55
    max_favorite_share: float = 0.68


@dataclass(frozen=True)
class CalibratedP1C2Spec:
    params: _ShadowStrengthParams
    family: str = "nr3_finalist"
    enabled: bool = True


def nr3_finalist_spec() -> CalibratedP1C2Spec:
    return CalibratedP1C2Spec(
        params=_ShadowStrengthParams(name="NR3_gw0.46_b0.05_oow0.14"),
        family="nr3_finalist",
    )
