"""Phase 4R.3 — Multi-provider national-team recent-form fusion cache."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import config
from core.football_data_teams import normalize_team_key
from core.recent_match_history import (
    NormalizedRecentMatch,
    SOURCE_PRIORITY_RANK,
    SOURCE_TO_CONFIDENCE,
    SOURCE_TO_PRIORITY_LABEL,
    _match_to_normalized_rows,
    _resolve_team_key,
)
from core.recent_form_sources_audit import load_tagged_matches
from data.database import FIFA_ELO_2026
from data.nt_match import registry_key_for_nt

logger = logging.getLogger(__name__)

FUSION_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "cache" / "recent_form_fusion_cache.json"
)
FUSION_SCHEMA_VERSION = 1
FUSION_SOURCE_ID = "recent_form_fusion_cache"
MAX_CANDIDATE_POOL = 40
LAST_10_WINDOW = 10

FUSION_CACHE_MISSING = "FUSION_CACHE_MISSING"
FUSION_CACHE_CORRUPT = "FUSION_CACHE_CORRUPT"
FUSION_CACHE_STALE = "FUSION_CACHE_STALE"
FUSION_CACHE_USED = "FUSION_CACHE_USED"
FUSION_CACHE_WRITE_REJECTED = "FUSION_CACHE_WRITE_REJECTED"

WARN_MISSING_2025_2026 = "FUSION_MISSING_2025_2026_HISTORICAL"
WARN_MIXED_WC_HISTORICAL = "FUSION_MIXED_WC_HISTORICAL_GAP"
WARN_STALE_TAIL = "FUSION_STALE_HISTORICAL_TAIL"
WARN_LOW_CANDIDATE_COUNT = "FUSION_LOW_CANDIDATE_COUNT"
WARN_SINGLE_SOURCE = "FUSION_SINGLE_SOURCE_ONLY"

CoverageQuality = Literal["high", "medium", "low", "unavailable"]

PROVIDER_NUMERIC_PRIORITY: dict[str, int] = {
    "football_data_recent_form": 110,
    "api_football_recent_form": 100,
    "sofascore_recent_form": 98,
    "recent_form_cache_football_data": 110,
    "cache_wc2026_live_matches": 100,
    "cache_nt_history_fetched": 95,
    "bundled_wc2026_qualifiers": 90,
    "bundled_euro2024": 40,
    "bundled_copa2024": 40,
    "bundled_wc2022": 35,
    "bundled_wc2018": 30,
}

REGISTRY = set(FIFA_ELO_2026.keys())
FUSION_LOAD_META: dict[str, Any] = {
    "cache_found": False,
    "cache_stale": False,
    "cache_error": None,
    "cache_row_count": 0,
    "reason_codes": [],
}


@dataclass
class TeamFusionResult:
    team_registry_key: str
    english_name: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    deduped: list[dict[str, Any]] = field(default_factory=list)
    last_10_finished: list[dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    coverage_count: int = 0
    last_15_available: int = 0
    source_mix: dict[str, int] = field(default_factory=dict)
    freshness_gap_days: int | None = None
    oldest_match_date: str | None = None
    latest_match_date: str | None = None
    coverage_quality: CoverageQuality = "unavailable"
    coverage_warnings: list[str] = field(default_factory=list)
    provider_ids: dict[str, Any] = field(default_factory=dict)
    provider_availability: dict[str, str] = field(default_factory=dict)
    provider_candidate_counts: dict[str, int] = field(default_factory=dict)
    fetch_errors: list[str] = field(default_factory=list)

    def to_cache_entry(self) -> dict[str, Any]:
        return {
            "team_registry_key": self.team_registry_key,
            "english_name": self.english_name,
            "provider_ids": self.provider_ids,
            "provider_availability": self.provider_availability,
            "provider_candidate_counts": self.provider_candidate_counts,
            "fusion": {
                "candidate_count": self.candidate_count,
                "coverage_count": self.coverage_count,
                "last_15_available": self.last_15_available,
                "source_mix": self.source_mix,
                "freshness_gap_days": self.freshness_gap_days,
                "oldest_match_date": self.oldest_match_date,
                "latest_match_date": self.latest_match_date,
                "coverage_quality": self.coverage_quality,
                "coverage_warnings": self.coverage_warnings,
                "last_10_finished": self.last_10_finished,
            },
            "candidates": self.candidates[:MAX_CANDIDATE_POOL],
            "deduped_count": len(self.deduped),
            "fetch_errors": self.fetch_errors,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _norm_team_label(name: str) -> str:
    base = name.split(" (")[0].strip().lower()
    return re.sub(r"[^a-z0-9]+", "", base)


def normalized_row_to_fusion_match(row: NormalizedRecentMatch) -> dict[str, Any]:
    provider = row.source
    if provider == "recent_form_cache_football_data":
        provider = "football_data_recent_form"
    if row.goals_for > row.goals_against:
        result = "W"
    elif row.goals_for < row.goals_against:
        result = "L"
    else:
        result = "D"
    season = None
    m = re.match(r"(\d{4})", row.date)
    if m:
        season = int(m.group(1))
    return {
        "provider": provider,
        "source_priority": PROVIDER_NUMERIC_PRIORITY.get(provider, 30),
        "provider_fixture_id": row.raw_source_id,
        "team": row.team,
        "opponent": row.opponent,
        "date": row.date,
        "status": "FT",
        "home_team": row.team if row.is_home is not False else row.opponent,
        "away_team": row.opponent if row.is_home is not False else row.team,
        "home_score": row.goals_for if row.is_home is not False else row.goals_against,
        "away_score": row.goals_against if row.is_home is not False else row.goals_for,
        "score_for": row.goals_for,
        "score_against": row.goals_against,
        "result_for_team": result,
        "competition_name": row.competition,
        "competition_id": None,
        "competition_code": None,
        "season": season,
        "is_neutral": row.is_neutral,
        "confidence_level": row.source_confidence,
        "quality_flags": [row.date_confidence] if row.date_confidence != "real" else [],
        "raw_source_ref": {"source": provider, "raw_source_id": row.raw_source_id},
        "team_registry_key": row.team_registry_key,
        "opponent_registry_key": row.opponent_registry_key,
    }


def fusion_match_to_normalized(row: dict[str, Any]) -> NormalizedRecentMatch:
    source = FUSION_SOURCE_ID
    source_priority = SOURCE_TO_PRIORITY_LABEL.get(source, "api_cache_fresh")
    source_confidence = SOURCE_TO_CONFIDENCE.get(source, row.get("confidence_level", "medium"))
    date_conf = "real"
    flags = row.get("quality_flags") or []
    if "synthetic" in flags:
        date_conf = "synthetic"
    elif "unknown" in flags:
        date_conf = "unknown"

    is_home: bool | None = None
    home_team = str(row.get("home_team") or "")
    away_team = str(row.get("away_team") or "")
    team = str(row.get("team") or "")
    if home_team and away_team and team:
        team_key = normalize_team_key(team)
        if team_key == normalize_team_key(home_team):
            is_home = True
        elif team_key == normalize_team_key(away_team):
            is_home = False

    return NormalizedRecentMatch(
        date=str(row["date"]),
        team=team,
        opponent=str(row.get("opponent") or "unknown"),
        goals_for=int(row.get("score_for", row.get("goals_for", 0))),
        goals_against=int(row.get("score_against", row.get("goals_against", 0))),
        competition=str(row.get("competition_name") or row.get("competition") or "unknown"),
        source=source,
        source_priority=source_priority,
        source_confidence=source_confidence,
        date_confidence=date_conf,
        is_home=is_home,
        is_neutral=row.get("is_neutral"),
        raw_source_id=str(row.get("provider_fixture_id") or row.get("raw_source_ref", {}).get("raw_source_id")),
        team_registry_key=row.get("team_registry_key"),
        opponent_registry_key=row.get("opponent_registry_key"),
    )


def _dedupe_key(match: dict[str, Any]) -> tuple[str, str, str, int, int]:
    team = _norm_team_label(str(match.get("team") or ""))
    opp = _norm_team_label(str(match.get("opponent") or ""))
    pair = tuple(sorted((team, opp)))
    return (
        str(match.get("date") or "")[:10],
        pair[0],
        pair[1],
        int(match.get("score_for", 0)),
        int(match.get("score_against", 0)),
    )


def dedupe_fusion_matches(
    matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Deduplicate across providers; keep higher numeric source_priority."""
    best: dict[tuple[str, str, str, int, int], dict[str, Any]] = {}
    source_mix: dict[str, int] = {}
    for match in matches:
        provider = str(match.get("provider") or "unknown")
        source_mix[provider] = source_mix.get(provider, 0) + 1
        key = _dedupe_key(match)
        existing = best.get(key)
        if existing is None:
            best[key] = match
            continue
        existing_pri = int(existing.get("source_priority") or 0)
        new_pri = int(match.get("source_priority") or 0)
        if new_pri > existing_pri:
            best[key] = match
        elif new_pri == existing_pri:
            existing_flags = existing.get("quality_flags") or []
            new_flags = match.get("quality_flags") or []
            if "synthetic" not in new_flags and "synthetic" in existing_flags:
                best[key] = match
    return sorted(best.values(), key=lambda m: str(m.get("date") or ""), reverse=True), source_mix


