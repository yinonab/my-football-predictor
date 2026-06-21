"""Phase 4R.2 — football-data.org recent-form fetch, parse, and cache I/O."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import config
from core.football_data_teams import football_data_team_keys, teams_match
from core.recent_match_history import NormalizedRecentMatch
from data.database import FIFA_ELO_2026
from data.football_data import (
    KEY_MISSING,
    FootballDataClient,
    FootballDataErrorDetail,
    FootballDataRequestError,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_429_RATE_LIMITED,
    RATE_LIMITED,
    UNAUTHORIZED,
    parse_rate_limit_wait_seconds,
    sanitize_fd_response_body,
)
from data.nt_match import registry_key_for_nt

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
CACHE_SOURCE_ID = "recent_form_cache_football_data"
RECENT_FORM_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "cache" / "recent_form_cache.json"
)

FINISHED_STATUSES = frozenset({"FINISHED", "AWARDED"})
IGNORED_STATUSES = frozenset({"SCHEDULED", "TIMED", "POSTPONED", "SUSPENDED", "CANCELLED"})

# football-data.org: dateFrom/dateTo must be paired; span must not exceed 750 days.
FD_MAX_DATE_SPAN_DAYS = 750
FD_SAFE_WINDOW_DAYS = 730
FD_TARGET_MIN_MATCHES = 10
FD_DEFAULT_ROLLING_WINDOWS = 1
FD_MAX_ROLLING_WINDOWS = 2

REGISTRY = set(FIFA_ELO_2026.keys())

RECENT_FORM_CACHE_CORRUPT = "RECENT_FORM_CACHE_CORRUPT"
RECENT_FORM_CACHE_MISSING = "RECENT_FORM_CACHE_MISSING"
RECENT_FORM_CACHE_STALE = "RECENT_FORM_CACHE_STALE"
RECENT_FORM_API_CACHE_USED = "RECENT_FORM_API_CACHE_USED"
RECENT_FORM_API_UNDATED_FALLBACK_USED = "RECENT_FORM_API_UNDATED_FALLBACK_USED"
RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT = "RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT"
RECENT_FORM_API_PARTIAL_DUE_UPSTREAM_ERROR = "RECENT_FORM_API_PARTIAL_DUE_UPSTREAM_ERROR"
RECENT_FORM_RATE_LIMIT_STOP = "RECENT_FORM_RATE_LIMIT_STOP"
RECENT_FORM_CACHE_WRITE_REJECTED = "RECENT_FORM_CACHE_WRITE_REJECTED"

TEAM_FETCH_STATUS_OK = "ok"
TEAM_FETCH_STATUS_PARTIAL = "partial_success"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_finished_fd_match(match: dict[str, Any]) -> bool:
    status = (match.get("status") or "").upper()
    if status in IGNORED_STATUSES:
        return False
    if status not in FINISHED_STATUSES:
        return False
    score = match.get("score") or {}
    full = score.get("fullTime") or score.get("regularTime") or {}
    home = full.get("home")
    away = full.get("away")
    return home is not None and away is not None


def _match_date_iso(match: dict[str, Any]) -> str | None:
    raw = match.get("utcDate") or match.get("date")
    if not raw:
        return None
    return str(raw)[:10]


def _competition_name(match: dict[str, Any]) -> str:
    comp = match.get("competition") or {}
    if isinstance(comp, dict):
        return str(comp.get("name") or comp.get("code") or "unknown")
    return str(comp or "unknown")


def _venue_neutral(match: dict[str, Any]) -> bool | None:
    venue = match.get("venue")
    if venue is None:
        return None
    if isinstance(venue, dict):
        return not bool(venue.get("name") or venue.get("city"))
    return None


def parse_fd_match_for_registry_team(
    match: dict[str, Any],
    *,
    team_registry_key: str,
    football_data_team_id: int,
) -> list[NormalizedRecentMatch]:
    """Convert one football-data match to normalized rows for the focal team."""
    if not is_finished_fd_match(match):
        return []

    match_date = _match_date_iso(match)
    if not match_date:
        return []

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    score = match.get("score") or {}
    full = score.get("fullTime") or score.get("regularTime") or {}
    home_goals = int(full.get("home", 0))
    away_goals = int(full.get("away", 0))

    raw_id = str(match.get("id") or f"fd:{match_date}:{home.get('name')}:{away.get('name')}")
    competition = _competition_name(match)
    neutral = _venue_neutral(match)

    rows: list[NormalizedRecentMatch] = []
    english = team_registry_key.split(" (")[0]

    if home_id == football_data_team_id or teams_match(english, home):
        away_key = registry_key_for_nt(str(away.get("name") or ""), REGISTRY)
        rows.append(
            NormalizedRecentMatch(
                date=match_date,
                team=english,
                opponent=str(away.get("name") or away.get("shortName") or "unknown"),
                goals_for=home_goals,
                goals_against=away_goals,
                competition=competition,
                source=CACHE_SOURCE_ID,
                source_priority="api_cache_fresh",
                source_confidence="high",
                date_confidence="real",
                is_home=True if neutral is False else None,
                is_neutral=neutral,
                raw_source_id=f"football-data.org:{raw_id}",
                team_registry_key=team_registry_key,
                opponent_registry_key=away_key,
            )
        )
    elif away_id == football_data_team_id or teams_match(english, away):
        home_key = registry_key_for_nt(str(home.get("name") or ""), REGISTRY)
        rows.append(
            NormalizedRecentMatch(
                date=match_date,
                team=english,
                opponent=str(home.get("name") or home.get("shortName") or "unknown"),
                goals_for=away_goals,
                goals_against=home_goals,
                competition=competition,
                source=CACHE_SOURCE_ID,
                source_priority="api_cache_fresh",
                source_confidence="high",
                date_confidence="real",
                is_home=False if neutral is False else None,
                is_neutral=neutral,
                raw_source_id=f"football-data.org:{raw_id}",
                team_registry_key=team_registry_key,
                opponent_registry_key=home_key,
            )
        )
    return rows


def _discovery_error_record(detail: FootballDataErrorDetail | None) -> dict[str, Any]:
    if detail is None:
        return {"ok": False, "category": UNKNOWN_ERROR, "message": "no error detail"}
    wait = parse_rate_limit_wait_seconds(detail.message)
    return {
        "ok": False,
        "category": detail.category,
        "http_status": detail.http_status,
        "path": detail.endpoint_path,
        "message": detail.message,
        "likely_cause": detail.likely_cause,
        "fd_error_code": detail.fd_error_code,
        "rate_limit_wait_seconds": wait,
    }


UNKNOWN_ERROR = "UNKNOWN_ERROR"


def _source_diag_ok(match_count: int = 0) -> dict[str, Any]:
    return {"ok": True, "category": OK_CATEGORY, "match_count": match_count}


OK_CATEGORY = "OK"


def discover_football_data_team_ids(
    client: FootballDataClient,
) -> tuple[dict[str, int], list[str], dict[str, Any]]:
    """
    Map WC 2026 registry keys → football-data team id.

    Sources: competition teams endpoint + WC match home/away teams.
    """
    id_map: dict[str, int] = {}
    meta: dict[str, Any] = {
        "sources_used": [],
        "source_diagnostics": {},
        "warnings": [],
    }

    comp_path = f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/teams"
    comp_payload, comp_detail = client.request_raw(
        comp_path,
        {"season": config.FOOTBALL_DATA_WC_SEASON},
    )
    if comp_detail is not None:
        meta["source_diagnostics"]["competition_teams"] = _discovery_error_record(comp_detail)
        meta["warnings"].append(f"competition_teams:{comp_detail.category}")
        if is_rate_limited_category(comp_detail.category):
            meta["rate_limit_stop"] = True
            meta["rate_limit_wait_seconds"] = parse_rate_limit_wait_seconds(comp_detail.message)
            missing = [key.split(" (")[0] for key in sorted(REGISTRY) if key not in id_map]
            meta["discovered_count"] = len(id_map)
            meta["missing_count"] = len(missing)
            return id_map, missing, meta
    elif comp_payload is not None:
        meta["sources_used"].append("competition_teams")
        meta["source_diagnostics"]["competition_teams"] = _source_diag_ok()
        comp_teams = list(comp_payload.get("teams") or [])
        meta["source_diagnostics"]["competition_teams"]["team_count"] = len(comp_teams)
        for entry in comp_teams:
            team_obj = entry.get("team") if isinstance(entry, dict) else entry
            if not isinstance(team_obj, dict):
                continue
            team_id = team_obj.get("id")
            if team_id is None:
                continue
            for registry_key in REGISTRY:
                english = registry_key.split(" (")[0]
                if teams_match(english, team_obj):
                    id_map[registry_key] = int(team_id)

    if len(id_map) >= len(REGISTRY):
        meta["source_diagnostics"]["wc_matches"] = {
            "ok": True,
            "category": OK_CATEGORY,
            "skipped": True,
            "reason": "competition_teams_complete",
        }
        missing = [
            key.split(" (")[0]
            for key in sorted(REGISTRY)
            if key not in id_map
        ]
        meta["discovered_count"] = len(id_map)
        meta["missing_count"] = len(missing)
        return id_map, missing, meta

    wc_path = f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/matches"
    wc_payload, wc_detail = client.request_raw(
        wc_path,
        {"season": config.FOOTBALL_DATA_WC_SEASON},
    )
    if wc_detail is not None:
        meta["source_diagnostics"]["wc_matches"] = _discovery_error_record(wc_detail)
        meta["warnings"].append(f"wc_matches:{wc_detail.category}")
        if is_rate_limited_category(wc_detail.category):
            meta["rate_limit_stop"] = True
            meta["rate_limit_wait_seconds"] = parse_rate_limit_wait_seconds(wc_detail.message)
    elif wc_payload is not None:
        meta["sources_used"].append("wc_matches")
        wc_matches = list(wc_payload.get("matches") or [])
        meta["source_diagnostics"]["wc_matches"] = _source_diag_ok(len(wc_matches))
        for match in wc_matches:
            for side in ("homeTeam", "awayTeam"):
                team_obj = match.get(side) or {}
                team_id = team_obj.get("id")
                if team_id is None:
                    continue
                for registry_key in REGISTRY:
                    english = registry_key.split(" (")[0]
                    if teams_match(english, team_obj):
                        id_map.setdefault(registry_key, int(team_id))

    missing = [
        key.split(" (")[0]
        for key in sorted(REGISTRY)
        if key not in id_map
    ]
    meta["discovered_count"] = len(id_map)
    meta["missing_count"] = len(missing)
    return id_map, missing, meta


def _utc_today() -> datetime.date:
    return datetime.now(timezone.utc).date()


def build_safe_date_window(
    *,
    date_to: datetime.date | None = None,
    span_days: int = FD_SAFE_WINDOW_DAYS,
) -> tuple[str, str]:
    """Return paired dateFrom/dateTo with span <= FD_SAFE_WINDOW_DAYS."""
    end = date_to or _utc_today()
    span = min(max(span_days, 1), FD_SAFE_WINDOW_DAYS)
    start = end - timedelta(days=span)
    return start.isoformat(), end.isoformat()


def iter_rolling_date_windows(
    *,
    date_to: datetime.date | None = None,
    span_days: int = FD_SAFE_WINDOW_DAYS,
    max_windows: int = FD_MAX_ROLLING_WINDOWS,
) -> list[tuple[str, str]]:
    """Non-overlapping windows ending at date_to; each span <= FD_SAFE_WINDOW_DAYS."""
    end = date_to or _utc_today()
    span = min(max(span_days, 1), FD_SAFE_WINDOW_DAYS)
    windows: list[tuple[str, str]] = []
    cursor_end = end
    for _ in range(max(1, max_windows)):
        start = cursor_end - timedelta(days=span)
        windows.append((start.isoformat(), cursor_end.isoformat()))
        cursor_end = start - timedelta(days=1)
    return windows


def date_window_span_days(date_from: str, date_to: str) -> int:
    start = datetime.fromisoformat(date_from[:10]).date()
    end = datetime.fromisoformat(date_to[:10]).date()
    return (end - start).days


def normalize_cli_team_token(raw: str) -> str:
    return raw.strip().strip('"').strip("'").strip("\u201c\u201d")


def parse_cli_team_names(
    teams_csv: str | None,
    team_repeat: list[str] | None = None,
) -> list[str]:
    """Parse --teams CSV and/or repeatable --team values into one ordered name list."""
    names: list[str] = []
    if teams_csv:
        names.extend(
            normalize_cli_team_token(part)
            for part in teams_csv.split(",")
            if normalize_cli_team_token(part)
        )
    if team_repeat:
        names.extend(
            normalize_cli_team_token(part)
            for part in team_repeat
            if normalize_cli_team_token(part)
        )
    return names


def resolve_cli_team_registry_keys(names: list[str]) -> list[str]:
    """Resolve CLI team names to WC 2026 registry keys (deduped, order preserved)."""
    registry = REGISTRY
    keys: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in registry:
            key = name
        else:
            key = registry_key_for_nt(name, registry)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def error_detail_from_client(client: FootballDataClient) -> FootballDataErrorDetail | None:
    return client.last_error_detail


def format_error_detail(detail: FootballDataErrorDetail, *, verbose: bool = False) -> str:
    parts = [detail.category]
    if detail.http_status is not None:
        parts.append(f"status={detail.http_status}")
    parts.append(f"path={detail.endpoint_path}")
    if detail.params:
        parts.append(f"params={detail.params}")
    if detail.fd_error_code:
        parts.append(f"fd_errorCode={detail.fd_error_code}")
    if detail.message and detail.message != detail.category:
        parts.append(f"msg={detail.message}")
    wait = parse_rate_limit_wait_seconds(detail.message)
    if wait is not None:
        parts.append(f"wait_seconds={wait}")
    if verbose:
        parts.append(f"likely={detail.likely_cause}")
    return " ".join(parts)


def is_rate_limited_category(category: str | None) -> bool:
    return category in (HTTP_429_RATE_LIMITED, RATE_LIMITED)


def is_upstream_partial_error(category: str | None) -> bool:
    if not category:
        return False
    if is_rate_limited_category(category):
        return True
    return category in (
        HTTP_403_FORBIDDEN,
        "TIMEOUT",
        "CONNECTION_ERROR",
        "HTTP_5XX_UPSTREAM",
    )


def team_fetch_status_for_result(result: "TeamFetchResult") -> str:
    if result.rows and (result.partial_success or result.error_category):
        return TEAM_FETCH_STATUS_PARTIAL
    if result.rows:
        return TEAM_FETCH_STATUS_OK
    return str(result.error_category or "error").lower()


def team_result_has_usable_rows(result: dict[str, Any]) -> bool:
    status = str(result.get("status", ""))
    return status in (TEAM_FETCH_STATUS_OK, TEAM_FETCH_STATUS_PARTIAL) and bool(
        result.get("matches")
    )


def print_discovery_diagnostics(meta: dict[str, Any], *, verbose: bool = False) -> None:
    diag = meta.get("source_diagnostics") or {}
    for source in ("competition_teams", "wc_matches"):
        record = diag.get(source)
        if not record:
            print(f"  {source}: not attempted")
            continue
        if record.get("ok"):
            extra = f" teams={record.get('team_count')}" if source == "competition_teams" else ""
            extra = extra or (f" matches={record.get('match_count')}" if source == "wc_matches" else "")
            print(f"  {source}: ok{extra}")
            continue
        line = (
            f"  {source}: {record.get('category')} status={record.get('http_status')} "
            f"likely={record.get('likely_cause')}"
        )
        print(line)
        if record.get("message"):
            print(f"    msg={record.get('message')}")
        if record.get("rate_limit_wait_seconds") is not None:
            wait = record["rate_limit_wait_seconds"]
            print(f"    rate_limit_wait_seconds={wait} — rerun after waiting")
    if meta.get("rate_limit_stop"):
        wait = meta.get("rate_limit_wait_seconds")
        if wait:
            print(f"Discovery stopped due to rate limit; wait {wait}s before retry.")


def _raw_team_matches(
    client: FootballDataClient,
    team_id: int,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str = "FINISHED",
    limit: int = 100,
) -> tuple[list[dict[str, Any]], FootballDataErrorDetail | None]:
    params: dict[str, Any] = {"status": status, "limit": limit}
    if date_from and date_to:
        params["dateFrom"] = date_from
        params["dateTo"] = date_to
    payload, detail = client.request_raw(f"/teams/{team_id}/matches", params)
    if detail is not None:
        return [], detail
    return list((payload or {}).get("matches") or []), None


def _ingest_fd_matches(
    raw_matches: list[dict[str, Any]],
    *,
    team_registry_key: str,
    football_data_team_id: int,
    seen_ids: set[str],
    source_confidence: str = "high",
) -> list[NormalizedRecentMatch]:
    rows: list[NormalizedRecentMatch] = []
    for match in raw_matches:
        for row in parse_fd_match_for_registry_team(
            match,
            team_registry_key=team_registry_key,
            football_data_team_id=football_data_team_id,
        ):
            dedupe_key = row.raw_source_id or f"{row.date}:{row.opponent}"
            if dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)
            if source_confidence != row.source_confidence:
                row = NormalizedRecentMatch(
                    **{**row.to_dict(), "source_confidence": source_confidence}
                )
            rows.append(row)
    return rows


@dataclass
class TeamFetchResult:
    rows: list[NormalizedRecentMatch] = field(default_factory=list)
    error_category: str | None = None
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    fetch_strategy: str | None = None
    window_index: int | None = None
    rate_limit_wait_seconds: int | None = None
    partial_success: bool = False


def _partial_fetch_result(
    *,
    rows: list[NormalizedRecentMatch],
    warnings: list[str],
    reason_codes: list[str],
    partial_code: str,
    fetch_strategy: str | None,
    window_index: int | None,
    rate_limit_wait_seconds: int | None = None,
) -> TeamFetchResult:
    return TeamFetchResult(
        rows=rows,
        partial_success=True,
        warnings=[*warnings, partial_code],
        reason_codes=[*reason_codes, partial_code],
        fetch_strategy=fetch_strategy,
        window_index=window_index,
        rate_limit_wait_seconds=rate_limit_wait_seconds,
    )


def fetch_team_recent_matches(
    client: FootballDataClient,
    *,
    team_registry_key: str,
    football_data_team_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    sleep_seconds: float = 0.35,
    min_matches: int = FD_TARGET_MIN_MATCHES,
    max_windows: int = FD_DEFAULT_ROLLING_WINDOWS,
) -> TeamFetchResult:
    """Fetch FINISHED team matches; recent dated window first, undated fallback on 403."""
    max_windows = min(max(1, max_windows), FD_MAX_ROLLING_WINDOWS)
    if date_from is not None or date_to is not None:
        if not (date_from and date_to):
            return TeamFetchResult(error_category=HTTP_400_BAD_REQUEST)
        if date_window_span_days(date_from, date_to) > FD_MAX_DATE_SPAN_DAYS:
            return TeamFetchResult(error_category=HTTP_400_BAD_REQUEST)
        windows = [(date_from, date_to)]
    else:
        windows = iter_rolling_date_windows(max_windows=max_windows)

    all_rows: list[NormalizedRecentMatch] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []
    reason_codes: list[str] = []
    dated_forbidden = False
    last_strategy: str | None = None
    last_window_idx: int | None = None

    for window_idx, (win_from, win_to) in enumerate(windows):
        raw_matches, detail = _raw_team_matches(
            client,
            football_data_team_id,
            date_from=win_from,
            date_to=win_to,
            status="FINISHED",
            limit=limit,
        )
        if detail is not None:
            if all_rows and is_upstream_partial_error(detail.category):
                partial_code = (
                    RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT
                    if is_rate_limited_category(detail.category)
                    else RECENT_FORM_API_PARTIAL_DUE_UPSTREAM_ERROR
                )
                wait = (
                    parse_rate_limit_wait_seconds(detail.message)
                    if is_rate_limited_category(detail.category)
                    else None
                )
                return _partial_fetch_result(
                    rows=all_rows,
                    warnings=warnings,
                    reason_codes=reason_codes,
                    partial_code=partial_code,
                    fetch_strategy=last_strategy,
                    window_index=last_window_idx,
                    rate_limit_wait_seconds=wait,
                )
            if is_rate_limited_category(detail.category):
                wait = parse_rate_limit_wait_seconds(detail.message)
                return TeamFetchResult(
                    error_category=detail.category,
                    warnings=[detail.category],
                    reason_codes=[RECENT_FORM_RATE_LIMIT_STOP],
                    rate_limit_wait_seconds=wait,
                    window_index=window_idx,
                )
            if detail.category == HTTP_403_FORBIDDEN:
                dated_forbidden = True
                warnings.append(f"dated_window_403:window={window_idx}")
                break
            return TeamFetchResult(
                error_category=detail.category,
                warnings=[detail.category],
                window_index=window_idx,
            )

        batch = _ingest_fd_matches(
            raw_matches,
            team_registry_key=team_registry_key,
            football_data_team_id=football_data_team_id,
            seen_ids=seen_ids,
        )
        all_rows.extend(batch)
        last_strategy = "dated_recent" if window_idx == 0 else "dated_older"
        last_window_idx = window_idx

        if len(all_rows) >= min_matches:
            break
        if window_idx + 1 < len(windows) and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if (len(all_rows) < min_matches or dated_forbidden) and (
        dated_forbidden or not all_rows
    ):
        raw_matches, detail = _raw_team_matches(
            client,
            football_data_team_id,
            status="FINISHED",
            limit=limit,
        )
        if detail is not None:
            if all_rows and is_upstream_partial_error(detail.category):
                partial_code = (
                    RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT
                    if is_rate_limited_category(detail.category)
                    else RECENT_FORM_API_PARTIAL_DUE_UPSTREAM_ERROR
                )
                wait = (
                    parse_rate_limit_wait_seconds(detail.message)
                    if is_rate_limited_category(detail.category)
                    else None
                )
                return _partial_fetch_result(
                    rows=all_rows,
                    warnings=warnings,
                    reason_codes=reason_codes,
                    partial_code=partial_code,
                    fetch_strategy=last_strategy,
                    window_index=last_window_idx,
                    rate_limit_wait_seconds=wait,
                )
            if is_rate_limited_category(detail.category):
                wait = parse_rate_limit_wait_seconds(detail.message)
                if all_rows:
                    return _partial_fetch_result(
                        rows=all_rows,
                        warnings=warnings,
                        reason_codes=reason_codes,
                        partial_code=RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT,
                        fetch_strategy=last_strategy,
                        window_index=last_window_idx,
                        rate_limit_wait_seconds=wait,
                    )
                return TeamFetchResult(
                    error_category=detail.category,
                    warnings=[detail.category],
                    reason_codes=[RECENT_FORM_RATE_LIMIT_STOP],
                    rate_limit_wait_seconds=wait,
                )
            if not all_rows:
                return TeamFetchResult(
                    error_category=detail.category,
                    warnings=warnings + [detail.category],
                    window_index=last_window_idx,
                )
        else:
            batch = _ingest_fd_matches(
                raw_matches,
                team_registry_key=team_registry_key,
                football_data_team_id=football_data_team_id,
                seen_ids=seen_ids,
                source_confidence="medium",
            )
            if batch:
                all_rows.extend(batch)
                warnings.append(RECENT_FORM_API_UNDATED_FALLBACK_USED)
                reason_codes.append(RECENT_FORM_API_UNDATED_FALLBACK_USED)
                last_strategy = "undated_fallback"

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    if not all_rows and dated_forbidden:
        return TeamFetchResult(
            error_category=HTTP_403_FORBIDDEN,
            warnings=warnings,
            window_index=last_window_idx,
        )

    return TeamFetchResult(
        rows=all_rows,
        warnings=warnings,
        reason_codes=reason_codes,
        fetch_strategy=last_strategy,
        window_index=last_window_idx,
    )


def probe_team_match_endpoint_variants(
    client: FootballDataClient,
    *,
    team_id: int,
    team_label: str,
    stop_on_rate_limit: bool = True,
) -> list[dict[str, Any]]:
    """Low-volume endpoint variant probe for diagnostics (1 team, ~5 calls)."""
    safe_from, safe_to = build_safe_date_window()
    path = f"/teams/{team_id}/matches"
    variants: list[tuple[str, dict[str, Any]]] = [
        ("undated status=FINISHED", {"status": "FINISHED", "limit": 100}),
        ("recent safe dated window + FINISHED", {"dateFrom": safe_from, "dateTo": safe_to, "status": "FINISHED", "limit": 100}),
        ("limit=10 undated", {"limit": 10}),
    ]
    results: list[dict[str, Any]] = []
    for label, params in variants:
        payload, detail = client.request_raw(path, params)
        entry: dict[str, Any] = {
            "team": team_label,
            "team_id": team_id,
            "variant": label,
            "path": path,
            "params": params,
        }
        if detail is not None:
            entry["ok"] = False
            entry["category"] = detail.category
            entry["http_status"] = detail.http_status
            entry["message"] = detail.message
            entry["likely_cause"] = detail.likely_cause
            entry["fd_error_code"] = detail.fd_error_code
            entry["rate_limit_wait_seconds"] = parse_rate_limit_wait_seconds(detail.message)
            results.append(entry)
            if stop_on_rate_limit and is_rate_limited_category(detail.category):
                break
        else:
            matches = list((payload or {}).get("matches") or [])
            entry["ok"] = True
            entry["http_status"] = 200
            entry["match_count"] = len(matches)
            entry["category"] = OK_CATEGORY
            results.append(entry)
        time.sleep(0.35)
    return results


def investigate_bosnia_discovery(
    client: FootballDataClient,
    id_map: dict[str, int],
) -> dict[str, Any]:
    """Report why Bosnia may be missing from team ID discovery."""
    from core.football_data_teams import football_data_team_keys, normalize_team_key, teams_match

    bosnia_key = registry_key_for_nt("Bosnia", REGISTRY)
    report: dict[str, Any] = {
        "registry_key": bosnia_key,
        "discovered_id": id_map.get(bosnia_key) if bosnia_key else None,
        "alias_checks": {},
        "competition_team_hits": [],
        "wc_match_hits": [],
        "near_name_hits": [],
    }
    for alias in (
        "Bosnia",
        "Bosnia and Herzegovina",
        "Bosnia-Herzegovina",
        "Bosnia & Herzegovina",
        "BIH",
    ):
        report["alias_checks"][alias] = normalize_team_key(alias)

    try:
        comp_teams = client.get_competition_teams()
        for entry in comp_teams:
            team_obj = entry.get("team") if isinstance(entry, dict) else entry
            if not isinstance(team_obj, dict):
                continue
            name_blob = " ".join(
                str(team_obj.get(k) or "")
                for k in ("name", "shortName", "tla")
            ).lower()
            if "bosnia" in name_blob or team_obj.get("tla") == "BIH":
                report["competition_team_hits"].append(
                    {
                        "id": team_obj.get("id"),
                        "name": team_obj.get("name"),
                        "shortName": team_obj.get("shortName"),
                        "tla": team_obj.get("tla"),
                        "teams_match_bosnia": teams_match("Bosnia", team_obj),
                        "fd_keys": sorted(football_data_team_keys(team_obj)),
                    }
                )
            elif "herzegovina" in name_blob:
                report["near_name_hits"].append(team_obj.get("name"))
    except Exception as exc:
        report["competition_teams_error"] = type(exc).__name__

    try:
        wc_matches = client.get_world_cup_matches()
        seen: set[int] = set()
        for match in wc_matches:
            for side in ("homeTeam", "awayTeam"):
                team_obj = match.get(side) or {}
                team_id = team_obj.get("id")
                if team_id in seen:
                    continue
                name_blob = " ".join(
                    str(team_obj.get(k) or "")
                    for k in ("name", "shortName", "tla")
                ).lower()
                if "bosnia" in name_blob or team_obj.get("tla") == "BIH":
                    seen.add(int(team_id))
                    report["wc_match_hits"].append(
                        {
                            "id": team_id,
                            "name": team_obj.get("name"),
                            "shortName": team_obj.get("shortName"),
                            "tla": team_obj.get("tla"),
                            "teams_match_bosnia": teams_match("Bosnia", team_obj),
                            "fd_keys": sorted(football_data_team_keys(team_obj)),
                        }
                    )
    except Exception as exc:
        report["wc_matches_error"] = type(exc).__name__

    if bosnia_key and bosnia_key not in id_map:
        if report["competition_team_hits"] or report["wc_match_hits"]:
            report["diagnosis"] = "present_in_api_but_alias_match_failed"
        else:
            report["diagnosis"] = "not_listed_in_football_data_wc_2026"
    elif bosnia_key and bosnia_key in id_map:
        report["diagnosis"] = "discovered_ok"
    else:
        report["diagnosis"] = "registry_key_unresolved"
    return report


def normalized_match_to_cache_dict(row: NormalizedRecentMatch) -> dict[str, Any]:
    return row.to_dict()


def cache_dict_to_normalized(row: dict[str, Any]) -> NormalizedRecentMatch:
    return NormalizedRecentMatch(
        date=str(row["date"]),
        team=str(row["team"]),
        opponent=str(row["opponent"]),
        goals_for=int(row["goals_for"]),
        goals_against=int(row["goals_against"]),
        competition=str(row.get("competition", "unknown")),
        source=str(row.get("source", CACHE_SOURCE_ID)),
        source_priority=row.get("source_priority", "api_cache_fresh"),
        source_confidence=row.get("source_confidence", "high"),
        date_confidence=row.get("date_confidence", "real"),
        is_home=row.get("is_home"),
        is_neutral=row.get("is_neutral"),
        raw_source_id=row.get("raw_source_id"),
        opponent_power_proxy=row.get("opponent_power_proxy"),
        opponent_strength_confidence=row.get("opponent_strength_confidence"),
        team_registry_key=row.get("team_registry_key"),
        opponent_registry_key=row.get("opponent_registry_key"),
    )


def load_recent_form_cache(
    path: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Load cache JSON; returns (payload, error_code)."""
    path = path or RECENT_FORM_CACHE_PATH
    if not path.exists():
        return None, RECENT_FORM_CACHE_MISSING
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, RECENT_FORM_CACHE_CORRUPT
    if not isinstance(payload, dict):
        return None, RECENT_FORM_CACHE_CORRUPT
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None, RECENT_FORM_CACHE_CORRUPT
    return payload, None


