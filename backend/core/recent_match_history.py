"""Phase 4R.1 — Normalized offline national-team recent match history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from core.recent_form_sources_audit import load_tagged_matches
from data.database import FIFA_ELO_2026
from data.nt_match import registry_key_for_nt

DateConfidence = Literal["real", "synthetic", "unknown"]
SourceConfidence = Literal["high", "medium", "low"]
SourcePriority = Literal[
    "static_real_dated",
    "static_synthetic",
    "api_cache_fresh",
    "api_cache_stale",
    "unavailable",
]

REGISTRY = set(FIFA_ELO_2026.keys())

SOURCE_PRIORITY_RANK: dict[str, int] = {
    "recent_form_fusion_cache": 115,
    "recent_form_cache_football_data": 110,
    "cache_wc2026_live_matches": 100,
    "cache_nt_history_fetched": 95,
    "bundled_wc2026_qualifiers": 90,
    "bundled_euro2024": 40,
    "bundled_copa2024": 40,
    "bundled_wc2022": 35,
    "bundled_wc2018": 30,
}

SOURCE_TO_PRIORITY_LABEL: dict[str, SourcePriority] = {
    "recent_form_fusion_cache": "api_cache_fresh",
    "recent_form_cache_football_data": "api_cache_fresh",
    "cache_wc2026_live_matches": "api_cache_fresh",
    "cache_nt_history_fetched": "api_cache_fresh",
    "bundled_wc2026_qualifiers": "static_real_dated",
    "bundled_euro2024": "static_synthetic",
    "bundled_copa2024": "static_synthetic",
    "bundled_wc2022": "static_synthetic",
    "bundled_wc2018": "static_synthetic",
}

SOURCE_TO_CONFIDENCE: dict[str, SourceConfidence] = {
    "recent_form_fusion_cache": "high",
    "recent_form_cache_football_data": "high",
    "cache_wc2026_live_matches": "high",
    "cache_nt_history_fetched": "high",
    "bundled_wc2026_qualifiers": "medium",
    "bundled_euro2024": "low",
    "bundled_copa2024": "low",
    "bundled_wc2022": "low",
    "bundled_wc2018": "low",
}

CACHE_LOAD_META: dict[str, Any] = {
    "cache_found": False,
    "cache_stale": False,
    "cache_error": None,
    "cache_row_count": 0,
    "reason_codes": [],
}


@dataclass(frozen=True)
class NormalizedRecentMatch:
    date: str
    team: str
    opponent: str
    goals_for: int
    goals_against: int
    competition: str
    source: str
    source_priority: SourcePriority
    source_confidence: SourceConfidence
    date_confidence: DateConfidence
    is_home: bool | None
    is_neutral: bool | None
    raw_source_id: str | None = None
    opponent_power_proxy: float | None = None
    opponent_strength_confidence: SourceConfidence | None = None
    team_registry_key: str | None = None
    opponent_registry_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeamRecentMatchCoverage:
    team_registry_key: str
    english_name: str
    matches_found: int = 0
    real_dated_matches: int = 0
    synthetic_dated_matches: int = 0
    latest_match_date: str | None = None
    source_breakdown: dict[str, int] = field(default_factory=dict)
    only_synthetic_dates: bool = False
    opponent_strength_proxy_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_team_key(name: str) -> str | None:
    return registry_key_for_nt(name, REGISTRY)


def _opponent_power_proxy(opponent_key: str | None) -> tuple[float | None, SourceConfidence | None]:
    if not opponent_key or opponent_key not in FIFA_ELO_2026:
        return None, None
    return float(FIFA_ELO_2026[opponent_key]), "medium"


def _match_to_normalized_rows(
    *,
    source_id: str,
    date_confidence: DateConfidence,
    match,
) -> list[NormalizedRecentMatch]:
    home_key = _resolve_team_key(match.home)
    away_key = _resolve_team_key(match.away)
    source_priority = SOURCE_TO_PRIORITY_LABEL.get(source_id, "static_synthetic")
    source_confidence = SOURCE_TO_CONFIDENCE.get(source_id, "low")
    raw_id = f"{source_id}:{match.date}:{match.home}:{match.away}"

    rows: list[NormalizedRecentMatch] = []
    if home_key:
        opp_proxy, opp_conf = _opponent_power_proxy(away_key)
        rows.append(
            NormalizedRecentMatch(
                date=match.date,
                team=home_key.split(" (")[0],
                opponent=match.away if not away_key else away_key.split(" (")[0],
                goals_for=match.home_goals,
                goals_against=match.away_goals,
                competition=match.competition,
                source=source_id,
                source_priority=source_priority,
                source_confidence=source_confidence,
                date_confidence=date_confidence,
                is_home=True if not match.neutral else None,
                is_neutral=match.neutral,
                raw_source_id=raw_id,
                opponent_power_proxy=opp_proxy,
                opponent_strength_confidence=opp_conf,
                team_registry_key=home_key,
                opponent_registry_key=away_key,
            )
        )
    if away_key:
        opp_proxy, opp_conf = _opponent_power_proxy(home_key)
        rows.append(
            NormalizedRecentMatch(
                date=match.date,
                team=away_key.split(" (")[0],
                opponent=match.home if not home_key else home_key.split(" (")[0],
                goals_for=match.away_goals,
                goals_against=match.home_goals,
                competition=match.competition,
                source=source_id,
                source_priority=source_priority,
                source_confidence=source_confidence,
                date_confidence=date_confidence,
                is_home=False if not match.neutral else None,
                is_neutral=match.neutral,
                raw_source_id=raw_id,
                opponent_power_proxy=opp_proxy,
                opponent_strength_confidence=opp_conf,
                team_registry_key=away_key,
                opponent_registry_key=home_key,
            )
        )
    return rows


def _dedupe_key(row: NormalizedRecentMatch) -> tuple[str, str, str, int, int]:
    opp = row.opponent_registry_key or row.opponent.lower()
    team = row.team_registry_key or row.team.lower()
    return (row.date, team, opp, row.goals_for, row.goals_against)


def _dedupe_rows(rows: list[NormalizedRecentMatch]) -> list[NormalizedRecentMatch]:
    best: dict[tuple[str, str, str, int, int], NormalizedRecentMatch] = {}
    for row in rows:
        key = _dedupe_key(row)
        existing = best.get(key)
        if existing is None:
            best[key] = row
            continue
        existing_rank = SOURCE_PRIORITY_RANK.get(existing.source, 0)
        new_rank = SOURCE_PRIORITY_RANK.get(row.source, 0)
        if new_rank > existing_rank:
            best[key] = row
        elif new_rank == existing_rank:
            # Prefer real-dated over synthetic when same source tier
            if row.date_confidence == "real" and existing.date_confidence != "real":
                best[key] = row
    return list(best.values())


def _sort_rows(rows: list[NormalizedRecentMatch]) -> list[NormalizedRecentMatch]:
    def sort_key(r: NormalizedRecentMatch) -> tuple[str, int, int]:
        real_rank = 1 if r.date_confidence == "real" else 0
        src_rank = SOURCE_PRIORITY_RANK.get(r.source, 0)
        return (r.date, real_rank, src_rank)

    return sorted(rows, key=sort_key, reverse=True)


def _enrich_opponent_proxy(row: NormalizedRecentMatch) -> NormalizedRecentMatch:
    if row.opponent_power_proxy is not None:
        return row
    opp_key = row.opponent_registry_key or _resolve_team_key(row.opponent)
    proxy, conf = _opponent_power_proxy(opp_key)
    if proxy is None:
        return row
    return NormalizedRecentMatch(
        **{
            **row.to_dict(),
            "opponent_power_proxy": proxy,
            "opponent_strength_confidence": conf,
            "opponent_registry_key": opp_key,
        }
    )


def load_fusion_cache_rows() -> tuple[list[NormalizedRecentMatch], dict[str, Any]]:
    """Read multi-provider fusion cache if present (no live API)."""
    from core.recent_form_fusion import (
        FUSION_CACHE_CORRUPT,
        FUSION_CACHE_MISSING,
        fusion_rows_from_payload,
        load_fusion_cache,
    )

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
    enriched = [_enrich_opponent_proxy(r) for r in rows]
    meta["cache_row_count"] = len(enriched)
    return enriched, meta


def load_recent_form_cache_rows() -> tuple[list[NormalizedRecentMatch], dict[str, Any]]:
    """Read football-data recent form cache if present (no live API)."""
    from core.football_data_recent_form import (
        RECENT_FORM_CACHE_CORRUPT,
        RECENT_FORM_CACHE_MISSING,
        cache_rows_from_payload,
        load_recent_form_cache,
    )

    payload, error = load_recent_form_cache()
    meta: dict[str, Any] = {
        "cache_found": payload is not None,
        "cache_stale": False,
        "cache_error": error,
        "cache_row_count": 0,
        "reason_codes": [],
    }
    if error == RECENT_FORM_CACHE_MISSING:
        meta["reason_codes"].append(RECENT_FORM_CACHE_MISSING)
        return [], meta
    if error == RECENT_FORM_CACHE_CORRUPT or payload is None:
        meta["reason_codes"].append(RECENT_FORM_CACHE_CORRUPT)
        return [], meta

    rows, cache_meta = cache_rows_from_payload(payload)
    meta.update(cache_meta)
    enriched = [_enrich_opponent_proxy(r) for r in rows]
    meta["cache_row_count"] = len(enriched)
    global CACHE_LOAD_META
    CACHE_LOAD_META = meta
    return enriched, meta


def get_recent_form_cache_status() -> dict[str, Any]:
    """Last cache load metadata for audits/diagnostics."""
    return dict(CACHE_LOAD_META)


def build_normalized_recent_match_history(
    *,
    include_optional_caches: bool = True,
    include_recent_form_cache: bool = True,
    include_fusion_cache: bool = True,
) -> list[NormalizedRecentMatch]:
    """Build deduplicated normalized match list from cache + static/bundled sources."""
    rows: list[NormalizedRecentMatch] = []
    fusion_used = False

    if include_fusion_cache:
        fusion_rows, fusion_meta = load_fusion_cache_rows()
        if fusion_rows:
            rows.extend(fusion_rows)
            fusion_used = True

    if include_recent_form_cache and not fusion_used:
        cache_rows, _ = load_recent_form_cache_rows()
        rows.extend(cache_rows)

    tagged = load_tagged_matches(include_optional_caches=include_optional_caches)
    for tm in tagged:
        rows.extend(
            _match_to_normalized_rows(
                source_id=tm.source_id,
                date_confidence=tm.date_confidence,
                match=tm.match,
            )
        )
    return _sort_rows(_dedupe_rows(rows))


def _resolve_team_registry_key(team: str) -> str | None:
    if team in REGISTRY:
        return team
    return registry_key_for_nt(team, REGISTRY)


def get_team_recent_matches(
    team: str,
    *,
    before_date: str | date | None = None,
    limit: int = 10,
    history: list[NormalizedRecentMatch] | None = None,
) -> list[NormalizedRecentMatch]:
    team_key = _resolve_team_registry_key(team)
    if not team_key:
        return []

    cutoff = str(before_date) if before_date is not None else None
    all_rows = history if history is not None else build_normalized_recent_match_history()

    filtered: list[NormalizedRecentMatch] = []
    for row in all_rows:
        row_key = row.team_registry_key or _resolve_team_registry_key(row.team)
        if row_key != team_key:
            continue
        if cutoff and row.date >= cutoff:
            continue
        filtered.append(row)

    return _sort_rows(filtered)[:limit]


def explain_recent_match_sources(team: str) -> dict[str, Any]:
    team_key = _resolve_team_registry_key(team)
    if not team_key:
        return {"team": team, "resolved": False, "sources": {}}
    matches = get_team_recent_matches(team_key, limit=1000)
    sources: dict[str, int] = {}
    date_types: dict[str, int] = {"real": 0, "synthetic": 0, "unknown": 0}
    for m in matches:
        sources[m.source] = sources.get(m.source, 0) + 1
        date_types[m.date_confidence] = date_types.get(m.date_confidence, 0) + 1
    return {
        "team": team_key,
        "resolved": True,
        "total_matches": len(matches),
        "sources": sources,
        "date_confidence_breakdown": date_types,
        "latest_match_date": matches[0].date if matches else None,
    }


def get_recent_match_coverage_summary(
    *,
    history: list[NormalizedRecentMatch] | None = None,
    window: int = 10,
) -> list[TeamRecentMatchCoverage]:
    all_rows = history if history is not None else build_normalized_recent_match_history()
    by_team: dict[str, list[NormalizedRecentMatch]] = {}
    for row in all_rows:
        key = row.team_registry_key or _resolve_team_registry_key(row.team)
        if not key:
            continue
        by_team.setdefault(key, []).append(row)

    summary: list[TeamRecentMatchCoverage] = []
    for registry_key in sorted(FIFA_ELO_2026.keys()):
        english = registry_key.split(" (")[0]
        team_rows = _sort_rows(by_team.get(registry_key, []))
        last_n = team_rows[:window]
        cov = TeamRecentMatchCoverage(
            team_registry_key=registry_key,
            english_name=english,
            matches_found=len(last_n),
            latest_match_date=last_n[0].date if last_n else None,
        )
        for m in last_n:
            if m.date_confidence == "real":
                cov.real_dated_matches += 1
            elif m.date_confidence == "synthetic":
                cov.synthetic_dated_matches += 1
            cov.source_breakdown[m.source] = cov.source_breakdown.get(m.source, 0) + 1
            if m.opponent_power_proxy is not None:
                cov.opponent_strength_proxy_available = True
        cov.only_synthetic_dates = (
            cov.matches_found > 0 and cov.real_dated_matches == 0
        )
        summary.append(cov)
    return summary
