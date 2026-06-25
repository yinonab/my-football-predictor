"""Recent-form provider transparency for /api/predict diagnostics (read-only)."""

from __future__ import annotations

from typing import Any, Literal

from core.recent_form_fusion import get_fusion_team_entry, load_fusion_cache
from core.recent_scoring_form import get_recent_scoring_form

ConfidenceBucket = Literal[
    "high", "medium", "low", "unavailable", "mixed", "unknown"
]

_PROVIDER_PRIORITY = (
    "sofascore_recent_form",
    "football_data_recent_form",
    "api_football_recent_form",
    "recent_form_fusion_cache",
    "recent_form_cache_football_data",
    "bundled_wc2026",
    "static",
)


def _merge_source_mix(*mixes: dict[str, int] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for mix in mixes:
        if not mix:
            continue
        for key, count in mix.items():
            out[str(key)] = out.get(str(key), 0) + int(count)
    return out


def _pick_primary_provider(source_mix: dict[str, int]) -> str:
    if not source_mix:
        return "unavailable"
    ranked = sorted(
        source_mix.items(),
        key=lambda item: (
            -item[1],
            _PROVIDER_PRIORITY.index(item[0])
            if item[0] in _PROVIDER_PRIORITY
            else 99,
        ),
    )
    top_key, top_count = ranked[0]
    if top_key in ("sofascore_recent_form",):
        return "sofascore_recent_form"
    if top_key.startswith("bundled_") or top_key == "static":
        return "static/offline fallback"
    if top_count <= 0:
        return "unavailable"
    return top_key


def _confidence_bucket(
    home_quality: str | None,
    away_quality: str | None,
    *,
    home_available: bool,
    away_available: bool,
) -> ConfidenceBucket:
    if not home_available and not away_available:
        return "unavailable"
    qualities = [q for q in (home_quality, away_quality) if q and q != "unavailable"]
    if not qualities:
        return "unknown"
    if len(set(qualities)) > 1:
        return "mixed"
    return qualities[0]  # type: ignore[return-value]


def build_recent_form_provider_diagnostics(
    home_team_key: str,
    away_team_key: str,
) -> dict[str, Any]:
    """Offline read of fusion cache + scoring form — no live API calls."""
    home_entry = get_fusion_team_entry(home_team_key)
    away_entry = get_fusion_team_entry(away_team_key)

    home_fusion = (home_entry or {}).get("fusion") or {}
    away_fusion = (away_entry or {}).get("fusion") or {}

    home_mix = dict(home_fusion.get("source_mix") or {})
    away_mix = dict(away_fusion.get("source_mix") or {})
    source_mix = _merge_source_mix(home_mix, away_mix)

    home_scoring = get_recent_scoring_form(home_team_key)
    away_scoring = get_recent_scoring_form(away_team_key)

    if not source_mix:
        source_mix = _merge_source_mix(
            home_scoring.source_breakdown,
            away_scoring.source_breakdown,
        )

    primary_provider = _pick_primary_provider(source_mix)
    if not source_mix and home_scoring.recent_form_available:
        primary_provider = home_scoring.recent_form_source or "static/offline fallback"

    payload, cache_err = load_fusion_cache()
    cache_last_updated_utc = None
    if payload:
        cache_last_updated_utc = payload.get("last_updated_utc")

    teams_with_provider_ids: dict[str, dict[str, Any]] = {}
    for team_key, entry in (
        (home_team_key, home_entry),
        (away_team_key, away_entry),
    ):
        if not entry:
            continue
        provider_ids = entry.get("provider_ids") or {}
        if provider_ids:
            teams_with_provider_ids[team_key] = dict(provider_ids)

    confidence_bucket = _confidence_bucket(
        home_fusion.get("coverage_quality"),
        away_fusion.get("coverage_quality"),
        home_available=home_scoring.recent_form_available,
        away_available=away_scoring.recent_form_available,
    )

    notes: list[str] = []
    if cache_err:
        notes.append(f"fusion_cache:{cache_err}")
    elif not payload:
        notes.append("fusion_cache:missing")
    elif source_mix.get("sofascore_recent_form", 0) > 0:
        notes.append(
            f"Recent form includes {source_mix['sofascore_recent_form']} "
            "Sofascore rows in fused last-10 window"
        )
    elif primary_provider == "static/offline fallback":
        notes.append("Recent form derived from static/bundled offline history")
    elif primary_provider == "unavailable":
        notes.append("No recent-form fusion coverage for one or both teams")

    sofascore_rows = int(source_mix.get("sofascore_recent_form") or 0)
    if sofascore_rows > 0:
        primary_provider = "sofascore_recent_form"

    return {
        "source_mix": source_mix,
        "primary_provider": primary_provider,
        "cache_last_updated_utc": cache_last_updated_utc,
        "teams_with_provider_ids": teams_with_provider_ids,
        "confidence_bucket": confidence_bucket,
        "provider_notes": notes,
    }