def cache_age_hours(payload: dict[str, Any]) -> float | None:
    updated = payload.get("last_updated_utc")
    if not updated:
        return None
    try:
        ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 3600.0
    except ValueError:
        return None


def is_cache_stale(payload: dict[str, Any]) -> bool:
    age = cache_age_hours(payload)
    if age is None:
        return True
    return age > float(config.RECENT_FORM_CACHE_TTL_HOURS)


def cache_rows_from_payload(
    payload: dict[str, Any],
    *,
    stale_ok: bool = True,
) -> tuple[list[NormalizedRecentMatch], dict[str, Any]]:
    """Extract normalized rows from cache; metadata includes stale/corrupt flags."""
    meta: dict[str, Any] = {
        "cache_found": True,
        "cache_stale": is_cache_stale(payload),
        "cache_age_hours": cache_age_hours(payload),
        "reason_codes": [RECENT_FORM_API_CACHE_USED],
    }
    if meta["cache_stale"] and not stale_ok:
        meta["reason_codes"].append(RECENT_FORM_CACHE_STALE)
        return [], meta
    if meta["cache_stale"]:
        meta["reason_codes"].append(RECENT_FORM_CACHE_STALE)

    priority: Literal["api_cache_fresh", "api_cache_stale"] = (
        "api_cache_stale" if meta["cache_stale"] else "api_cache_fresh"
    )

    rows: list[NormalizedRecentMatch] = []
    teams = payload.get("teams") or {}
    if not isinstance(teams, dict):
        return [], meta

    for _key, team_entry in teams.items():
        if not isinstance(team_entry, dict):
            continue
        for raw in team_entry.get("matches") or []:
            if not isinstance(raw, dict):
                continue
            try:
                row = cache_dict_to_normalized(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if row.source_priority != priority:
                row = NormalizedRecentMatch(
                    **{
                        **row.to_dict(),
                        "source_priority": priority,
                    }
                )
            rows.append(row)
    meta["row_count"] = len(rows)
    meta["team_count"] = len(teams)
    return rows, meta


def build_cache_payload(
    *,
    team_results: dict[str, dict[str, Any]],
    id_map: dict[str, int],
    refresh_errors: list[str],
) -> dict[str, Any]:
    teams_payload: dict[str, Any] = {}
    for registry_key, result in team_results.items():
        english = registry_key.split(" (")[0]
        matches = result.get("matches") or []
        teams_payload[registry_key] = {
            "team": english,
            "normalized_team": registry_key,
            "football_data_team_id": id_map.get(registry_key),
            "last_updated_utc": _utc_now_iso(),
            "source_priority": "api_cache_fresh",
            "source_confidence": result.get("source_confidence", "high"),
            "status": result.get("status", "ok"),
            "match_count": len(matches),
            "warnings": result.get("warnings") or [],
            "reason_codes": result.get("reason_codes") or [],
            "fetch_strategy": result.get("fetch_strategy"),
            "window_index": result.get("window_index"),
            "matches": matches,
        }

    ok_count = sum(
        1
        for r in team_results.values()
        if r.get("status") in (TEAM_FETCH_STATUS_OK, TEAM_FETCH_STATUS_PARTIAL)
        and len(r.get("matches") or []) > 0
    )
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "last_updated_utc": _utc_now_iso(),
        "sources": {
            "football-data.org": {
                "last_success_utc": _utc_now_iso(),
                "status": "ok" if ok_count else "partial",
                "endpoint": "/v4/teams/{id}/matches",
            }
        },
        "refresh_summary": {
            "teams_requested": len(team_results),
            "teams_ok": ok_count,
            "teams_failed": len(team_results) - ok_count,
            "errors": refresh_errors,
        },
        "teams": teams_payload,
    }


