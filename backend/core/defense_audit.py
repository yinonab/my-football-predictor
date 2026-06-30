"""Defense component semantics audit for Power / Z-score candidates."""

from __future__ import annotations

from typing import Any, Literal

DefenseSign = Literal["subtract", "add"]

# Evidence-backed semantics (see team_ratings.py + database.py).
DEFENSE_RAW_MEANING = (
    "Higher raw defense (0–1) = stronger defensive profile: fewer goals conceded relative "
    "to league average (defense_ratio = league_avg_gf / avg_ga)."
)

DEFENSE_PRODUCTION_SIGN = "subtract"
DEFENSE_PRODUCTION_FORMULA = "Power -= WEIGHT_DEFENSE × defense × 1000"

DEFENSE_SEMANTIC_NOTE = (
    "Production subtracts defense even though raw defense increases with stronger defensive "
    "records. Effect: higher defense lowers composite Power (counter-intuitive vs attack)."
)


def defense_audit_summary() -> dict[str, Any]:
    """Static audit payload for diagnostics and reports."""
    return {
        "defense_raw_meaning": DEFENSE_RAW_MEANING,
        "defense_power_sign": DEFENSE_PRODUCTION_SIGN,
        "defense_effect_on_power": (
            "Higher raw defense → lower Power contribution in production formula "
            "(subtracted term). Strong defenders are penalized unless sign is flipped."
        ),
        "production_formula": DEFENSE_PRODUCTION_FORMULA,
        "semantic_note": DEFENSE_SEMANTIC_NOTE,
        "derivation_sources": [
            "backend/core/team_power.py (subtract in calculate_composite_power)",
            "backend/core/team_ratings.py (defense_ratio = league_avg_gf / avg_ga)",
            "backend/data/database.py (compute_derived_metrics from Elo)",
        ],
        "zscore_variants": {
            "zscore_defense_current_sign": "Matches production: subtract DefenseZ",
            "zscore_defense_flipped_sign": "Candidate: add DefenseZ (aligns strength semantics)",
        },
    }


def defense_diagnostics_block(*, zscore_sign: DefenseSign = "subtract") -> dict[str, Any]:
    base = defense_audit_summary()
    base["zscore_defense_sign"] = zscore_sign
    base["zscore_defense_effect"] = (
        "DefenseZ subtracted from weighted PowerZ"
        if zscore_sign == "subtract"
        else "DefenseZ added to weighted PowerZ (flipped candidate)"
    )
    return base