def _is_wc_2026_match(match: dict[str, Any]) -> bool:
    comp = str(match.get("competition_name") or "").lower()
    season = match.get("season")
    year = str(match.get("date") or "")[:4]
    return "world cup" in comp and (season == 2026 or year == "2026")


def _assess_coverage(
    deduped: list[dict[str, Any]],
    source_mix: dict[str, int],
) -> tuple[CoverageQuality, list[str], int | None]:
    warnings: list[str] = []
    if not deduped:
        return "unavailable", warnings, None

    dates = [_parse_date(str(m.get("date") or "")) for m in deduped]
    valid_dates = [d for d in dates if d is not None]
    latest = max(valid_dates) if valid_dates else None
    oldest = min(valid_dates) if valid_dates else None

    freshness_gap: int | None = None
    wc_matches = [m for m in deduped if _is_wc_2026_match(m)]
    non_wc = [m for m in deduped if not _is_wc_2026_match(m)]

    if wc_matches and non_wc:
        wc_latest = max(_parse_date(str(m.get("date") or "")) for m in wc_matches if _parse_date(str(m.get("date") or "")))
        non_wc_latest = max(
            _parse_date(str(m.get("date") or "")) for m in non_wc if _parse_date(str(m.get("date") or ""))
        )
        if wc_latest and non_wc_latest and wc_latest > non_wc_latest:
            freshness_gap = (wc_latest - non_wc_latest).days
            if freshness_gap > 90:
                warnings.append(WARN_MIXED_WC_HISTORICAL)
                warnings.append(WARN_STALE_TAIL)

    if latest and latest.year <= 2024:
        warnings.append(WARN_MISSING_2025_2026)

    if len(deduped) < LAST_10_WINDOW:
        warnings.append(WARN_LOW_CANDIDATE_COUNT)
        quality: CoverageQuality = "low" if deduped else "unavailable"
        return quality, warnings, freshness_gap

    if len(source_mix) <= 1:
        warnings.append(WARN_SINGLE_SOURCE)

    today = date.today()
    if latest and (today - latest).days > 540:
        warnings.append(WARN_STALE_TAIL)

    if len(deduped) >= LAST_10_WINDOW and not warnings:
        return "high", warnings, freshness_gap
    if len(deduped) >= LAST_10_WINDOW:
        return "medium", warnings, freshness_gap
    return "low", warnings, freshness_gap


