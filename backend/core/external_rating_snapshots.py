"""Phase 2H/2I — Historical external rating snapshots for low-leakage walk-forward."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import config

WARNING_SNAPSHOT_MISSING = "SNAPSHOT_MISSING"
WARNING_SNAPSHOT_AFTER_TOURNAMENT_START = "SNAPSHOT_AFTER_TOURNAMENT_START"
WARNING_SNAPSHOT_PARTIAL_COVERAGE = "SNAPSHOT_PARTIAL_COVERAGE"
WARNING_SNAPSHOT_PARTIAL_FIFA_COVERAGE = "SNAPSHOT_PARTIAL_FIFA_COVERAGE"
WARNING_SNAPSHOT_TEAM_UNMATCHED = "SNAPSHOT_TEAM_UNMATCHED"
WARNING_SNAPSHOT_EMPTY = "SNAPSHOT_EMPTY"
WARNING_SNAPSHOT_WORLD_ELO_MISSING = "SNAPSHOT_WORLD_ELO_MISSING"
WARNING_SNAPSHOT_FIFA_POINTS_MISSING = "SNAPSHOT_FIFA_POINTS_MISSING"
WARNING_SNAPSHOT_HAS_FIFA_POINTS = "SNAPSHOT_HAS_FIFA_POINTS"
WARNING_SNAPSHOT_HAS_WORLD_ELO = "SNAPSHOT_HAS_WORLD_ELO"
WARNING_SNAPSHOT_AS_OF_APPROXIMATE = "SNAPSHOT_AS_OF_APPROXIMATE"
WARNING_SNAPSHOT_PRODUCTION_CURRENT = "SNAPSHOT_PRODUCTION_CURRENT"

FIFA_CONSTANT_NOTES: dict[str, str] = {
    "wc2018": "from WC2018_FIFA_ELO",
    "wc2022": "from WC2022_FIFA_ELO",
    "euro2024": "from EURO2024_FIFA_ELO",
    "copa2024": "from COPA2024_FIFA_ELO",
}

TOURNAMENT_SNAPSHOT_AS_OF: dict[str, str] = {
    "wc2018": "2018-06-13",
    "wc2022": "2022-11-19",
    "euro2024": "2024-06-13",
    "copa2024": "2024-06-19",
}

TOURNAMENT_FIRST_MATCH: dict[str, str] = {
    "wc2018": "2018-06-14",
    "wc2022": "2022-11-20",
    "euro2024": "2024-06-14",
    "copa2024": "2024-06-20",
}

PRODUCTION_SNAPSHOT_KEYS: frozenset[str] = frozenset({"wc2026_current", "production_current"})

ExternalRatingField = Literal["world_elo", "fifa_points"]


def _snapshots_path() -> Path:
    return Path(config.EXTERNAL_RATING_SNAPSHOTS_PATH)


def normalize_team_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip())


def load_external_rating_snapshots() -> dict[str, Any]:
    path = _snapshots_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if k != "description"}


def get_external_rating_snapshot(dataset: str) -> dict[str, Any] | None:
    key = dataset.strip().lower()
    return load_external_rating_snapshots().get(key)


def get_team_external_rating(
    dataset: str,
    team: str,
    *,
    match_date: str | None = None,
) -> tuple[float | None, bool]:
    """Return (world_elo, available). Never reads current global_ratings.json."""
    block = get_external_rating_snapshot(dataset)
    if not block:
        return None, False
    as_of = block.get("as_of", "")
    if match_date and as_of and as_of >= match_date:
        return None, False
    teams = block.get("teams") or {}
    entry = teams.get(team.strip())
    if not entry or not isinstance(entry, dict):
        return None, False
    world_elo = entry.get("world_elo")
    if world_elo is None:
        return None, False
    return float(world_elo), True


def get_team_fifa_points(
    dataset: str,
    team: str,
    *,
    match_date: str | None = None,
) -> tuple[float | None, bool]:
    """Return (fifa_points, available) from snapshot file."""
    block = get_external_rating_snapshot(dataset)
    if not block:
        return None, False
    as_of = block.get("as_of", "")
    key = dataset.strip().lower()
    if match_date and as_of and key not in PRODUCTION_SNAPSHOT_KEYS:
        if as_of >= match_date:
            return None, False
    teams = block.get("teams") or {}
    resolved = _resolve_snapshot_team_name(team.strip(), teams)
    if not resolved:
        return None, False
    entry = teams.get(resolved)
    if not entry or not isinstance(entry, dict):
        return None, False
    fifa_points = entry.get("fifa_points")
    if fifa_points is None:
        return None, False
    return float(fifa_points), True


def _resolve_snapshot_team_name(team: str, snapshot_teams: dict[str, Any]) -> str | None:
    norm = normalize_team_name(team)
    if norm in snapshot_teams:
        return norm
    from core.global_ratings import english_name
    from data.database import FIFA_ELO_2026
    from data.nt_match import registry_key_for_nt

    try:
        reg = registry_key_for_nt(norm, set(FIFA_ELO_2026.keys()))
    except KeyError:
        reg = None
    if reg:
        en = english_name(reg)
        if en in snapshot_teams:
            return en
    return None


def list_production_team_names() -> list[str]:
    """English names for all WC 2026 production registry teams."""
    from core.global_ratings import english_name
    from data.database import FIFA_ELO_2026

    return sorted(english_name(k) for k in FIFA_ELO_2026)


def dataset_fifa_points_map(dataset: str) -> dict[str, float | None]:
    block = get_external_rating_snapshot(dataset.strip().lower())
    if not block:
        return {}
    teams = block.get("teams") or {}
    out: dict[str, float | None] = {}
    for name, entry in teams.items():
        if isinstance(entry, dict):
            fp = entry.get("fifa_points")
            out[name] = float(fp) if fp is not None else None
    return out


def dataset_internal_prior_elos(dataset: str) -> dict[str, float]:
    key = dataset.strip().lower()
    if key in PRODUCTION_SNAPSHOT_KEYS:
        from core.global_ratings import english_name
        from data.database import FIFA_ELO_2026

        return {english_name(k): float(v) for k, v in FIFA_ELO_2026.items()}
    from core.temporal_match_data import load_rating_priors

    priors = load_rating_priors(dataset.strip().lower())
    if not priors:
        return {}
    teams = priors.get("teams") or {}
    out: dict[str, float] = {}
    for name, entry in teams.items():
        if isinstance(entry, dict) and entry.get("elo") is not None:
            out[name] = float(entry["elo"])
    return out


def _dataset_teams(dataset: str) -> set[str]:
    key = dataset.lower()
    if key in PRODUCTION_SNAPSHOT_KEYS:
        return set(list_production_team_names())
    from core.fixture_metadata import TOURNAMENT_STARTS, _load_tournament_matches
    if key not in TOURNAMENT_STARTS:
        from core.temporal_backtest import load_historical_matches

        matches = load_historical_matches(key, apply_overrides=True)
        return {m.home_team for m in matches} | {m.away_team for m in matches}
    teams: set[str] = set()
    for match in _load_tournament_matches(key):
        teams.add(match.home)
        teams.add(match.away)
    return teams


def _coverage_counts(
    expected_teams: set[str],
    snapshot_teams: dict[str, Any],
) -> tuple[int, int, int]:
    with_world_elo = 0
    with_fifa = 0
    with_any = 0
    for team in expected_teams:
        entry = snapshot_teams.get(team)
        if not isinstance(entry, dict):
            continue
        has_world = entry.get("world_elo") is not None
        has_fifa = entry.get("fifa_points") is not None
        if has_world:
            with_world_elo += 1
        if has_fifa:
            with_fifa += 1
        if has_world or has_fifa:
            with_any += 1
    return with_world_elo, with_fifa, with_any


def _primary_coverage_for_mode(
    *,
    mode: str,
    world_elo_coverage: float,
    fifa_points_coverage: float,
    any_external_rating_coverage: float,
) -> float:
    if mode == "fifa_points_snapshot":
        return fifa_points_coverage
    if mode in ("world_elo_snapshot", "current_static_world_elo"):
        return world_elo_coverage
    return any_external_rating_coverage


@dataclass
class ExternalSnapshotValidationReport:
    dataset: str
    as_of: str
    teams: int
    matched: int
    missing: int
    coverage: float
    world_elo_coverage: float
    fifa_points_coverage: float
    any_external_rating_coverage: float
    leakage: str
    status: str
    warnings: list[str] = field(default_factory=list)
    unmatched_teams: list[str] = field(default_factory=list)
    rating_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_external_rating_snapshot(
    dataset: str,
    *,
    external_rating_mode: str = "any",
) -> ExternalSnapshotValidationReport:
    key = dataset.strip().lower()
    expected_teams = _dataset_teams(key)
    block = get_external_rating_snapshot(key)
    warnings: list[str] = []

    n = len(expected_teams)
    zero_cov = ExternalSnapshotValidationReport(
        dataset=key,
        as_of="",
        teams=n,
        matched=0,
        missing=n,
        coverage=0.0,
        world_elo_coverage=0.0,
        fifa_points_coverage=0.0,
        any_external_rating_coverage=0.0,
        leakage="high",
        status="fail",
        warnings=[WARNING_SNAPSHOT_MISSING],
    )

    if not block:
        return zero_cov

    as_of = block.get("as_of", "")
    rating_type = str(block.get("rating_type", ""))
    first_match = TOURNAMENT_FIRST_MATCH.get(key, "")
    if key not in PRODUCTION_SNAPSHOT_KEYS and first_match and as_of:
        try:
            if as_of >= first_match:
                warnings.append(WARNING_SNAPSHOT_AFTER_TOURNAMENT_START)
        except ValueError:
            warnings.append(WARNING_SNAPSHOT_AFTER_TOURNAMENT_START)

    if key in PRODUCTION_SNAPSHOT_KEYS:
        warnings.append(WARNING_SNAPSHOT_PRODUCTION_CURRENT)
        if not as_of:
            warnings.append(WARNING_SNAPSHOT_AS_OF_APPROXIMATE)

    snapshot_teams = block.get("teams") or {}
    if not snapshot_teams:
        warnings.append(WARNING_SNAPSHOT_EMPTY)

    seen: set[str] = set()
    duplicates: list[str] = []
    for name in snapshot_teams:
        norm = normalize_team_name(name)
        if norm in seen:
            duplicates.append(name)
        seen.add(norm)

    unmatched = [t for t in snapshot_teams if t not in expected_teams]
    if unmatched:
        warnings.append(WARNING_SNAPSHOT_TEAM_UNMATCHED)

    with_world_elo, with_fifa, with_any = _coverage_counts(expected_teams, snapshot_teams)
    world_elo_coverage = round(with_world_elo / n, 3) if n else 0.0
    fifa_points_coverage = round(with_fifa / n, 3) if n else 0.0
    any_external_rating_coverage = round(with_any / n, 3) if n else 0.0

    if with_world_elo == 0 and n:
        warnings.append(WARNING_SNAPSHOT_WORLD_ELO_MISSING)
    if with_fifa == 0 and n:
        warnings.append(WARNING_SNAPSHOT_FIFA_POINTS_MISSING)
    if with_fifa > 0:
        warnings.append(WARNING_SNAPSHOT_HAS_FIFA_POINTS)
    if with_world_elo > 0:
        warnings.append(WARNING_SNAPSHOT_HAS_WORLD_ELO)

    mode = external_rating_mode.strip().lower()
    primary = _primary_coverage_for_mode(
        mode=mode,
        world_elo_coverage=world_elo_coverage,
        fifa_points_coverage=fifa_points_coverage,
        any_external_rating_coverage=any_external_rating_coverage,
    )

    if mode == "fifa_points_snapshot":
        min_cov = (
            config.PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE
            if key in PRODUCTION_SNAPSHOT_KEYS
            else config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
        )
        if fifa_points_coverage < min_cov and n:
            warnings.append(WARNING_SNAPSHOT_PARTIAL_FIFA_COVERAGE)
        elif with_fifa < n and with_fifa > 0:
            warnings.append(WARNING_SNAPSHOT_PARTIAL_FIFA_COVERAGE)
    elif mode in ("world_elo_snapshot", "current_static_world_elo", "any"):
        if world_elo_coverage < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION and n:
            if mode != "fifa_points_snapshot":
                warnings.append(WARNING_SNAPSHOT_PARTIAL_COVERAGE)

    matched = len(expected_teams & set(snapshot_teams.keys()))
    missing = len(expected_teams - set(snapshot_teams.keys()))

    leakage = snapshot_leakage_label(
        key,
        coverage=primary,
        warnings=warnings,
        external_rating_mode=mode,
        fifa_points_coverage=fifa_points_coverage,
        world_elo_coverage=world_elo_coverage,
    )

    status = "ok"
    if WARNING_SNAPSHOT_MISSING in warnings or WARNING_SNAPSHOT_AFTER_TOURNAMENT_START in warnings:
        status = "fail"
    elif duplicates:
        status = "fail"
        warnings.append("SNAPSHOT_DUPLICATE_TEAM")
    elif mode == "fifa_points_snapshot":
        min_cov = (
            config.PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE
            if key in PRODUCTION_SNAPSHOT_KEYS
            else config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
        )
        if fifa_points_coverage == 0.0 or WARNING_SNAPSHOT_EMPTY in warnings:
            status = "incomplete"
        elif fifa_points_coverage < min_cov:
            status = "incomplete"
    elif primary == 0.0 or WARNING_SNAPSHOT_EMPTY in warnings:
        status = "incomplete"
    elif primary < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:
        status = "incomplete"

    return ExternalSnapshotValidationReport(
        dataset=key,
        as_of=as_of,
        teams=n,
        matched=matched,
        missing=missing,
        coverage=primary,
        world_elo_coverage=world_elo_coverage,
        fifa_points_coverage=fifa_points_coverage,
        any_external_rating_coverage=any_external_rating_coverage,
        leakage=leakage,
        status=status,
        warnings=sorted(set(warnings)),
        unmatched_teams=unmatched[:10],
        rating_type=rating_type,
    )


def snapshot_leakage_label(
    dataset: str,
    *,
    coverage: float | None = None,
    warnings: list[str] | None = None,
    external_rating_mode: str = "any",
    fifa_points_coverage: float | None = None,
    world_elo_coverage: float | None = None,
) -> str:
    report = (
        validate_external_rating_snapshot(dataset, external_rating_mode=external_rating_mode)
        if coverage is None
        else None
    )
    mode = external_rating_mode.strip().lower()
    fifa_cov = (
        fifa_points_coverage
        if fifa_points_coverage is not None
        else (report.fifa_points_coverage if report else 0.0)
    )
    world_cov = (
        world_elo_coverage
        if world_elo_coverage is not None
        else (report.world_elo_coverage if report else 0.0)
    )
    cov = coverage if coverage is not None else (report.coverage if report else 0.0)
    warns = warnings if warnings is not None else (report.warnings if report else [])

    if dataset.strip().lower() in PRODUCTION_SNAPSHOT_KEYS:
        if WARNING_SNAPSHOT_MISSING in warns:
            return "high"
        return "production_current"

    if WARNING_SNAPSHOT_MISSING in warns or WARNING_SNAPSHOT_AFTER_TOURNAMENT_START in warns:
        return "high"

    if mode == "fifa_points_snapshot":
        if fifa_cov >= config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION:
            return "low"
        if fifa_cov > 0:
            return "medium"
        return "high"

    if mode == "world_elo_snapshot":
        if world_cov >= config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:
            return "low"
        if world_cov > 0:
            return "medium"
        return "high"

    if cov >= config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:
        return "low"
    if cov > 0:
        return "medium"
    return "high"


def external_snapshot_activation_ready(
    datasets: list[str] | None = None,
) -> tuple[bool, list[ExternalSnapshotValidationReport]]:
    from core.fixture_metadata import TOURNAMENT_STARTS

    keys = datasets or list(TOURNAMENT_STARTS.keys())
    reports = [
        validate_external_rating_snapshot(k, external_rating_mode="world_elo_snapshot")
        for k in keys
    ]
    ready = all(
        r.world_elo_coverage >= config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION
        and r.leakage == "low"
        and WARNING_SNAPSHOT_AFTER_TOURNAMENT_START not in r.warnings
        for r in reports
    )
    return ready, reports


def external_fifa_points_activation_ready(
    datasets: list[str] | None = None,
) -> tuple[bool, list[ExternalSnapshotValidationReport]]:
    from core.fixture_metadata import TOURNAMENT_STARTS

    keys = datasets or list(TOURNAMENT_STARTS.keys())
    reports = [
        validate_external_rating_snapshot(k, external_rating_mode="fifa_points_snapshot")
        for k in keys
    ]
    ready = all(
        r.fifa_points_coverage >= config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
        and r.leakage in ("low", "medium")
        and WARNING_SNAPSHOT_AFTER_TOURNAMENT_START not in r.warnings
        for r in reports
    )
    return ready, reports


def external_fifa_points_production_ready(
    dataset: str | None = None,
) -> tuple[bool, ExternalSnapshotValidationReport]:
    key = (dataset or config.PRODUCTION_FIFA_SNAPSHOT_DATASET).strip().lower()
    report = validate_external_rating_snapshot(key, external_rating_mode="fifa_points_snapshot")
    ready = (
        report.fifa_points_coverage >= config.PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE
        and report.status == "ok"
        and WARNING_SNAPSHOT_MISSING not in report.warnings
    )
    return ready, report


def build_wc2026_current_snapshot_block() -> dict[str, Any]:
    """Current production FIFA ranking points for all WC 2026 registry teams (Phase 3B)."""
    from core.global_ratings import english_name
    from data.database import FIFA_ELO_2026

    teams: dict[str, dict[str, Any]] = {}
    for reg_key, fifa_pts in FIFA_ELO_2026.items():
        en = english_name(reg_key)
        teams[en] = {
            "world_elo": None,
            "fifa_points": int(fifa_pts),
            "external_rank": None,
            "confidence": 0.85,
            "notes": "from FIFA_ELO_2026",
        }
    return {
        "as_of": "",
        "as_of_label": "June 2026 (approximate, per FIFA_ELO_2026 repo comment)",
        "source": "repo_FIFA_ELO_2026",
        "rating_type": "fifa_ranking_points_current",
        "teams": dict(sorted(teams.items())),
    }


def build_fifa_points_snapshot_document() -> dict[str, Any]:
    """Build snapshot JSON from repo FIFA ranking-point constants (Phase 2I)."""
    from core.fixture_metadata import TOURNAMENT_STARTS, _fifa_elo_map, _load_tournament_matches

    doc: dict[str, Any] = {
        "description": (
            "Pre-tournament external rating snapshots (Phase 2I). "
            "fifa_points populated from repo WC/EURO/COPA FIFA_ELO constants. "
            "world_elo remains null until true World Elo (eloratings-style) data is curated. "
            "Do not mislabel FIFA points as World Elo."
        ),
    }
    for key in TOURNAMENT_STARTS:
        teams: set[str] = set()
        for match in _load_tournament_matches(key):
            teams.add(match.home)
            teams.add(match.away)
        fifa_map = _fifa_elo_map(key)
        note_prefix = FIFA_CONSTANT_NOTES.get(key, "from repo FIFA constant")
        doc[key] = {
            "as_of": TOURNAMENT_SNAPSHOT_AS_OF[key],
            "source": "repo_pre_tournament_fifa_points",
            "rating_type": "fifa_ranking_points",
            "teams": {
                name: {
                    "world_elo": None,
                    "fifa_points": fifa_map.get(name),
                    "external_rank": None,
                    "confidence": 0.85,
                    "notes": note_prefix if name in fifa_map else "missing from repo FIFA constant",
                }
                for name in sorted(teams)
            },
        }
    return doc


def build_full_snapshot_document() -> dict[str, Any]:
    """Tournament historical snapshots plus current production WC 2026 FIFA snapshot."""
    doc = build_fifa_points_snapshot_document()
    prod_key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    doc[prod_key] = build_wc2026_current_snapshot_block()
    return doc


def build_placeholder_snapshot_document() -> dict[str, Any]:
    """Backward-compatible alias — tournament + production FIFA snapshots."""
    return build_full_snapshot_document()


def write_external_rating_snapshots_file(path: Path | None = None) -> Path:
    target = path or _snapshots_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(build_full_snapshot_document(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target


def format_snapshot_validation_table(
    reports: list[ExternalSnapshotValidationReport],
) -> str:
    header = (
        f"{'dataset':10} | {'as_of':>10} | {'teams':>5} | {'match':>5} | "
        f"{'miss':>4} | {'w_elo':>5} | {'fifa':>5} | {'any':>5} | "
        f"{'leak':>4} | {'status':>10} | warnings"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        warn = ",".join(r.warnings) if r.warnings else "-"
        lines.append(
            f"{r.dataset:10} | {r.as_of:>10} | {r.teams:5d} | {r.matched:5d} | "
            f"{r.missing:4d} | {r.world_elo_coverage:5.2f} | {r.fifa_points_coverage:5.2f} | "
            f"{r.any_external_rating_coverage:5.2f} | {r.leakage:>4} | {r.status:>10} | {warn}"
        )
    return "\n".join(lines)
