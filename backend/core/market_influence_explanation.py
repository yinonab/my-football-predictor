"""Phase 6C — user-facing explanation text when market influence is applied."""

from __future__ import annotations

from typing import Any, Literal

from core.market_event_map import normalize_team_for_event_map
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW

OutcomeKey = Literal["home_win", "draw", "away_win"]

_SIGNAL_LABELS: dict[str, str] = {
    BAND_GREEN: "Strong market signal",
    BAND_YELLOW: "Partial market signal",
    BAND_RED: "Weak market signal",
}


def _display_team(name: str) -> str:
    return normalize_team_for_event_map(name)


def build_market_influence_explanation(
    *,
    home_team: str,
    away_team: str,
    quality_band: str,
    influence_weight_pct: int,
    selected_score: str,
    outcome: OutcomeKey,
) -> dict[str, Any]:
    """Build deterministic user-facing explanation; only for applied influence."""
    home = _display_team(home_team)
    away = _display_team(away_team)
    band = str(quality_band or "").strip().upper()
    weight = max(0, min(100, int(influence_weight_pct)))
    score = str(selected_score or "").strip()
    signal_label = _SIGNAL_LABELS.get(band, "Partial market signal")

    title = "Market-adjusted prediction"
    influence_label = f"{weight}% market influence"
    selected_score_label = f"Selected market-adjusted score: {score}"

    if outcome == "draw":
        if band == BAND_YELLOW:
            summary = (
                "Live market signals suggested a more balanced match. "
                "Market data was available but incomplete, so the adjustment was limited "
                "and stayed closer to a narrow result."
            )
        else:
            summary = (
                "Live market signals suggested a more balanced match, "
                "so the prediction stayed closer to a narrow result."
            )
        details = [
            f"Signal strength: {signal_label.lower()}.",
            f"The exact-score blend used {weight}% market weight.",
            f"Market-aligned narrow result: {score}.",
        ]
    elif outcome == "away_win":
        if band == BAND_GREEN:
            summary = (
                f"Live market signals strengthened {away} as the likely winner. "
                f"The market points to an {away} advantage, but not a completely one-sided match, "
                f"so the prediction was adjusted toward a realistic {score} away win."
            )
        elif band == BAND_YELLOW:
            summary = (
                f"Live market signals moderately favored {away}. "
                f"Market data was available but incomplete, so the adjustment was limited "
                f"toward a {score} away win."
            )
        else:
            summary = (
                f"Limited market signals slightly favored {away}. "
                f"The prediction was cautiously adjusted toward {score}."
            )
        details = [
            f"Market quality: {signal_label.lower()}.",
            f"The exact-score blend used {weight}% market weight.",
            f"Top market-aligned result: {score}.",
        ]
    else:  # home_win
        if band == BAND_GREEN:
            summary = (
                f"Live market signals strengthened {home} as the likely winner. "
                f"The market points to a {home} advantage, but not a completely one-sided match, "
                f"so the prediction was adjusted toward a realistic {score} home win."
            )
        elif band == BAND_YELLOW:
            summary = (
                f"Live market signals moderately favored {home}. "
                f"Market data was available but incomplete, so the adjustment was limited "
                f"toward a {score} home win."
            )
        else:
            summary = (
                f"Limited market signals slightly favored {home}. "
                f"The prediction was cautiously adjusted toward {score}."
            )
        details = [
            f"Market quality: {signal_label.lower()}.",
            f"The exact-score blend used {weight}% market weight.",
            f"Top market-aligned result: {score}.",
        ]

    return {
        "title": title,
        "summary": summary,
        "signal_label": signal_label,
        "influence_label": influence_label,
        "selected_score_label": selected_score_label,
        "details": details,
    }