def fuse_team_matches(
    team_registry_key: str,
    candidates: list[dict[str, Any]],
) -> TeamFusionResult:
    english = team_registry_key.split(" (")[0]
    deduped, source_mix = dedupe_fusion_matches(candidates)
    last_10 = deduped[:LAST_10_WINDOW]
    quality, warnings, freshness_gap = _assess_coverage(deduped, source_mix)

    provider_counts: dict[str, int] = {}
    for m in candidates:
        p = str(m.get("provider") or "unknown")
        provider_counts[p] = provider_counts.get(p, 0) + 1

    dates = [str(m.get("date") or "")[:10] for m in deduped if m.get("date")]
    return TeamFusionResult(
        team_registry_key=team_registry_key,
        english_name=english,
        candidates=sorted(candidates, key=lambda m: str(m.get("date") or ""), reverse=True)[:MAX_CANDIDATE_POOL],
        deduped=deduped,
        last_10_finished=last_10,
        candidate_count=len(candidates),
        coverage_count=len(deduped),
        last_15_available=min(15, len(deduped)),
        source_mix={k: source_mix.get(k, 0) for k in sorted(source_mix)},
        freshness_gap_days=freshness_gap,
        oldest_match_date=min(dates) if dates else None,
        latest_match_date=max(dates) if dates else None,
        coverage_quality=quality,
        coverage_warnings=warnings,
        provider_candidate_counts=provider_counts,
    )