def count_cache_match_rows(payload: dict[str, Any]) -> int:
    total = 0
    teams = payload.get("teams") or {}
    if not isinstance(teams, dict):
        return 0
    for team_entry in teams.values():
        if isinstance(team_entry, dict):
            total += len(team_entry.get("matches") or [])
    return total


def validate_cache_payload_for_write(
    payload: dict[str, Any],
    *,
    id_map: dict[str, int],
    team_results: dict[str, dict[str, Any]] | None = None,
    allow_empty: bool = False,
) -> tuple[bool, str]:
    if allow_empty:
        return True, "ok"
    if not id_map:
        return False, "team discovery returned 0 IDs"
    row_count = count_cache_match_rows(payload)
    if row_count == 0:
        return False, "cache would contain 0 match rows"
    if team_results:
        ok_with_rows = sum(1 for r in team_results.values() if team_result_has_usable_rows(r))
        if ok_with_rows == 0:
            statuses = {str(r.get("status", "")).lower() for r in team_results.values()}
            if statuses <= {"http_429_rate_limited", "rate_limited", "skipped_rate_limit"}:
                return False, "all teams failed due to rate limit before useful data"
            if statuses == {"http_403_forbidden"}:
                return False, "all teams failed with HTTP 403 and no accepted matches"
            return False, "all requested teams failed or produced 0 accepted matches"
    return True, "ok"


