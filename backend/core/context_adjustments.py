"""Apply rest, travel, weather and stage modifiers to power and xG."""

from __future__ import annotations

from dataclasses import dataclass, field

import config


@dataclass
class ContextAdjustments:
    home_power_mult: float = 1.0
    away_power_mult: float = 1.0
    xg_total_delta: float = 0.0
    notes: list[str] = field(default_factory=list)


def _rest_penalty(rest_days: int | None) -> tuple[float, str | None]:
    if rest_days is None:
        return 1.0, None
    if rest_days >= 4:
        return 1.0, f"מנוחה {rest_days} ימים — ללא עונש"
    if rest_days == 3:
        return 0.99, f"מנוחה {rest_days} ימים"
    if rest_days == 2:
        return 0.96, f"מנוחה קצרה ({rest_days} ימים) — עייפות קלה"
    if rest_days <= 1:
        return 0.92, f"מנוחה {rest_days} ימים בלבד — עייפות"
    return 0.97, f"מנוחה {rest_days} ימים"


def _travel_penalty(km: float | None) -> tuple[float, str | None]:
    if km is None or km < config.TRAVEL_KM_THRESHOLD:
        return 1.0, None
    if km >= 4000:
        return 0.94, f"נסיעה {km:.0f} ק\"מ — עומס נסיעה גבוה"
    if km >= 2500:
        return 0.96, f"נסיעה {km:.0f} ק\"מ"
    return 0.98, f"נסיעה {km:.0f} ק\"מ — קל"


def _weather_xg_delta(rain_mm: float | None, temp_c: float | None) -> tuple[float, str | None]:
    delta = 0.0
    notes: list[str] = []
    if rain_mm is not None:
        if rain_mm >= 4.0:
            delta -= config.RAIN_HEAVY_XG_PENALTY
            notes.append(f"גשם כבד ({rain_mm} מ\"מ) — פחות שערים")
        elif rain_mm >= 1.0:
            delta -= config.RAIN_LIGHT_XG_PENALTY
            notes.append(f"גשם ({rain_mm} מ\"מ)")
    if temp_c is not None:
        if temp_c >= config.HEAT_TEMP_C:
            delta -= config.HEAT_XG_PENALTY
            notes.append(f"חום ({temp_c}°C)")
        elif temp_c <= config.COLD_TEMP_C:
            delta -= config.COLD_XG_PENALTY
            notes.append(f"קור ({temp_c}°C)")
    if not notes:
        return 0.0, None
    return delta, "; ".join(notes)


def compute_context_adjustments(
    *,
    home_rest_days: int | None,
    away_rest_days: int | None,
    away_travel_km: float | None,
    home_travel_km: float | None = None,
    rain_mm: float | None = None,
    temp_c: float | None = None,
    stage: str | None = None,
) -> ContextAdjustments:
    out = ContextAdjustments()

    h_rest, h_note = _rest_penalty(home_rest_days)
    a_rest, a_note = _rest_penalty(away_rest_days)
    out.home_power_mult *= h_rest
    out.away_power_mult *= a_rest
    if h_note:
        out.notes.append(f"בית: {h_note}")
    if a_note:
        out.notes.append(f"חוץ: {a_note}")

    a_trav, a_tnote = _travel_penalty(away_travel_km)
    h_trav, h_tnote = _travel_penalty(home_travel_km)
    out.away_power_mult *= a_trav
    out.home_power_mult *= h_trav
    if a_tnote:
        out.notes.append(f"חוץ: {a_tnote}")
    if h_tnote:
        out.notes.append(f"בית: {h_tnote}")

    xg_d, w_note = _weather_xg_delta(rain_mm, temp_c)
    out.xg_total_delta = xg_d
    if w_note:
        out.notes.append(w_note)

    if stage:
        lower = stage.lower()
        if "final" in lower or "semi" in lower or "quarter" in lower:
            out.notes.append(f"שלב: {stage} — משחק חשוב")
        elif "group" in lower:
            out.notes.append(f"שלב: {stage}")

    return out


def apply_xg_context_delta(
    home_xg: float,
    away_xg: float,
    xg_total_delta: float,
) -> tuple[float, float]:
    """Spread total xG adjustment proportionally across teams."""
    if abs(xg_total_delta) < 1e-6:
        return home_xg, away_xg
    total = home_xg + away_xg
    if total <= 0:
        half = abs(xg_total_delta) / 2
        return max(0.15, home_xg - half), max(0.15, away_xg - half)
    new_total = max(0.5, total + xg_total_delta)
    scale = new_total / total
    return round(home_xg * scale, 2), round(away_xg * scale, 2)
