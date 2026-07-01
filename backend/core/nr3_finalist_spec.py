"""NR3 finalist strength spec — runtime-safe (shadow sidecar only)."""

from __future__ import annotations

from dataclasses import dataclass

from core.strength_based_xg_generator import StrengthXgParams, p1c2_shadow_params


@dataclass(frozen=True)
class CalibratedP1C2Spec:
    params: StrengthXgParams
    family: str
    enabled: bool = True


def nr3_finalist_spec() -> CalibratedP1C2Spec:
    base = p1c2_shadow_params()
    return CalibratedP1C2Spec(
        params=StrengthXgParams(
            name="NR3_gw0.46_b0.05_oow0.14",
            scale=base.scale,
            gap_weight=0.46,
            overall_weight=0.06,
            opponent_overall_weight=0.14,
            favorite_share_boost=0.05,
            favorite_share_boost_start=0.55,
            max_favorite_share=0.68,
            use_attack_defense=base.use_attack_defense,
            use_overall_power=base.use_overall_power,
            use_gap=base.use_gap,
            min_side=base.min_side,
            max_side=base.max_side,
            min_total=base.min_total,
            max_total=base.max_total,
            signal_mode=base.signal_mode,
        ),
        family="nr3_finalist",
    )
