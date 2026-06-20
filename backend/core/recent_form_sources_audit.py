"""Phase 4R — offline recent-form data source inventory and per-team coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from core.match_store import load_live_matches
from core.team_ratings import FETCHED_HISTORY_PATH, load_fetched_matches
from data.copa2024 import COPA2024_MATCHES
from data.database import FIFA_ELO_2026
from data.euro2024 import EURO2024_MATCHES
from data.nt_history_bundle import _tournament_to_nt_matches
from data.nt_match import NationalTeamMatch, NT_REGISTRY_ALIASES, registry_key_for_nt
from data.wc2018 import WC2018_MATCHES
from data.wc2022 import WC2022_MATCHES
from data.wc2026_qualifiers import WC2026_QUALIFIER_MATCHES

ConfidenceBucket = Literal["high", "medium", "low", "unavailable"]
DateConfidence = Literal["real", "synthetic", "unknown"]
SourceRole = Literal["active_model", "diagnostics_only", "ignored", "optional_cache"]

REGISTRY = set(FIFA_ELO_2026.keys())

# Architecture doc alias probes (English names)
ALIAS_PROBE_NAMES: tuple[str, ...] = (
    "USA",
    "United States",
    "Czechia",
    "Czech Republic",
    "DR Congo",
    "Congo DR",
    "Democratic Republic of the Congo",
    "Ivory Coast",
    "Côte d'Ivoire",
    "Bosnia and Herzegovina",
    "Bosnia-Herzegovina",
    "Curacao",
    "Curaçao",
    "South Korea",
    "Korea Republic",
    "Iran",
    "IR Iran",
    "Cape Verde",
    "Cabo Verde",
    "New Zealand",
    "Haiti",
    "Trinidad and Tobago",
)


@dataclass(frozen=True)
class TaggedMatch:
    match: NationalTeamMatch
    source_id: str
    date_confidence: DateConfidence
    source_role: SourceRole


@dataclass(frozen=True)
class DataSourceInventoryRow:
    source_id: str
    path_or_module: str
    competitions: str
    match_count: int
    team_count: int
    date_coverage: str
    date_type: str
    goals_available: bool
    opponent_available: bool
    home_away_neutral: str
    reliability: str
    freshness: str
    offline_tests_safe: bool
    source_controlled: bool
    recommended_use: SourceRole
    notes: str = ""


@dataclass
class TeamCoverageRow:
    registry_key: str
    english_name: str
    usable_matches: int = 0
    real_date_matches: int = 0
    synthetic_date_matches: int = 0
    matches_with_goals: int = 0
    latest_match_date: str | None = None
    source_breakdown: dict[str, int] = field(default_factory=dict)
    confidence_bucket: ConfidenceBucket = "unavailable"
    alias_resolution_ok: bool = True
    alias_notes: list[str] = field(default_factory=list)
    only_synthetic_dates: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _teams_in_matches(matches: list[NationalTeamMatch]) -> set[str]:
    teams: set[str] = set()
    for m in matches:
        teams.add(m.home)
        teams.add(m.away)
    return teams


def _date_range(matches: list[NationalTeamMatch]) -> str:
    if not matches:
        return "none"
    dates = sorted(m.date for m in matches)
    return f"{dates[0]} .. {dates[-1]}"


def build_source_inventory() -> list[DataSourceInventoryRow]:
    """Static inventory of known NT match sources (no network)."""
    wc18 = _tournament_to_nt_matches(
        WC2018_MATCHES,
        competition="FIFA World Cup",
        weight=1.0,
        start=date(2018, 6, 14),
    )
    wc22 = _tournament_to_nt_matches(
        WC2022_MATCHES,
        competition="FIFA World Cup",
        weight=1.0,
        start=date(2022, 11, 20),
    )
    euro = _tournament_to_nt_matches(
        EURO2024_MATCHES,
        competition="UEFA European Championship",
        weight=0.95,
        start=date(2024, 6, 14),
    )
    copa = _tournament_to_nt_matches(
        COPA2024_MATCHES,
        competition="Copa America",
        weight=0.95,
        start=date(2024, 6, 20),
    )
    qual = [
        NationalTeamMatch(
            date=q.date,
            home=q.home,
            away=q.away,
            home_goals=q.home_goals,
            away_goals=q.away_goals,
            neutral=True,
            competition=q.competition,
            weight=0.75,
        )
        for q in WC2026_QUALIFIER_MATCHES
    ]

    fetched = load_fetched_matches()
    live = load_live_matches()

    rows = [
        DataSourceInventoryRow(
            source_id="bundled_wc2018",
            path_or_module="backend/data/wc2018.py + nt_history_bundle.py",
            competitions="FIFA World Cup 2018",
            match_count=len(wc18),
            team_count=len(_teams_in_matches(wc18)),
            date_coverage=_date_range(wc18),
            date_type="synthetic (one match per calendar day from 2018-06-14)",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="neutral flag per match; host home games non-neutral",
            reliability="high for scores; low for temporal ordering",
            freshness="static historical",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="diagnostics_only",
            notes="Useful for opponent history; poor last-10 recency signal.",
        ),
        DataSourceInventoryRow(
            source_id="bundled_wc2022",
            path_or_module="backend/data/wc2022.py + nt_history_bundle.py",
            competitions="FIFA World Cup 2022",
            match_count=len(wc22),
            team_count=len(_teams_in_matches(wc22)),
            date_coverage=_date_range(wc22),
            date_type="synthetic (from 2022-11-20)",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="neutral flag per match",
            reliability="high for scores; low for temporal ordering",
            freshness="static historical",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="diagnostics_only",
        ),
        DataSourceInventoryRow(
            source_id="bundled_euro2024",
            path_or_module="backend/data/euro2024.py + nt_history_bundle.py",
            competitions="UEFA Euro 2024",
            match_count=len(euro),
            team_count=len(_teams_in_matches(euro)),
            date_coverage=_date_range(euro),
            date_type="synthetic (from 2024-06-14)",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="all neutral=True in bundle",
            reliability="high for scores; medium temporal",
            freshness="static historical",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="diagnostics_only",
        ),
        DataSourceInventoryRow(
            source_id="bundled_copa2024",
            path_or_module="backend/data/copa2024.py + nt_history_bundle.py",
            competitions="Copa America 2024",
            match_count=len(copa),
            team_count=len(_teams_in_matches(copa)),
            date_coverage=_date_range(copa),
            date_type="synthetic (from 2024-06-20)",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="all neutral=True in bundle",
            reliability="high for scores; medium temporal",
            freshness="static historical",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="diagnostics_only",
        ),
        DataSourceInventoryRow(
            source_id="bundled_wc2026_qualifiers",
            path_or_module="backend/data/wc2026_qualifiers.py",
            competitions="WC2026 qualifiers (CONMEBOL/UEFA/AFC/CAF/CONCACAF)",
            match_count=len(qual),
            team_count=len(_teams_in_matches(qual)),
            date_coverage=_date_range(qual),
            date_type="real ISO dates (2023-2026)",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="home/away preserved; bundled neutral=True always",
            reliability="medium (hand-curated offline subset)",
            freshness="static but real-dated",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="active_model",
            notes="Best bundled source for last-10; partial team coverage.",
        ),
        DataSourceInventoryRow(
            source_id="cache_nt_history_fetched",
            path_or_module=str(FETCHED_HISTORY_PATH),
            competitions="API-Football NT fixtures 2018-2026",
            match_count=len(fetched),
            team_count=len(_teams_in_matches(fetched)),
            date_coverage=_date_range(fetched) if fetched else "not present locally",
            date_type="real when present",
            goals_available=bool(fetched),
            opponent_available=bool(fetched),
            home_away_neutral="from API venue when present",
            reliability="high when populated",
            freshness="depends on last fetch / cloud sync",
            offline_tests_safe=True,
            source_controlled=False,
            recommended_use="optional_cache",
            notes="Gitignored; optional via run_fetch_nt_history.py.",
        ),
        DataSourceInventoryRow(
            source_id="cache_wc2026_live_matches",
            path_or_module="backend/data/cache/wc2026_live_matches.json",
            competitions="WC2026 tournament results (manual/live append)",
            match_count=len(live),
            team_count=len(_teams_in_matches(live)),
            date_coverage=_date_range(live) if live else "not present locally",
            date_type="real when present",
            goals_available=bool(live),
            opponent_available=bool(live),
            home_away_neutral="neutral default",
            reliability="high for recorded results",
            freshness="runtime / manual",
            offline_tests_safe=True,
            source_controlled=False,
            recommended_use="optional_cache",
        ),
        DataSourceInventoryRow(
            source_id="metadata_match_dates_overrides",
            path_or_module="backend/data/match_dates_overrides.json",
            competitions="metadata for bundled tournaments",
            match_count=0,
            team_count=0,
            date_coverage="2018-2026 tournament calendars",
            date_type="curated calendar (not ingested into build_all_matches)",
            goals_available=False,
            opponent_available=True,
            home_away_neutral="metadata only",
            reliability="medium",
            freshness="static",
            offline_tests_safe=True,
            source_controlled=True,
            recommended_use="ignored",
            notes="Phase 2F temporal backtest metadata; not used by recent form today.",
        ),
        DataSourceInventoryRow(
            source_id="football_data_fixtures",
            path_or_module="backend/data/football_data.py",
            competitions="WC fixture status only",
            match_count=0,
            team_count=0,
            date_coverage="live WC 2026 schedule",
            date_type="real",
            goals_available=True,
            opponent_available=True,
            home_away_neutral="from API",
            reliability="high for fixture state",
            freshness="live API",
            offline_tests_safe=False,
            source_controlled=False,
            recommended_use="ignored",
            notes="Not NT history store; fixture_state_resolver only.",
        ),
    ]
    return rows


def load_tagged_matches(
    *,
    fetched_path: Path | None = None,
    include_optional_caches: bool = True,
) -> list[TaggedMatch]:
    """Load all match layers with source and date-confidence tags."""
    tagged: list[TaggedMatch] = []

    tournament_specs: list[tuple[str, tuple, str, date, SourceRole]] = [
        ("bundled_wc2018", WC2018_MATCHES, "FIFA World Cup", date(2018, 6, 14), "diagnostics_only"),
        ("bundled_wc2022", WC2022_MATCHES, "FIFA World Cup", date(2022, 11, 20), "diagnostics_only"),
        ("bundled_euro2024", EURO2024_MATCHES, "UEFA European Championship", date(2024, 6, 14), "diagnostics_only"),
        ("bundled_copa2024", COPA2024_MATCHES, "Copa America", date(2024, 6, 20), "diagnostics_only"),
    ]
    for source_id, raw, competition, start, role in tournament_specs:
        weight = 0.95 if "Copa" in competition or "European" in competition else 1.0
        for m in _tournament_to_nt_matches(
            raw, competition=competition, weight=weight, start=start
        ):
            tagged.append(
                TaggedMatch(m, source_id, "synthetic", role)
            )

    for q in WC2026_QUALIFIER_MATCHES:
        m = NationalTeamMatch(
            date=q.date,
            home=q.home,
            away=q.away,
            home_goals=q.home_goals,
            away_goals=q.away_goals,
            neutral=True,
            competition=q.competition,
            weight=0.75,
        )
        tagged.append(
            TaggedMatch(m, "bundled_wc2026_qualifiers", "real", "active_model")
        )

    if include_optional_caches:
        fetched = load_fetched_matches(fetched_path) if fetched_path else load_fetched_matches()
        for m in fetched:
            tagged.append(
                TaggedMatch(m, "cache_nt_history_fetched", "real", "optional_cache")
            )
        for m in load_live_matches():
            tagged.append(
                TaggedMatch(m, "cache_wc2026_live_matches", "real", "optional_cache")
            )

    return tagged


def _team_goals(match: NationalTeamMatch, team_key: str) -> int | None:
    home_key = registry_key_for_nt(match.home, REGISTRY)
    away_key = registry_key_for_nt(match.away, REGISTRY)
    if team_key == home_key:
        return match.home_goals
    if team_key == away_key:
        return match.away_goals
    return None


def classify_confidence_bucket(
    usable: int,
    real_dates: int,
    synthetic_dates: int,
) -> ConfidenceBucket:
    """Architecture doc buckets for last-10 coverage."""
    if usable <= 2:
        return "unavailable"
    if usable <= 5:
        return "low"
    if usable <= 7:
        return "medium"
    if usable >= 8 and real_dates >= 8 and synthetic_dates == 0:
        return "high"
    if usable >= 8:
        return "medium"
    return "low"


def audit_team_coverage(
    tagged_matches: list[TaggedMatch] | None = None,
    *,
    window: int = 10,
) -> list[TeamCoverageRow]:
    tagged = tagged_matches if tagged_matches is not None else load_tagged_matches()
    rows: list[TeamCoverageRow] = []

    for registry_key in sorted(FIFA_ELO_2026.keys()):
        english = registry_key.split(" (")[0]
        row = TeamCoverageRow(registry_key=registry_key, english_name=english)

        team_entries: list[tuple[str, int, TaggedMatch]] = []
        for tm in tagged:
            goals = _team_goals(tm.match, registry_key)
            if goals is None:
                continue
            team_entries.append((tm.match.date, goals, tm))

        team_entries.sort(key=lambda item: item[0], reverse=True)
        last_n = team_entries[:window]

        row.usable_matches = len(last_n)
        for _, goals, tm in last_n:
            if tm.date_confidence == "real":
                row.real_date_matches += 1
            elif tm.date_confidence == "synthetic":
                row.synthetic_date_matches += 1
            if goals is not None:
                row.matches_with_goals += 1
            row.source_breakdown[tm.source_id] = (
                row.source_breakdown.get(tm.source_id, 0) + 1
            )

        if last_n:
            row.latest_match_date = last_n[0][0]
        row.only_synthetic_dates = (
            row.usable_matches > 0 and row.real_date_matches == 0
        )
        row.confidence_bucket = classify_confidence_bucket(
            row.usable_matches,
            row.real_date_matches,
            row.synthetic_date_matches,
        )

        # Alias probe for this team
        if registry_key_for_nt(english, REGISTRY) != registry_key:
            row.alias_resolution_ok = False
            row.alias_notes.append(f"english name {english!r} did not resolve")

        rows.append(row)

    return rows


def audit_alias_probes() -> list[dict[str, Any]]:
    """Check architecture-doc alias names against NT registry resolution."""
    results: list[dict[str, Any]] = []
    for name in ALIAS_PROBE_NAMES:
        key = registry_key_for_nt(name, REGISTRY)
        via_map = NT_REGISTRY_ALIASES.get(name)
        results.append(
            {
                "probe_name": name,
                "resolved_registry_key": key,
                "via_nt_registry_aliases": via_map,
                "ok": key is not None,
            }
        )
    return results


def summarize_coverage(rows: list[TeamCoverageRow]) -> dict[str, Any]:
    buckets: dict[str, list[str]] = {
        "high": [],
        "medium": [],
        "low": [],
        "unavailable": [],
    }
    for row in rows:
        buckets[row.confidence_bucket].append(row.english_name)

    no_data = [r.english_name for r in rows if r.usable_matches == 0]
    synthetic_only = [r.english_name for r in rows if r.only_synthetic_dates]

    sorted_by_count = sorted(rows, key=lambda r: r.usable_matches)
    return {
        "total_teams": len(rows),
        "by_bucket": {k: len(v) for k, v in buckets.items()},
        "teams_by_bucket": buckets,
        "no_data_teams": no_data,
        "synthetic_only_teams": synthetic_only,
        "worst_covered": [
            {"team": r.english_name, "matches": r.usable_matches, "bucket": r.confidence_bucket}
            for r in sorted_by_count[:8]
        ],
        "best_covered": [
            {"team": r.english_name, "matches": r.usable_matches, "real_dates": r.real_date_matches, "bucket": r.confidence_bucket}
            for r in sorted(rows, key=lambda r: (-r.usable_matches, -r.real_date_matches))[:8]
        ],
    }


def football_data_api_capability_notes() -> dict[str, Any]:
    """Offline documentation of football-data.org capabilities (no live calls)."""
    return {
        "provider": "football-data.org v4",
        "current_repo_usage": "WC fixture status only (football_data.py)",
        "potential_endpoints": [
            "GET /v4/teams/{id}/matches?dateFrom=&dateTo=&status=FINISHED&limit=",
            "GET /v4/competitions/WC/matches?season=2026",
            "GET /v4/matches/{id}/head2head",
        ],
        "national_team_history": "No dedicated NT endpoint; team match subresource works for NT if team id known",
        "wc_qualifiers_friendlies": "Depends on competition subscription; WC code WC in repo config",
        "tier_limits": "Default list limit 100 matches; permission tier in filters (e.g. TIER_THREE in docs)",
        "rate_limits": "Plan-dependent; client handles 429 as RATE_LIMITED",
        "cacheable": True,
        "tests_without_live": True,
        "gaps_to_verify_with_key": [
            "Resolve WC2026 national team ids for all 48 registry teams",
            "Confirm qualifier/friendly competitions included in subscription",
            "Historical depth beyond current WC season",
        ],
        "recommended_role": "Primary API cache candidate for Phase 4R.2 (alongside existing fixture client)",
    }


def api_football_capability_notes() -> dict[str, Any]:
    """Optional fallback — not required."""
    return {
        "provider": "API-Football v3",
        "current_repo_usage": "run_fetch_nt_history.py, optional live stats",
        "status": "optional; account has been suspended in prior checks",
        "endpoints_in_repo": [
            "GET /teams?search=",
            "GET /fixtures?team=&from=&to=&status=FT",
            "Qualifier league ids in api_football.py",
        ],
        "cache_file": str(FETCHED_HISTORY_PATH),
        "required_for_architecture": False,
        "recommended_role": "Optional fallback if account restored; existing fetch script",
    }
