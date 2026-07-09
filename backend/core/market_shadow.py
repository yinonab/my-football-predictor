"""Shadow diagnostics for market-implied score matrix (Phase 3A — not wired to predict)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW
from core.market_types import MarketConsensus, MarketQualityResult, NormalizedMarketSnapshot

# RapidAPI ASIAN_HANDICAP convention (verified on Norway vs England fixture):
# - line_point is the HOME team's handicap
# - outcome_0 = home cover, outcome_1 = away cover
# Examples when away is favorite:
#   home line +0.5  => away -0.5 cover (must win)     ~ h2h away win %
#   home line -0.5  => away +0.5 protection (non-loss) ~ h2h away win + draw %

HOME_HANDICAP_FAVORITE_WIN_LINE: dict[str, str] = {
    "home": "-0.5",
    "away": "0.5",
}
HOME_HANDICAP_FAVORITE_NON_LOSS_LINE: dict[str, str] = {
    "home": "0.5",
    "away": "-0.5",
}

WIN_PRESSURE_H2H_TOLERANCE_PCT = 20.0
NON_LOSS_DRAW_TOLERANCE_PCT = 25.0


@dataclass
class MarketPressure:
    """Directional market pressure on a single axis (diagnostic only)."""

    label: str
    value_pct: float
    direction: str
    strength: str
    detail: str


@dataclass
class MarketShadowReport:
    """Read-only shadow report; does not alter model prediction output."""

    quality_band: str
    quality_score: float
    market_favorite: str
    market_favorite_side: str
    market_favorite_pct: float
    market_h2h: dict[str, float]
    totals_pressure: MarketPressure | None
    spread_pressure: MarketPressure | None
    btts_pressure: MarketPressure | None
    clean_sheet_pressure: dict[str, float]
    favorite_win_pressure: MarketPressure | None
    favorite_non_loss_pressure: MarketPressure | None
    shadow_tendency: str
    candidate_score_tendencies: list[str]
    recommended_market_weight_pct: int
    weight_explanation: str
    model_primary_score: str | None
    model_top_scores_unchanged: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def _pressure(p: MarketPressure | None) -> dict[str, Any] | None:
            if p is None:
                return None
            return {
                "label": p.label,
                "value_pct": p.value_pct,
                "direction": p.direction,
                "strength": p.strength,
                "detail": p.detail,
            }

        return {
            "quality_band": self.quality_band,
            "quality_score": round(self.quality_score, 2),
            "market_favorite": self.market_favorite,
            "market_favorite_side": self.market_favorite_side,
            "market_favorite_pct": self.market_favorite_pct,
            "market_h2h": self.market_h2h,
            "totals_pressure": _pressure(self.totals_pressure),
            "spread_pressure": _pressure(self.spread_pressure),
            "btts_pressure": _pressure(self.btts_pressure),
            "clean_sheet_pressure": self.clean_sheet_pressure,
            "favorite_win_pressure": _pressure(self.favorite_win_pressure),
            "favorite_non_loss_pressure": _pressure(self.favorite_non_loss_pressure),
            "shadow_tendency": self.shadow_tendency,
            "candidate_score_tendencies": self.candidate_score_tendencies,
            "recommended_market_weight_pct": self.recommended_market_weight_pct,
            "weight_explanation": self.weight_explanation,
            "model_primary_score": self.model_primary_score,
            "model_top_scores_unchanged": self.model_top_scores_unchanged,
            "notes": self.notes,
        }


def _strength(abs_delta: float) -> str:
    if abs_delta >= 12.0:
        return "strong"
    if abs_delta >= 5.0:
        return "moderate"
    if abs_delta >= 2.0:
        return "slight"
    return "neutral"


def _pressure_from_pct(
    label: str,
    value_pct: float,
    *,
    over_label: str = "over",
    under_label: str = "under",
    neutral_label: str = "neutral",
    detail: str = "",
) -> MarketPressure:
    delta = value_pct - 50.0
    if delta >= 2.0:
        direction = over_label
    elif delta <= -2.0:
        direction = under_label
    else:
        direction = neutral_label
    strength = _strength(abs(delta))
    return MarketPressure(
        label=label,
        value_pct=round(value_pct, 2),
        direction=direction,
        strength=strength,
        detail=detail or f"{label} at {value_pct:.1f}%",
    )


def _favorite_from_h2h(
    h2h: dict[str, float],
    *,
    home_team: str,
    away_team: str,
) -> tuple[str, str, float]:
    sides = {
        "home": h2h.get("home", 0.0),
        "draw": h2h.get("draw", 0.0),
        "away": h2h.get("away", 0.0),
    }
    side = max(sides, key=sides.get)
    pct = sides[side]
    if side == "home":
        name = home_team
    elif side == "away":
        name = away_team
    else:
        name = "draw"
    return name, side, pct


def _pick_line(consensus_map: dict[str, dict[str, float]], preferred: str) -> tuple[str, dict[str, float]] | None:
    if preferred in consensus_map:
        return preferred, consensus_map[preferred]
    if not consensus_map:
        return None
    key = sorted(consensus_map.keys(), key=lambda k: abs(float(k) - float(preferred)))[0]
    return key, consensus_map[key]


def _win_pressure_coherent(fav_pct: float, h2h_win: float, h2h_draw: float) -> bool:
    """Favorite -0.5 cover should track ML win, not win-or-draw mass."""
    non_loss_approx = h2h_win + h2h_draw
    if abs(fav_pct - non_loss_approx) < abs(fav_pct - h2h_win):
        return False
    return abs(fav_pct - h2h_win) <= WIN_PRESSURE_H2H_TOLERANCE_PCT


def _non_loss_pressure_coherent(fav_pct: float, h2h_win: float, h2h_draw: float) -> bool:
    """Favorite +0.5 protection should sit near win-or-draw, above ML win."""
    non_loss_approx = h2h_win + h2h_draw
    if fav_pct <= h2h_win + 3.0:
        return False
    return abs(fav_pct - non_loss_approx) <= NON_LOSS_DRAW_TOLERANCE_PCT


def _favorite_handicap_pressures(
    favorite_side: str,
    favorite_name: str,
    h2h: dict[str, float],
    spreads_by_line: dict[str, dict[str, float]],
) -> tuple[MarketPressure | None, MarketPressure | None, list[str]]:
    """Build favorite win (-0.5) and non-loss (+0.5) pressures using home-handicap lines."""
    notes: list[str] = []
    if favorite_side not in ("home", "away"):
        return None, None, notes

    h2h_win = h2h.get(favorite_side, 0.0)
    h2h_draw = h2h.get("draw", 0.0)
    non_loss_approx = h2h_win + h2h_draw

    win_home_line = HOME_HANDICAP_FAVORITE_WIN_LINE[favorite_side]
    non_loss_home_line = HOME_HANDICAP_FAVORITE_NON_LOSS_LINE[favorite_side]

    win_pressure: MarketPressure | None = None
    non_loss_pressure: MarketPressure | None = None

    picked_win = _pick_line(spreads_by_line, win_home_line)
    if picked_win is not None:
        line_key, line = picked_win
        fav_pct = line.get(favorite_side, 0.0)
        handicap = "-0.5"
        if line_key != win_home_line:
            notes.append(f"favorite_win_line_approximated:{line_key}")
        if _win_pressure_coherent(fav_pct, h2h_win, h2h_draw):
            win_pressure = _pressure_from_pct(
                "favorite_win",
                fav_pct,
                over_label="covers_minus_0_5",
                under_label="fails_minus_0_5",
                neutral_label="uncertain",
                detail=(
                    f"{favorite_name} -0.5 cover via home handicap {line_key}: "
                    f"{favorite_side} {fav_pct:.1f}% (h2h win {h2h_win:.1f}%)"
                ),
            )
        else:
            notes.append(
                f"favorite_win_pressure_unavailable:line {line_key} {favorite_side} "
                f"{fav_pct:.1f}% incoherent with h2h win {h2h_win:.1f}%"
            )
    else:
        notes.append("favorite_win_pressure_unavailable:line_missing")

    picked_non_loss = _pick_line(spreads_by_line, non_loss_home_line)
    if picked_non_loss is not None:
        line_key, line = picked_non_loss
        fav_pct = line.get(favorite_side, 0.0)
        if line_key != non_loss_home_line:
            notes.append(f"favorite_non_loss_line_approximated:{line_key}")
        if _non_loss_pressure_coherent(fav_pct, h2h_win, h2h_draw):
            non_loss_pressure = _pressure_from_pct(
                "favorite_non_loss",
                fav_pct,
                over_label="non_loss_covers",
                under_label="loses_or_draw_insufficient",
                neutral_label="uncertain",
                detail=(
                    f"{favorite_name} +0.5 protection via home handicap {line_key}: "
                    f"{favorite_side} {fav_pct:.1f}% (win-or-draw ~{non_loss_approx:.1f}%)"
                ),
            )
        else:
            notes.append(
                f"favorite_non_loss_pressure_unavailable:line {line_key} {favorite_side} "
                f"{fav_pct:.1f}% incoherent with win-or-draw ~{non_loss_approx:.1f}%"
            )
    else:
        notes.append("favorite_non_loss_pressure_unavailable:line_missing")

    return win_pressure, non_loss_pressure, notes


def _recommend_weight(quality: MarketQualityResult) -> tuple[int, str]:
    if quality.band == BAND_RED:
        return 30, (
            "RED band: h2h-only or insufficient families — market matrix would be too thin; "
            "cap future influence at ~30% until totals/spreads/BTTS are available."
        )
    if quality.band == BAND_YELLOW:
        return 40, (
            "YELLOW band: h2h + totals + spreads present but BTTS missing — "
            "moderate future influence (~40%) until BTTS and deeper lines are confirmed."
        )
    if quality.band == BAND_GREEN:
        weight = 60 if quality.bookmaker_count >= 6 and quality.total_line_count >= 10 else 50
        return weight, (
            f"GREEN band: full core families with multi-line totals/spreads and BTTS — "
            f"future influence candidate ~{weight}% pending matrix calibration."
        )
    return 30, "Unknown quality band — default conservative 30% cap."


def _clean_sheet_pressure(
    h2h: dict[str, float],
    btts: dict[str, float] | None,
) -> dict[str, float]:
    if not btts:
        return {"home": 0.0, "away": 0.0}
    no_btts = btts.get("no", 50.0)
    home_win = h2h.get("home", 33.0)
    away_win = h2h.get("away", 33.0)
    return {
        "home": round(no_btts * (home_win / 100.0), 2),
        "away": round(no_btts * (away_win / 100.0), 2),
    }


def _shadow_tendency_text(
    favorite_name: str,
    favorite_side: str,
    favorite_pct: float,
    totals: MarketPressure | None,
    favorite_win: MarketPressure | None,
    btts: MarketPressure | None,
    h2h: dict[str, float],
) -> str:
    parts: list[str] = []
    if favorite_side != "draw":
        parts.append(f"{favorite_name} edge")
    else:
        parts.append("draw-led market")

    if btts is not None:
        if btts.direction == "yes":
            parts.append("BTTS-leaning" if btts.strength != "strong" else "strong-BTTS")
        elif btts.direction == "no":
            parts.append("clean-sheet-leaning")

    if totals is not None:
        if totals.direction == "over":
            parts.append(f"{totals.strength}-over")
        elif totals.direction == "under":
            parts.append(f"{totals.strength}-under")

    draw_pct = h2h.get("draw", 0.0)
    if draw_pct >= 28.0:
        parts.append("draw risk")
    if favorite_win is not None and favorite_win.strength in ("slight", "neutral"):
        parts.append("close match")
    elif favorite_pct < 55.0 and favorite_side != "draw":
        parts.append("close match")

    return ", ".join(parts)


def _candidate_score_tendencies(
    favorite_side: str,
    totals: MarketPressure | None,
    btts: MarketPressure | None,
    *,
    home_team: str,
    away_team: str,
    model_sample: Mapping[str, Any],
) -> list[str]:
    over = totals is not None and totals.direction == "over"
    under = totals is not None and totals.direction == "under"
    btts_yes = btts is not None and btts.direction == "yes"
    btts_no = btts is not None and btts.direction == "no"

    if favorite_side == "away":
        pool = ["0-1", "1-2", "0-2", "1-1", "2-2", "0-0"]
        if over and btts_yes:
            pool = ["1-2", "1-1", "2-2", "0-1", "2-1"]
        elif over:
            pool = ["0-2", "1-2", "2-1", "1-1"]
        elif under and btts_no:
            pool = ["0-1", "0-0", "1-0", "0-2"]
        elif btts_yes:
            pool = ["1-2", "1-1", "2-2", "0-1"]
    elif favorite_side == "home":
        pool = ["1-0", "2-1", "2-0", "1-1", "2-2", "0-0"]
        if over and btts_yes:
            pool = ["2-1", "1-1", "2-2", "3-1", "1-2"]
        elif over:
            pool = ["2-1", "3-1", "2-0", "1-1"]
        elif under and btts_no:
            pool = ["1-0", "0-0", "0-1", "1-0"]
        elif btts_yes:
            pool = ["2-1", "1-1", "2-2", "1-2"]
    else:
        pool = ["1-1", "0-0", "2-2", "1-0", "0-1"]

    primary = model_sample.get("primary_score")
    if isinstance(primary, str) and primary:
        pool = [primary] + [s for s in pool if s != primary]
    return pool[:5]


def _extract_model_fields(model_sample: Mapping[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    primary = model_sample.get("primary_score")
    primary_str = str(primary) if primary is not None else None
    top = model_sample.get("top_scores") or []
    top_copy: list[dict[str, Any]] = []
    if isinstance(top, list):
        for item in top:
            if isinstance(item, dict):
                top_copy.append(copy.deepcopy(item))
    return primary_str, top_copy


def build_market_shadow_report(
    model_sample: Mapping[str, Any],
    consensus: MarketConsensus,
    quality: MarketQualityResult,
    snapshot: NormalizedMarketSnapshot | None = None,
) -> MarketShadowReport:
    """Build shadow diagnostics without mutating model_sample."""
    model_copy = copy.deepcopy(dict(model_sample))
    primary_score, top_scores_snapshot = _extract_model_fields(model_copy)

    home_team = snapshot.home_team if snapshot else "Home"
    away_team = snapshot.away_team if snapshot else "Away"

    h2h = dict(consensus.h2h or {"home": 33.33, "draw": 33.33, "away": 33.34})
    favorite_name, favorite_side, favorite_pct = _favorite_from_h2h(
        h2h, home_team=home_team, away_team=away_team
    )

    totals_pressure: MarketPressure | None = None
    picked_totals = _pick_line(consensus.totals_by_line, "2.5")
    if picked_totals is not None:
        line_key, line = picked_totals
        over_pct = line.get("over", 50.0)
        totals_pressure = _pressure_from_pct(
            f"totals_{line_key}",
            over_pct,
            over_label="over",
            under_label="under",
            detail=f"totals {line_key}: over {over_pct:.1f}% / under {line.get('under', 0):.1f}%",
        )

    spread_pressure: MarketPressure | None = None
    if favorite_side in ("home", "away"):
        win_home_line = HOME_HANDICAP_FAVORITE_WIN_LINE[favorite_side]
        picked_spread = _pick_line(consensus.spreads_by_line, win_home_line)
        if picked_spread is not None:
            line_key, line = picked_spread
            fav_pct = line.get(favorite_side, 50.0)
            spread_pressure = _pressure_from_pct(
                f"spread_home_line_{line_key}",
                fav_pct,
                over_label=f"{favorite_side}_minus_0_5_cover",
                under_label="opponent_cover",
                detail=(
                    f"home handicap {line_key} ({favorite_name} -0.5 cover): "
                    f"home {line.get('home', 0):.1f}% / away {line.get('away', 0):.1f}%"
                ),
            )

    btts_pressure: MarketPressure | None = None
    if consensus.btts:
        yes_pct = consensus.btts.get("yes", 50.0)
        btts_pressure = _pressure_from_pct(
            "btts",
            yes_pct,
            over_label="yes",
            under_label="no",
            detail=f"BTTS yes {yes_pct:.1f}% / no {consensus.btts.get('no', 0):.1f}%",
        )

    clean_sheet = _clean_sheet_pressure(h2h, consensus.btts)
    favorite_win, favorite_non_loss, handicap_notes = _favorite_handicap_pressures(
        favorite_side,
        favorite_name,
        h2h,
        consensus.spreads_by_line,
    )

    weight_pct, weight_expl = _recommend_weight(quality)
    tendency = _shadow_tendency_text(
        favorite_name,
        favorite_side,
        favorite_pct,
        totals_pressure,
        favorite_win,
        btts_pressure,
        h2h,
    )
    candidates = _candidate_score_tendencies(
        favorite_side,
        totals_pressure,
        btts_pressure,
        home_team=home_team,
        away_team=away_team,
        model_sample=model_copy,
    )

    notes: list[str] = []
    if quality.notes:
        notes.extend(quality.notes)
    notes.extend(handicap_notes)
    notes.append("shadow_only_no_predict_mutation")
    notes.append("asian_handicap_line_point_is_home_perspective")

    return MarketShadowReport(
        quality_band=quality.band,
        quality_score=quality.score,
        market_favorite=favorite_name,
        market_favorite_side=favorite_side,
        market_favorite_pct=round(favorite_pct, 2),
        market_h2h=h2h,
        totals_pressure=totals_pressure,
        spread_pressure=spread_pressure,
        btts_pressure=btts_pressure,
        clean_sheet_pressure=clean_sheet,
        favorite_win_pressure=favorite_win,
        favorite_non_loss_pressure=favorite_non_loss,
        shadow_tendency=tendency,
        candidate_score_tendencies=candidates,
        recommended_market_weight_pct=weight_pct,
        weight_explanation=weight_expl,
        model_primary_score=primary_score,
        model_top_scores_unchanged=top_scores_snapshot,
        notes=notes,
    )
