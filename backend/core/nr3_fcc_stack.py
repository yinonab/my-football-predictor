"""NR3+FCC stack builder — shadow runtime only."""

from __future__ import annotations

from core.hybrid_balance_tuning import best_hb3_reference_params, p174_recovery_params
from core.priority1_options import Priority1Config


def build_hb3_stack(strength_params) -> Priority1Config:
    return Priority1Config.strength_xg_v1_balance_stack(
        strength_params,
        p174_recovery_params(),
        best_hb3_reference_params(),
    )
