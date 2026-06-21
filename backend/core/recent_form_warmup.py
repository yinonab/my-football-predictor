"""Phase 4R.5 — Admin-only recent-form fusion cache warmup with request budget."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import config
from core.api_football_recent_form import (
    APIF_ACCOUNT_SUSPENDED,
    APIF_ERROR_KEY_MISSING,
    APIF_ERROR_RATE_LIMIT,
    ApiFootballRecentFormClient,
    ApiFootballRequestError,
)
from core.cloud_persist import is_configured as cloud_persist_configured, push_file
from core.football_data_recent_form import discover_football_data_team_ids
from core.recent_form_fusion import (
    FUSION_CACHE_PATH,
    TeamFusionResult,
    build_fusion_cache_payload,
    build_team_fusion,
    cache_age_hours,
    load_fusion_cache,
    resolve_cli_team_registry_keys,
    team_fusion_result_from_cache_entry,
    write_fusion_cache_safe,
)
from core.recent_form_shadow import load_fusion_recent_form_bundle
from data.football_data import FootballDataClient

logger = logging.getLogger(__name__)

ProviderStatus = Literal[
    "ok",
    "suspended",
    "rate_limited",
    "auth_error",
    "not_configured",
    "error",
    "disabled",
    "budget_exhausted",
    "stopped",
]

FATAL_APIF_CATEGORIES = frozenset(
    {
        APIF_ACCOUNT_SUSPENDED,
        APIF_ERROR_RATE_LIMIT,
        APIF_ERROR_KEY_MISSING,
        "APIF_HTTP_401",
        "APIF_HTTP_403",
    }
)


@dataclass
class RequestBudget:
    max_requests: int
    used: int = 0
    stopped_due_to_budget: bool = False

    def consume(self, count: int = 1) -> bool:
        if self.stopped_due_to_budget:
            return False
        if self.used + count > self.max_requests:
            self.stopped_due_to_budget = True
            return False
        self.used += count
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_requests": self.max_requests,
            "estimated_used": self.used,
            "stopped_due_to_budget": self.stopped_due_to_budget,
        }


@dataclass
class WarmupTeamReport:
    status: str
    matches_before: int = 0
    matches_after: int = 0
    coverage_quality_before: str = "unavailable"
    coverage_quality_after: str = "unavailable"
    source_mix: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "matches_before": self.matches_before,
            "matches_after": self.matches_after,
            "coverage_quality_before": self.coverage_quality_before,
            "coverage_quality_after": self.coverage_quality_after,
            "source_mix": dict(self.source_mix),
            "warnings": list(self.warnings),
            "reason_codes": list(self.reason_codes),
        }


class BudgetedApiFootballClient(ApiFootballRecentFormClient):
    """API-Football client that respects a shared request budget and fatal-error stop."""

    def __init__(self, budget: RequestBudget, *, sleep_seconds: float | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.budget = budget
        self.stop_reason: str | None = None
        if sleep_seconds is not None:
            self.sleep_seconds = sleep_seconds

    def request_raw(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, ApiFootballRequestError | None]:
        if self.stop_reason:
            return None, ApiFootballRequestError("APIF_STOPPED", self.stop_reason)
        if not self.budget.consume(1):
            self.stop_reason = "APIF_BUDGET"
            return None, ApiFootballRequestError("APIF_BUDGET", "request budget exhausted")
        payload, err = super().request_raw(path, params)
        if err is not None and err.category in FATAL_APIF_CATEGORIES:
            self.stop_reason = err.category
        return payload, err


def verify_admin_token(token: str | None) -> bool:
    expected = config.recent_form_warmup_admin_token()
    if not expected:
        return False
    if not token:
        return False
    return token.strip() == expected


def _provider_status_apif(client: BudgetedApiFootballClient | None) -> ProviderStatus:
    if not config.api_football_recent_form_enabled():
        return "not_configured"
    if client is None:
        return "not_configured"
    if client.stop_reason == "APIF_BUDGET" or client.budget.stopped_due_to_budget:
        return "budget_exhausted"
    if client.stop_reason == APIF_ACCOUNT_SUSPENDED:
        return "suspended"
    if client.stop_reason == APIF_ERROR_RATE_LIMIT:
        return "rate_limited"
    if client.stop_reason in {APIF_ERROR_KEY_MISSING, "APIF_HTTP_401", "APIF_HTTP_403"}:
        return "auth_error"
    if client.stop_reason:
        return "stopped"
    if client.last_error and client.last_error.category in FATAL_APIF_CATEGORIES:
        cat = client.last_error.category
        if cat == APIF_ACCOUNT_SUSPENDED:
            return "suspended"
        if cat == APIF_ERROR_RATE_LIMIT:
            return "rate_limited"
        if cat in {APIF_ERROR_KEY_MISSING, "APIF_HTTP_401", "APIF_HTTP_403"}:
            return "auth_error"
        return "error"
    return "ok"


def _provider_status_football_data() -> ProviderStatus:
    if not config.recent_form_api_enabled():
        return "not_configured"
    return "ok"


def _team_entry_snapshot(entry: dict[str, Any] | None) -> tuple[int, str]:
    if not entry:
        return 0, "unavailable"
    fusion = entry.get("fusion") or {}
    return int(fusion.get("coverage_count") or 0), str(fusion.get("coverage_quality") or "unavailable")


def _team_is_fresh(entry: dict[str, Any] | None, payload: dict[str, Any] | None) -> bool:
    if not entry or not payload:
        return False
    count, quality = _team_entry_snapshot(entry)
    if count <= 0 or quality == "unavailable":
        return False
    age = cache_age_hours(payload)
    if age is None:
        return False
    return age < float(config.RECENT_FORM_WARMUP_MIN_REFRESH_INTERVAL_HOURS)


def _coverage_buckets(payload: dict[str, Any] | None) -> dict[str, int]:
    buckets = {"high": 0, "medium": 0, "low": 0, "unavailable": 0}
    if not payload:
        return buckets
    for entry in (payload.get("teams") or {}).values():
        if not isinstance(entry, dict):
            continue
        quality = str((entry.get("fusion") or {}).get("coverage_quality") or "unavailable")
        if quality not in buckets:
            quality = "unavailable"
        buckets[quality] += 1
    return buckets


def build_recent_form_status() -> dict[str, Any]:
    """Read-only fusion cache / provider status (no external API calls)."""
    payload, cache_error = load_fusion_cache()
    rows_meta: dict[str, Any] = {}
    total_rows = 0
    if payload:
        from core.recent_form_fusion import load_fusion_cache_rows

        rows, rows_meta = load_fusion_cache_rows()
        total_rows = len(rows)

    warnings: list[str] = []
    if cache_error:
        warnings.append(str(cache_error))
    if payload and cache_age_hours(payload) is not None:
        if cache_age_hours(payload) > float(config.RECENT_FORM_CACHE_TTL_HOURS):
            warnings.append("FUSION_CACHE_STALE")

    return {
        "cache_exists": payload is not None,
        "cache_path": str(FUSION_CACHE_PATH.name),
        "cache_error": cache_error,
        "last_updated_utc": (payload or {}).get("last_updated_utc"),
        "cache_age_hours": cache_age_hours(payload) if payload else None,
        "team_count": len((payload or {}).get("teams") or {}),
        "total_normalized_rows": total_rows,
        "coverage_buckets": _coverage_buckets(payload),
        "provider_configured": {
            "api_football": config.api_football_recent_form_enabled(),
            "football_data": config.recent_form_api_enabled(),
        },
        "cloud_persist_configured": cloud_persist_configured(),
        "flags": {
            "RECENT_FORM_SHADOW_ENABLED": config.RECENT_FORM_SHADOW_ENABLED,
            "RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED": config.RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED,
            "RECENT_FORM_AFFECTS_SCORELINE": config.RECENT_FORM_AFFECTS_SCORELINE,
            "RECENT_FORM_WARMUP_ENABLED": config.RECENT_FORM_WARMUP_ENABLED,
        },
        "warmup_available": config.recent_form_warmup_enabled(),
        "warnings": warnings,
        "cache_row_meta": rows_meta,
    }


def build_recent_form_team_status(team: str) -> dict[str, Any] | None:
    """Read-only per-team diagnostics (no external API calls)."""
    keys = resolve_cli_team_registry_keys([team])
    if not keys:
        return None
    team_key = keys[0]
    bundle = load_fusion_recent_form_bundle(team_key.split(" (")[0])
    scoring = bundle.scoring
    return {
        "team": team_key.split(" (")[0],
        "registry_key": team_key,
        "matches_found": scoring.matches_found,
        "requested_match_count": scoring.requested_match_count,
        "latest_match_date": bundle.latest_match_date,
        "coverage_quality": bundle.coverage_quality,
        "source_mix": dict(bundle.source_mix),
        "competition_mix": dict(bundle.competition_mix),
        "recent_form_available": scoring.recent_form_available,
        "recent_form_confidence": scoring.recent_form_confidence,
        "last_10_scored_rate": scoring.last_10_scored_rate,
        "last_10_goals_for_avg": scoring.last_10_goals_for_avg,
        "last_10_goals_against_avg": scoring.last_10_goals_against_avg,
        "failed_to_score_rate": scoring.last_10_failed_to_score_rate,
        "support_level": bundle.support_level,
        "warnings": list(bundle.warnings),
        "reason_codes": list(bundle.reason_codes),
    }


def run_recent_form_warmup(
    *,
    teams: list[str],
    max_requests: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Targeted fusion refresh with request budget and per-team reporting."""
    if not config.recent_form_warmup_enabled():
        raise ValueError("WARMUP_DISABLED")

    if not teams:
        raise ValueError("TEAMS_REQUIRED")

    max_teams = config.RECENT_FORM_WARMUP_MAX_TEAMS
    if len(teams) > max_teams:
        raise ValueError(f"TOO_MANY_TEAMS:max={max_teams}")

    registry_keys = resolve_cli_team_registry_keys(teams)
    if not registry_keys:
        raise ValueError("TEAMS_UNRESOLVED")

    budget = RequestBudget(max_requests=max_requests or config.RECENT_FORM_WARMUP_DEFAULT_MAX_REQUESTS)
    apif_client: BudgetedApiFootballClient | None = None
    if config.api_football_recent_form_enabled():
        apif_client = BudgetedApiFootballClient(
            budget,
            sleep_seconds=config.RECENT_FORM_WARMUP_SLEEP_SECONDS,
        )

    fd_client = FootballDataClient() if config.recent_form_api_enabled() else None
    id_map: dict[str, int] = {}
    if fd_client and budget.consume(1):
        id_map, _, _ = discover_football_data_team_ids(fd_client)

    existing_payload, _ = load_fusion_cache()
    existing_teams = (existing_payload or {}).get("teams") or {}

    refreshed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    team_reports: dict[str, WarmupTeamReport] = {}
    team_results: dict[str, TeamFusionResult] = {}
    refresh_errors: list[str] = []

    for team_key in registry_keys:
        english = team_key.split(" (")[0]
        prior_entry = existing_teams.get(team_key)
        before_count, before_quality = _team_entry_snapshot(prior_entry)

        if not force and _team_is_fresh(prior_entry, existing_payload):
            skipped.append(english)
            team_reports[english] = WarmupTeamReport(
                status="skipped_fresh",
                matches_before=before_count,
                matches_after=before_count,
                coverage_quality_before=before_quality,
                coverage_quality_after=before_quality,
                source_mix=dict((prior_entry or {}).get("fusion", {}).get("source_mix") or {}),
                reason_codes=["WARMUP_SKIPPED_FRESH"],
            )
            preserved = team_fusion_result_from_cache_entry(team_key, prior_entry or {})
            if preserved:
                team_results[team_key] = preserved
            continue

        if apif_client and apif_client.stop_reason:
            failed.append(english)
            team_reports[english] = WarmupTeamReport(
                status="failed",
                matches_before=before_count,
                matches_after=before_count,
                coverage_quality_before=before_quality,
                coverage_quality_after=before_quality,
                reason_codes=[apif_client.stop_reason or "APIF_STOPPED"],
            )
            preserved = team_fusion_result_from_cache_entry(team_key, prior_entry or {})
            if preserved:
                team_results[team_key] = preserved
            continue

        if budget.stopped_due_to_budget:
            failed.append(english)
            team_reports[english] = WarmupTeamReport(
                status="failed",
                matches_before=before_count,
                matches_after=before_count,
                coverage_quality_before=before_quality,
                coverage_quality_after=before_quality,
                reason_codes=["WARMUP_BUDGET_EXHAUSTED"],
            )
            preserved = team_fusion_result_from_cache_entry(team_key, prior_entry or {})
            if preserved:
                team_results[team_key] = preserved
            continue

        try:
            result = build_team_fusion(
                team_key,
                fd_client=fd_client,
                apif_client=apif_client,
                id_map=id_map,
                include_live_apis=True,
            )
        except Exception as exc:
            logger.warning("Warmup fetch failed for %s: %s", english, type(exc).__name__)
            refresh_errors.append(f"{english}:{type(exc).__name__}")
            failed.append(english)
            preserved = team_fusion_result_from_cache_entry(team_key, prior_entry or {})
            if preserved:
                team_results[team_key] = preserved
            team_reports[english] = WarmupTeamReport(
                status="failed",
                matches_before=before_count,
                matches_after=before_count,
                coverage_quality_before=before_quality,
                coverage_quality_after=before_quality,
                reason_codes=[f"WARMUP_EXCEPTION:{type(exc).__name__}"],
            )
            continue

        after_count = result.coverage_count
        after_quality = result.coverage_quality

        if after_count <= 0 and before_count > 0:
            preserved = team_fusion_result_from_cache_entry(team_key, prior_entry or {})
            if preserved:
                team_results[team_key] = preserved
                status = "partial"
                after_count = before_count
                after_quality = before_quality
                result.source_mix = dict(preserved.source_mix)
                result.coverage_warnings = list(preserved.coverage_warnings)
                warnings = ["WARMUP_PRESERVED_EXISTING_ON_EMPTY"]
                reason_codes = ["WARMUP_PRESERVED_EXISTING_ON_EMPTY"]
            else:
                team_results[team_key] = result
                status = "failed"
                failed.append(english)
                warnings = list(result.coverage_warnings)
                reason_codes = list(result.fetch_errors or [])
        elif after_count <= 0:
            team_results[team_key] = result
            status = "failed"
            failed.append(english)
            warnings = list(result.coverage_warnings)
            reason_codes = list(result.fetch_errors or [])
        else:
            team_results[team_key] = result
            if before_count > 0 and after_count < before_count:
                status = "partial"
            else:
                status = "refreshed"
            refreshed.append(english)
            warnings = list(result.coverage_warnings)
            reason_codes = []
            if result.fetch_errors:
                reason_codes.extend(result.fetch_errors)

        team_reports[english] = WarmupTeamReport(
            status=status,
            matches_before=before_count,
            matches_after=after_count,
            coverage_quality_before=before_quality,
            coverage_quality_after=after_quality,
            source_mix=dict(result.source_mix),
            warnings=warnings,
            reason_codes=reason_codes,
        )

        if apif_client and apif_client.stop_reason:
            break

        time.sleep(max(0.0, config.RECENT_FORM_WARMUP_SLEEP_SECONDS))

    # Preserve teams not in this warmup batch
    for team_key, entry in existing_teams.items():
        if team_key in team_results:
            continue
        preserved = team_fusion_result_from_cache_entry(team_key, entry)
        if preserved:
            team_results[team_key] = preserved

    cloud_pushed = False
    cache_written = False
    write_status = "dry_run"

    if not dry_run and any(r.status != "skipped_fresh" for r in team_reports.values()):
        payload = build_fusion_cache_payload(team_results, refresh_errors=refresh_errors)
        path, write_status = write_fusion_cache_safe(payload, team_results=team_results)
        cache_written = path is not None
        if path and cloud_persist_configured():
            cloud_pushed = push_file(path)
        elif path:
            write_status = f"{write_status};cloud_persist_not_configured"
    else:
        write_status = "dry_run_no_write"

    return {
        "enabled": True,
        "dry_run": dry_run,
        "requested_teams": [k.split(" (")[0] for k in registry_keys],
        "refreshed_teams": refreshed,
        "skipped_teams": skipped,
        "failed_teams": failed,
        "request_budget": budget.to_dict(),
        "provider_status": {
            "api_football": _provider_status_apif(apif_client),
            "football_data": _provider_status_football_data(),
        },
        "teams": {name: report.to_dict() for name, report in team_reports.items()},
        "cache_written": cache_written,
        "cloud_persist_pushed": cloud_pushed,
        "write_status": write_status,
    }