def collect_static_candidates(team_registry_key: str) -> list[dict[str, Any]]:
    rows: list[NormalizedRecentMatch] = []
    for tm in load_tagged_matches(include_optional_caches=False):
        rows.extend(
            _match_to_normalized_rows(
                source_id=tm.source_id,
                date_confidence=tm.date_confidence,
                match=tm.match,
            )
        )
    english = team_registry_key.split(" (")[0]
    out: list[dict[str, Any]] = []
    for row in rows:
        key = row.team_registry_key or _resolve_team_key(row.team)
        if key != team_registry_key:
            continue
        fusion = normalized_row_to_fusion_match(row)
        fusion["team_registry_key"] = team_registry_key
        out.append(fusion)
    return out


def collect_football_data_candidates(
    team_registry_key: str,
    *,
    client=None,
    id_map: dict[str, int] | None = None,
    max_windows: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from data.football_data import FootballDataClient
    from core.football_data_recent_form import fetch_team_recent_matches

    meta: dict[str, Any] = {"status": "skipped", "football_data_team_id": None}
    if not config.recent_form_api_enabled():
        meta["status"] = "disabled"
        return [], meta

    fd_id = (id_map or {}).get(team_registry_key)
    if fd_id is None:
        meta["status"] = "team_id_missing"
        return [], meta

    client = client or FootballDataClient()
    result = fetch_team_recent_matches(
        client,
        team_registry_key=team_registry_key,
        football_data_team_id=int(fd_id),
        max_windows=max_windows,
    )
    meta["status"] = "ok" if result.rows else (result.error_category or "no_results")
    meta["football_data_team_id"] = fd_id
    meta["reason_codes"] = result.reason_codes

    matches = [normalized_row_to_fusion_match(m) for m in result.rows]
    for m in matches:
        m["team_registry_key"] = team_registry_key
    return matches, meta


def collect_api_football_candidates(
    team_registry_key: str,
    *,
    client=None,
    registry: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from core.api_football_recent_form import (
        ApiFootballRecentFormClient,
        known_nt_team_id,
        parse_apif_fixture_for_team,
    )

    meta: dict[str, Any] = {"status": "skipped", "api_football_team_id": None}
    if not config.api_football_recent_form_enabled():
        meta["status"] = "disabled"
        return [], meta

    client = client or ApiFootballRecentFormClient()
    english = team_registry_key.split(" (")[0]
    team_obj, candidates, err = client.search_national_team(english, registry=registry or REGISTRY)
    meta["search_candidate_count"] = len(candidates)
    if err and not team_obj:
        meta["status"] = err.category
        meta["error"] = err.message
        return [], meta
    if not team_obj:
        meta["status"] = "team_not_found"
        return [], meta

    team_id = int(team_obj.get("id"))
    meta["api_football_team_id"] = team_id
    known_id = known_nt_team_id(english)
    if known_id is not None and team_id == known_id and not candidates:
        meta["search_fallback"] = "known_nt_team_id"
    if len(candidates) > 1:
        meta["ambiguous_search"] = True

    fixtures, fetch_meta = client.collect_team_fixtures(team_id)
    meta.update(fetch_meta)
    meta["status"] = "ok" if fixtures else "no_results"

    out: list[dict[str, Any]] = []
    for fx in fixtures:
        parsed = parse_apif_fixture_for_team(
            fx,
            team_registry_key=team_registry_key,
            api_team_id=team_id,
        )
        if parsed:
            out.append(parsed)
    return out, meta


def collect_sofascore_candidates(
    team_registry_key: str,
    *,
    client=None,
    id_map: dict[str, int] | None = None,
    registry: set[str] | None = None,
    force_enabled: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from data.sofascore import (
        SofascoreClient,
        known_sofascore_registry_team_id,
        known_sofascore_nt_team_id,
        select_national_mens_football_team,
        sofascore_event_to_fusion_match,
    )

    meta: dict[str, Any] = {"status": "skipped", "sofascore_team_id": None}
    if not force_enabled and not config.sofascore_enabled():
        meta["status"] = "disabled"
        return [], meta

    client = client or SofascoreClient(enabled=True)
    english = team_registry_key.split(" (")[0]
    reg = registry or REGISTRY

    sofa_id = (id_map or {}).get(team_registry_key)
    if sofa_id is None:
        sofa_id = known_sofascore_registry_team_id(team_registry_key)
    if sofa_id is None:
        sofa_id = known_sofascore_nt_team_id(english)
    if sofa_id is None and client.is_available:
        search_results = client.search_teams(english)
        selected = select_national_mens_football_team(
            search_results,
            expected_name=english,
        )
        if selected is not None:
            sofa_id = int(selected["id"])
    if sofa_id is None:
        meta["status"] = "team_id_missing"
        return [], meta

    meta["sofascore_team_id"] = int(sofa_id)
    events = client.fetch_last_match_events(int(sofa_id))
    if not events:
        meta["status"] = "no_results"
        return [], meta

    out: list[dict[str, Any]] = []
    for event in events:
        parsed = sofascore_event_to_fusion_match(
            event,
            team_registry_key=team_registry_key,
            sofascore_team_id=int(sofa_id),
            registry=reg,
        )
        if parsed:
            out.append(parsed)

    meta["status"] = "ok" if out else "no_finished_results"
    meta["raw_event_count"] = len(events)
    return out, meta


def summarize_sofascore_fusion_coverage(
    payload: dict[str, Any] | None,
    *,
    registry_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Offline audit summary for Sofascore rows inside fusion cache."""
    reg = registry_keys or REGISTRY
    summary: dict[str, Any] = {
        "teams_with_sofascore_id": 0,
        "sofascore_candidate_rows": 0,
        "finished_match_rows": 0,
        "matches_with_has_xg": 0,
        "source_mix_sofascore": 0,
        "missing_sofascore_mappings": [],
    }
    if not payload:
        summary["missing_sofascore_mappings"] = sorted(reg)
        return summary

    teams = payload.get("teams") or {}
    mapped_keys: set[str] = set()
    for team_key, entry in teams.items():
        if not isinstance(entry, dict):
            continue
        provider_ids = entry.get("provider_ids") or {}
        if provider_ids.get("sofascore") is not None:
            summary["teams_with_sofascore_id"] += 1
            mapped_keys.add(team_key)

        fusion = entry.get("fusion") or {}
        source_mix = fusion.get("source_mix") or {}
        summary["source_mix_sofascore"] += int(source_mix.get("sofascore_recent_form") or 0)

        for raw in entry.get("candidates") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("provider") or "") != "sofascore_recent_form":
                continue
            summary["sofascore_candidate_rows"] += 1
            status = str(raw.get("status") or "").lower()
            if status in ("finished", "ended", "ft") or raw.get("status_code") in (100, 110, 120):
                summary["finished_match_rows"] += 1
            if raw.get("has_xg"):
                summary["matches_with_has_xg"] += 1

    summary["missing_sofascore_mappings"] = sorted(reg - mapped_keys)
    return summary


def build_team_fusion(
    team_registry_key: str,
    *,
    fd_client=None,
    apif_client=None,
    sofascore_client=None,
    id_map: dict[str, int] | None = None,
    sofascore_id_map: dict[str, int] | None = None,
    include_live_apis: bool = True,
    include_football_data: bool = True,
    include_api_football: bool = True,
    include_sofascore: bool | None = None,
    force_sofascore: bool = False,
) -> TeamFusionResult:
    candidates: list[dict[str, Any]] = []
    result = TeamFusionResult(
        team_registry_key=team_registry_key,
        english_name=team_registry_key.split(" (")[0],
    )

    static = collect_static_candidates(team_registry_key)
    candidates.extend(static)
    result.provider_availability["static"] = "ok" if static else "empty"

    use_sofascore = (
        config.sofascore_enabled() if include_sofascore is None else include_sofascore
    )

    if include_live_apis:
        if include_football_data:
            fd_rows, fd_meta = collect_football_data_candidates(
                team_registry_key,
                client=fd_client,
                id_map=id_map,
            )
            candidates.extend(fd_rows)
            result.provider_availability["football_data"] = str(fd_meta.get("status", "unknown"))
            if fd_meta.get("football_data_team_id") is not None:
                result.provider_ids["football_data"] = fd_meta["football_data_team_id"]
        else:
            result.provider_availability["football_data"] = "skipped"

        if include_api_football:
            apif_rows, apif_meta = collect_api_football_candidates(
                team_registry_key,
                client=apif_client,
            )
            candidates.extend(apif_rows)
            result.provider_availability["api_football"] = str(apif_meta.get("status", "unknown"))
            if apif_meta.get("api_football_team_id") is not None:
                result.provider_ids["api_football"] = apif_meta["api_football_team_id"]
            if apif_meta.get("ambiguous_search"):
                result.fetch_errors.append("APIF_AMBIGUOUS_TEAM_SEARCH")
            for key, val in (apif_meta.get("season_errors") or {}).items():
                result.fetch_errors.append(f"APIF_SEASON_{key}:{val}")
        else:
            result.provider_availability["api_football"] = "skipped"

        if use_sofascore and include_sofascore is not False:
            ss_rows, ss_meta = collect_sofascore_candidates(
                team_registry_key,
                client=sofascore_client,
                id_map=sofascore_id_map,
                force_enabled=force_sofascore,
            )
            candidates.extend(ss_rows)
            result.provider_availability["sofascore"] = str(ss_meta.get("status", "unknown"))
            if ss_meta.get("sofascore_team_id") is not None:
                result.provider_ids["sofascore"] = ss_meta["sofascore_team_id"]
        else:
            result.provider_availability["sofascore"] = (
                "disabled" if not use_sofascore else "skipped"
            )
    else:
        result.provider_availability["football_data"] = "cache_only"
        result.provider_availability["api_football"] = "cache_only"
        result.provider_availability["sofascore"] = "cache_only"

    fused = fuse_team_matches(team_registry_key, candidates)
    fused.provider_ids = result.provider_ids
    fused.provider_availability = result.provider_availability
    fused.fetch_errors = result.fetch_errors
    return fused


def build_fusion_cache_payload(
    team_results: dict[str, TeamFusionResult],
    *,
    refresh_errors: list[str] | None = None,
) -> dict[str, Any]:
    teams_payload = {key: tr.to_cache_entry() for key, tr in team_results.items()}
    ok_count = sum(1 for tr in team_results.values() if tr.coverage_count > 0)
    sources: dict[str, Any] = {
        "football-data.org": {"role": "wc2026_current"},
        "api-football": {"role": "historical_nt", "seasons": config.api_football_seasons_list()},
        "static": {"role": "fallback"},
    }
    if config.sofascore_enabled():
        sources["sofascore"] = {"role": "recent_nt_matches", "provider_namespace": "sofascore"}
    return {
        "schema_version": FUSION_SCHEMA_VERSION,
        "last_updated_utc": _utc_now_iso(),
        "sources": sources,
        "refresh_summary": {
            "teams_requested": len(team_results),
            "teams_with_coverage": ok_count,
            "errors": refresh_errors or [],
        },
        "teams": teams_payload,
    }


def count_fusion_rows(payload: dict[str, Any]) -> int:
    total = 0
    for entry in (payload.get("teams") or {}).values():
        if isinstance(entry, dict):
            fusion = entry.get("fusion") or {}
            total += len(fusion.get("last_10_finished") or [])
    return total


def load_fusion_cache(
    path: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    path = path or FUSION_CACHE_PATH
    if not path.exists():
        return None, FUSION_CACHE_MISSING
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, FUSION_CACHE_CORRUPT
    if not isinstance(payload, dict):
        return None, FUSION_CACHE_CORRUPT
    if payload.get("schema_version") != FUSION_SCHEMA_VERSION:
        return None, FUSION_CACHE_CORRUPT
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


def is_fusion_cache_stale(payload: dict[str, Any]) -> bool:
    age = cache_age_hours(payload)
    if age is None:
        return True
    return age > float(config.RECENT_FORM_CACHE_TTL_HOURS)


def fusion_rows_from_payload(
    payload: dict[str, Any],
    *,
    stale_ok: bool = True,
) -> tuple[list[NormalizedRecentMatch], dict[str, Any]]:
    meta: dict[str, Any] = {
        "cache_found": True,
        "cache_stale": is_fusion_cache_stale(payload),
        "cache_age_hours": cache_age_hours(payload),
        "reason_codes": [FUSION_CACHE_USED],
    }
    if meta["cache_stale"] and not stale_ok:
        meta["reason_codes"].append(FUSION_CACHE_STALE)
        return [], meta
    if meta["cache_stale"]:
        meta["reason_codes"].append(FUSION_CACHE_STALE)

    rows: list[NormalizedRecentMatch] = []
    teams = payload.get("teams") or {}
    for entry in teams.values():
        if not isinstance(entry, dict):
            continue
        fusion = entry.get("fusion") or {}
        for raw in fusion.get("last_10_finished") or []:
            if not isinstance(raw, dict):
                continue
            try:
                row = fusion_match_to_normalized(raw)
                rows.append(row)
            except (KeyError, TypeError, ValueError):
                continue
    meta["row_count"] = len(rows)
    meta["team_count"] = len(teams)
    return rows, meta


def load_fusion_cache_rows() -> tuple[list[NormalizedRecentMatch], dict[str, Any]]:
    payload, error = load_fusion_cache()
    meta: dict[str, Any] = {
        "cache_found": payload is not None,
        "cache_stale": False,
        "cache_error": error,
        "cache_row_count": 0,
        "reason_codes": [],
    }
    if error == FUSION_CACHE_MISSING:
        meta["reason_codes"].append(FUSION_CACHE_MISSING)
        return [], meta
    if error == FUSION_CACHE_CORRUPT or payload is None:
        meta["reason_codes"].append(FUSION_CACHE_CORRUPT)
        return [], meta

    rows, cache_meta = fusion_rows_from_payload(payload)
    meta.update(cache_meta)
    meta["cache_row_count"] = len(rows)
    global FUSION_LOAD_META
    FUSION_LOAD_META = meta
    return rows, meta


def get_fusion_cache_status() -> dict[str, Any]:
    return dict(FUSION_LOAD_META)


def get_fusion_team_entry(team_registry_key: str) -> dict[str, Any] | None:
    """Return one team's fusion cache entry (offline read; no API)."""
    payload, error = load_fusion_cache()
    if error or not payload:
        return None
    entry = (payload.get("teams") or {}).get(team_registry_key)
    return entry if isinstance(entry, dict) else None


def validate_fusion_payload_for_write(
    payload: dict[str, Any],
    *,
    team_results: dict[str, TeamFusionResult] | None = None,
    allow_empty: bool = False,
) -> tuple[bool, str]:
    if allow_empty:
        return True, "ok"
    row_count = count_fusion_rows(payload)
    if row_count == 0:
        return False, "fusion cache would contain 0 last_10 rows"
    if team_results:
        with_coverage = sum(1 for tr in team_results.values() if tr.coverage_count > 0)
        if with_coverage == 0:
            return False, "all teams produced 0 deduped matches"
    return True, "ok"


def write_fusion_cache(payload: dict[str, Any], path: Path | None = None) -> Path:
    path = path or FUSION_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_fusion_cache_safe(
    payload: dict[str, Any],
    *,
    team_results: dict[str, TeamFusionResult] | None = None,
    path: Path | None = None,
    allow_empty: bool = False,
    force: bool = False,
) -> tuple[Path | None, str]:
    path = path or FUSION_CACHE_PATH
    if not force:
        valid, reason = validate_fusion_payload_for_write(
            payload,
            team_results=team_results,
            allow_empty=allow_empty,
        )
        if not valid:
            return None, reason

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded, load_err = load_fusion_cache(temp_path)
    if load_err is not None or loaded is None:
        temp_path.unlink(missing_ok=True)
        return None, f"temp fusion cache validation failed: {load_err}"
    if count_fusion_rows(loaded) == 0 and not allow_empty and not force:
        temp_path.unlink(missing_ok=True)
        return None, "temp fusion cache contains 0 rows"

    os.replace(temp_path, path)
    return path, "ok"


def team_fusion_result_from_cache_entry(team_key: str, entry: dict[str, Any]) -> TeamFusionResult | None:
    if not isinstance(entry, dict):
        return None
    fusion = entry.get("fusion") or {}
    if fusion.get("coverage_count", 0) <= 0 and not fusion.get("last_10_finished"):
        return None
    return TeamFusionResult(
        team_registry_key=team_key,
        english_name=str(entry.get("english_name") or team_key.split(" (")[0]),
        candidates=list(entry.get("candidates") or []),
        deduped=[],
        last_10_finished=list(fusion.get("last_10_finished") or []),
        candidate_count=int(fusion.get("candidate_count") or 0),
        coverage_count=int(fusion.get("coverage_count") or 0),
        last_15_available=int(fusion.get("last_15_available") or 0),
        source_mix=dict(fusion.get("source_mix") or {}),
        freshness_gap_days=fusion.get("freshness_gap_days"),
        oldest_match_date=fusion.get("oldest_match_date"),
        latest_match_date=fusion.get("latest_match_date"),
        coverage_quality=fusion.get("coverage_quality") or "unavailable",
        coverage_warnings=list(fusion.get("coverage_warnings") or []),
        provider_ids=dict(entry.get("provider_ids") or {}),
        provider_availability=dict(entry.get("provider_availability") or {}),
        provider_candidate_counts=dict(entry.get("provider_candidate_counts") or {}),
    )


def parse_cli_team_names(
    teams_csv: str | None = None,
    team_repeat: list[str] | None = None,
) -> list[str]:
    from core.football_data_recent_form import parse_cli_team_names as fd_parse

    return fd_parse(teams_csv, team_repeat)


def resolve_cli_team_registry_keys(names: list[str]) -> list[str]:
    from core.football_data_recent_form import resolve_cli_team_registry_keys as fd_resolve

    return fd_resolve(names)


def all_wc_registry_keys() -> list[str]:
    return sorted(FIFA_ELO_2026.keys())