def write_recent_form_cache(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Direct write — prefer write_recent_form_cache_safe for refresh scripts."""
    path = path or RECENT_FORM_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_recent_form_cache_safe(
    payload: dict[str, Any],
    *,
    id_map: dict[str, int],
    team_results: dict[str, dict[str, Any]] | None = None,
    path: Path | None = None,
    allow_empty: bool = False,
) -> tuple[Path | None, str]:
    """Atomic validated cache write; returns (path, status_message)."""
    path = path or RECENT_FORM_CACHE_PATH
    valid, reason = validate_cache_payload_for_write(
        payload,
        id_map=id_map,
        team_results=team_results,
        allow_empty=allow_empty,
    )
    if not valid:
        return None, reason

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded, load_err = load_recent_form_cache(temp_path)
    if load_err is not None or loaded is None:
        temp_path.unlink(missing_ok=True)
        return None, f"temp cache validation failed: {load_err}"
    if count_cache_match_rows(loaded) == 0 and not allow_empty:
        temp_path.unlink(missing_ok=True)
        return None, "temp cache contains 0 rows after validation"

    os.replace(temp_path, path)
    return path, "ok"


def refresh_enabled() -> bool:
    return config.recent_form_api_enabled()


def safe_error_message(exc: BaseException) -> str:
    """Redact anything that might contain tokens."""
    text = str(exc)
    for token in ("X-Auth-Token", "api_key", "token", "Bearer"):
        if token.lower() in text.lower():
            return type(exc).__name__
    if len(text) > 120:
        return type(exc).__name__
    return text


def classify_client_error(code: str | None) -> str:
    if code == KEY_MISSING:
        return "KEY_MISSING"
    if code == UNAUTHORIZED:
        return "UNAUTHORIZED"
    if code == RATE_LIMITED:
        return "RATE_LIMITED"
    return code or "UNKNOWN"


def classify_error_category(code: str | None) -> str:
    """Prefer detailed HTTP category over legacy collapsed codes."""
    if not code:
        return "UNKNOWN_ERROR"
    return code


def safe_error_detail_text(client: FootballDataClient) -> str | None:
    detail = error_detail_from_client(client)
    if detail is None:
        return None
    text = format_error_detail(detail, verbose=True)
    return sanitize_fd_response_body(text, max_len=300)
