"""Phase 4A — shadow-only market diagnostics API adapter (not wired to predict)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from core.market_matrix_shadow import calibrate_market_matrix_shadow
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_shadow import build_market_shadow_report
from core.market_types import NormalizedMarketSnapshot

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

ALLOWED_MARKET_FIXTURES: frozenset[str] = frozenset(
    {
        "rapidapi_odds_feed_norway_england.json",
    }
)

DIAGNOSTIC_ONLY_NOTE = "diagnostic_only_not_used_for_prediction"


class MarketShadowApiError(ValueError):
    """Invalid market shadow diagnostics request."""


def _validate_fixture_filename(name: str) -> str:
    if not name or name != Path(name).name:
        raise MarketShadowApiError("invalid_fixture_filename")
    if "/" in name or "\\" in name or ".." in name:
        raise MarketShadowApiError("invalid_fixture_filename")
    if name not in ALLOWED_MARKET_FIXTURES:
        raise MarketShadowApiError("fixture_not_allowlisted")
    return name


def _load_market_snapshot(
    *,
    market_fixture: str | None,
    inline_market: Mapping[str, Any] | None,
) -> tuple[NormalizedMarketSnapshot, str | None]:
    has_fixture = bool(market_fixture)
    has_inline = inline_market is not None
    if has_fixture and has_inline:
        raise MarketShadowApiError("exactly_one_market_source_required")
    if not has_fixture and not has_inline:
        raise MarketShadowApiError("market_source_required")

    if market_fixture:
        filename = _validate_fixture_filename(market_fixture.strip())
        path = (FIXTURES_DIR / filename).resolve()
        if FIXTURES_DIR.resolve() not in path.parents or not path.is_file():
            raise MarketShadowApiError("fixture_not_found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return parse_rapidapi_odds_feed_audit(payload), filename

    return parse_rapidapi_odds_feed_audit(dict(inline_market)), None


def build_market_shadow_diagnostics(
    *,
    home_team: str,
    away_team: str,
    model_score_matrix: Mapping[str, float],
    model_primary_score: str | None,
    model_top_scores: list[Mapping[str, Any]],
    market_fixture: str | None = None,
    inline_market: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build diagnostic-only shadow report; never mutates inputs or calls network."""
    if not home_team.strip() or not away_team.strip():
        raise MarketShadowApiError("home_team_and_away_team_required")

    matrix_before = copy.deepcopy(dict(model_score_matrix))
    top_scores_before = copy.deepcopy(model_top_scores)
    primary_before = model_primary_score

    matrix_work = copy.deepcopy(matrix_before)

    snapshot, source_fixture = _load_market_snapshot(
        market_fixture=market_fixture,
        inline_market=inline_market,
    )
    consensus, quality = build_snapshot_pipeline(snapshot)

    model_sample = {
        "primary_score": model_primary_score,
        "top_scores": copy.deepcopy(model_top_scores),
    }
    shadow = build_market_shadow_report(
        model_sample,
        consensus,
        quality,
        snapshot=snapshot,
    )
    matrix_result = calibrate_market_matrix_shadow(matrix_work, consensus, quality)

    if dict(model_score_matrix) != matrix_before:
        raise MarketShadowApiError("model_score_matrix_mutated")
    if model_primary_score != primary_before:
        raise MarketShadowApiError("model_primary_score_mutated")
    if list(model_top_scores) != top_scores_before:
        raise MarketShadowApiError("model_top_scores_mutated")

    shadow_dict = shadow.to_dict()
    matrix_dict = matrix_result.to_dict()

    effective_movement = {
        "h2h": matrix_dict["effective_h2h_movement"],
        "over_2_5": matrix_dict["effective_over_2_5_movement"],
        "btts": matrix_dict["effective_btts_movement"],
        "favorite_side": matrix_dict["effective_favorite_side_movement"],
    }

    warnings = list(matrix_dict.get("warnings") or [])
    notes = [
        DIAGNOSTIC_ONLY_NOTE,
        "static_fixture_no_live_provider_fetch",
    ]

    return {
        "home_team": home_team.strip(),
        "away_team": away_team.strip(),
        "quality_band": shadow_dict["quality_band"],
        "quality_score": shadow_dict["quality_score"],
        "market_favorite": shadow_dict["market_favorite"],
        "market_favorite_side": shadow_dict["market_favorite_side"],
        "market_favorite_pct": shadow_dict["market_favorite_pct"],
        "market_h2h": shadow_dict["market_h2h"],
        "totals_pressure": shadow_dict["totals_pressure"],
        "spread_pressure": shadow_dict["spread_pressure"],
        "btts_pressure": shadow_dict["btts_pressure"],
        "shadow_tendency": shadow_dict["shadow_tendency"],
        "requested_shadow_weight_pct": matrix_dict["requested_shadow_weight_pct"],
        "effective_movement": effective_movement,
        "shadow_top_scores": matrix_dict["top_scores_after"],
        "implied_1x2_before": matrix_dict["implied_1x2_before"],
        "implied_1x2_after": matrix_dict["implied_1x2_after"],
        "warnings": warnings,
        "notes": notes,
        "source_fixture": source_fixture,
        "model_primary_score_unchanged": model_primary_score,
        "model_top_scores_unchanged": shadow_dict["model_top_scores_unchanged"],
    }


def try_build_predict_market_shadow_diagnostics(
    *,
    server_enabled: bool,
    include_requested: bool,
    home_team: str,
    away_team: str,
    model_score_matrix: Mapping[str, float] | None,
    model_primary_score: str | None,
    model_top_scores: list[Mapping[str, Any]],
    market_fixture: str | None = None,
    inline_market: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append-only shadow diagnostics for /api/predict; never raises to caller."""
    if not server_enabled or not include_requested:
        return None
    if not model_score_matrix:
        return None
    if not market_fixture and inline_market is None:
        return None
    try:
        return build_market_shadow_diagnostics(
            home_team=home_team,
            away_team=away_team,
            model_score_matrix=model_score_matrix,
            model_primary_score=model_primary_score,
            model_top_scores=model_top_scores,
            market_fixture=market_fixture,
            inline_market=inline_market,
        )
    except MarketShadowApiError:
        return None
