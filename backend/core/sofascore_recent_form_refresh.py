"""Production Sofascore-only recent-form fusion cache refresh (admin-triggered)."""

from __future__ import annotations

import logging
import time
from typing import Any

import config
from core.cloud_persist import is_configured as cloud_persist_configured, push_file
from core.recent_form_fusion import (
    FUSION_CACHE_PATH,
    REGISTRY,
    TeamFusionResult,
    all_wc_registry_keys,
    build_fusion_cache_payload,
    build_team_fusion,
    load_fusion_cache,
    summarize_sofascore_fusion_coverage,
    team_fusion_result_from_cache_entry,
    write_fusion_cache_safe,
)
from data.sofascore import SofascoreClient, load_sofascore_registry_id_map

logger = logging.getLogger(__name__)


def build_sofascore_refresh_audit(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Coverage audit fields for admin refresh response."""
    summary = summarize_sofascore_fusion_coverage(payload, registry_keys=REGISTRY)
    teams = (payload or {}).get("teams") or {}
    ten_plus = 0
    under_five = 0
    refreshed_ok = 0
    for _key, entry in teams.items():
        if not isinstance(entry, dict):
            continue
        fusion = entry.get("fusion") or {}
        count = len(fusion.get("last_10_finished") or [])
        if (entry.get("provider_ids") or {}).get("sofascore") is not None:
            refreshed_ok += 1
        if count >= 10:
            ten_plus += 1
        if count < 5:
            under_five += 1

    return {
        "teams_total": len(REGISTRY),
        "teams_refreshed_with_sofascore_id": refreshed_ok,
        "teams_with_10_plus_last10": ten_plus,
        "teams_with_under_5_last10": under_five,
        "sofascore_candidate_rows": int(summary.get("sofascore_candidate_rows") or 0),
        "finished_rows": int(summary.get("finished_match_rows") or 0),
        "rows_with_has_xg": int(summary.get("matches_with_has_xg") or 0),
        "missing_mappings": list(summary.get("missing_sofascore_mappings") or []),
        "cache_last_updated_utc": (payload or {}).get("last_updated_utc"),
    }


def run_sofascore_recent_form_refresh(
    *,
    dry_run: bool = False,
    force: bool = False,
    sofascore_sleep: float = 1.0,
) -> dict[str, Any]:
    """
    Refresh fusion cache from Sofascore for all WC2026 teams.

    Equivalent to:
    refresh_recent_form_fusion_cache.py --provider sofascore --all-wc-teams --write
    """
    if not config.sofascore_enabled():
        raise ValueError("SOFASCORE_DISABLED")

    keys = all_wc_registry_keys()
    sofascore_id_map = load_sofascore_registry_id_map()
    sofascore_client = SofascoreClient(enabled=True)

    existing_payload, _ = load_fusion_cache()
    existing_teams = (existing_payload or {}).get("teams") or {}

    team_results: dict[str, TeamFusionResult] = {}
    refresh_errors: list[str] = []
    warnings: list[str] = []

    for idx, team_key in enumerate(keys):
        english = team_key.split(" (")[0]
        try:
            result = build_team_fusion(
                team_key,
                sofascore_client=sofascore_client,
                sofascore_id_map=sofascore_id_map,
                include_live_apis=True,
                include_football_data=False,
                include_api_football=False,
                include_sofascore=True,
                force_sofascore=True,
            )
            if result.coverage_count <= 0:
                preserved = team_fusion_result_from_cache_entry(
                    team_key, existing_teams.get(team_key) or {}
                )
                if preserved is not None:
                    team_results[team_key] = preserved
                    refresh_errors.append(f"{english}:preserved_existing_on_empty")
                    warnings.append(f"{english}:preserved_existing_on_empty")
                    continue
            team_results[team_key] = result
            if result.provider_availability.get("sofascore") not in ("ok",):
                status = str(result.provider_availability.get("sofascore") or "unknown")
                if status not in ("ok",):
                    warnings.append(f"{english}:sofascore_{status}")
        except Exception as exc:
            logger.warning("Sofascore refresh failed for %s: %s", english, type(exc).__name__)
            refresh_errors.append(f"{english}:{type(exc).__name__}")
            preserved = team_fusion_result_from_cache_entry(
                team_key, existing_teams.get(team_key) or {}
            )
            if preserved is not None:
                team_results[team_key] = preserved
                warnings.append(f"{english}:preserved_on_exception")

        if sofascore_sleep and idx + 1 < len(keys):
            time.sleep(sofascore_sleep)

    for team_key, entry in existing_teams.items():
        if team_key in team_results:
            continue
        preserved = team_fusion_result_from_cache_entry(team_key, entry)
        if preserved is not None:
            team_results[team_key] = preserved

    payload = build_fusion_cache_payload(team_results, refresh_errors=refresh_errors)

    cache_written = False
    write_status = "dry_run"
    cloud_persist_sync_status = "skipped_dry_run"

    if dry_run:
        audit = build_sofascore_refresh_audit(payload)
        return {
            "dry_run": True,
            "cache_written": False,
            "write_status": write_status,
            "cloud_persist_sync_status": cloud_persist_sync_status,
            "errors": refresh_errors,
            "warnings": warnings,
            **audit,
        }

    path, write_status = write_fusion_cache_safe(
        payload,
        team_results=team_results,
        force=force,
    )
    cache_written = path is not None

    if not cache_written:
        cloud_persist_sync_status = "not_attempted_write_failed"
        audit = build_sofascore_refresh_audit(existing_payload)
        return {
            "dry_run": False,
            "cache_written": False,
            "write_status": write_status,
            "cloud_persist_sync_status": cloud_persist_sync_status,
            "errors": refresh_errors,
            "warnings": warnings,
            **audit,
        }

    written_payload, _ = load_fusion_cache()
    audit = build_sofascore_refresh_audit(written_payload or payload)

    if cloud_persist_configured():
        pushed = push_file(FUSION_CACHE_PATH)
        cloud_persist_sync_status = "synced" if pushed else "sync_failed"
    else:
        cloud_persist_sync_status = "not_configured"

    return {
        "dry_run": False,
        "cache_written": True,
        "write_status": write_status,
        "cloud_persist_sync_status": cloud_persist_sync_status,
        "errors": refresh_errors,
        "warnings": warnings,
        **audit,
    }
