#!/usr/bin/env python3
"""Compact CLI table for Global Rating Stack diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.global_ratings import build_match_diagnostics
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager

DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("Portugal (פורטוגל)", "DR Congo (קונגו)"),
    ("Spain (ספרד)", "Cape Verde (כף ורד)"),
    ("Argentina (ארגנטינה)", "France (צרפת)"),
    ("Brazil (ברזיל)", "Morocco (מרוקו)"),
    ("England (אנגליה)", "USA (ארצות הברית)"),
]


def short_name(registry_key: str) -> str:
    return registry_key.split(" (")[0]


def row_for_pair(
    dm: LiveDataManager,
    pe: TeamPowerEvaluator,
    home_input: str,
    away_input: str,
) -> str:
    home_key, home_data = dm.resolve_team(home_input)
    away_key, away_data = dm.resolve_team(away_input)
    diag = build_match_diagnostics(
        home_key,
        away_key,
        home_power=pe.calculate_composite_power(home_key),
        away_power=pe.calculate_composite_power(away_key),
        home_internal_elo=float(home_data["elo"]),
        away_internal_elo=float(away_data["elo"]),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
    )
    g = diag.gaps
    warnings = ",".join(diag.warnings) if diag.warnings else "-"
    return (
        f"{short_name(home_key):12} | {short_name(away_key):12} | "
        f"{g.internal_elo_gap:8.1f} | {g.world_elo_gap:8.1f} | "
        f"{g.power_gap:8.1f} | {g.global_strength_gap:8.4f} | {warnings}"
    )


def main() -> None:
    dm = LiveDataManager()
    pe = TeamPowerEvaluator(dm)
    header = (
        f"{'home':12} | {'away':12} | "
        f"{'int_elo':>8} | {'world_elo':>8} | "
        f"{'power':>8} | {'global':>8} | warnings"
    )
    print(header)
    print("-" * len(header))
    pairs = DEFAULT_PAIRS
    if len(sys.argv) >= 3:
        pairs = [(sys.argv[1], sys.argv[2])]
    for home, away in pairs:
        print(row_for_pair(dm, pe, home, away))


if __name__ == "__main__":
    main()
