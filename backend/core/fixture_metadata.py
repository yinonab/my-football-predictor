"""Phase 2F — Fixture metadata generation, validation, and low-leakage classification."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import config

TOURNAMENT_STARTS: dict[str, tuple[str, date]] = {
    "wc2018": ("FIFA World Cup 2018", date(2018, 6, 14)),
    "wc2022": ("FIFA World Cup 2022", date(2022, 11, 20)),
    "euro2024": ("UEFA Euro 2024", date(2024, 6, 14)),
    "copa2024": ("Copa America 2024", date(2024, 6, 20)),
}

KNOWN_KICKOFFS: dict[str, dict[tuple[str, str], str]] = {
    "wc2022": {("Qatar", "Ecuador"): "19:00"},
}

PRIOR_AS_OF: dict[str, str] = {
    "wc2018": "2018-06-13",
    "wc2022": "2022-11-19",
    "euro2024": "2024-06-13",
    "copa2024": "2024-06-19",
}

PRIOR_SOURCES: dict[str, str] = {
    "wc2018": "data/wc2018.py WC2018_FIFA_ELO (pre-tournament repo snapshot)",
    "wc2022": "data/wc2022.py WC2022_FIFA_ELO (October 2022 pre-tournament)",
    "euro2024": "data/euro2024.py EURO2024_FIFA_ELO (pre-tournament repo snapshot)",
    "copa2024": "data/copa2024.py COPA2024_FIFA_ELO (pre-tournament repo snapshot)",
}


def _overrides_path() -> Path:
    return Path(config.TEMPORAL_MATCH_DATES_OVERRIDES_PATH)


def _priors_path() -> Path:
    return Path(config.TEMPORAL_RATING_PRIORS_PATH)


def _match_pair_key(home: str, away: str) -> tuple[str, str]:
    return (home.strip(), away.strip())


def _load_tournament_matches(dataset: str) -> tuple:
    key = dataset.lower()
    if key == "wc2018":
        from data.wc2018 import WC2018_MATCHES

        return WC2018_MATCHES
    if key == "wc2022":
        from data.wc2022 import WC2022_MATCHES

        return WC2022_MATCHES
    if key == "euro2024":
        from data.euro2024 import EURO2024_MATCHES

        return EURO2024_MATCHES
    if key == "copa2024":
        from data.copa2024 import COPA2024_MATCHES

        return COPA2024_MATCHES
    raise ValueError(f"Unknown tournament dataset: {dataset}")


def _fifa_elo_map(dataset: str) -> dict[str, int]:
    key = dataset.lower()
    if key == "wc2018":
        from data.wc2018 import WC2018_FIFA_ELO

        return dict(WC2018_FIFA_ELO)
    if key == "wc2022":
        from data.wc2022 import WC2022_FIFA_ELO

        return dict(WC2022_FIFA_ELO)
    if key == "euro2024":
        from data.euro2024 import EURO2024_FIFA_ELO

        return dict(EURO2024_FIFA_ELO)
    if key == "copa2024":
        from data.copa2024 import COPA2024_FIFA_ELO

        return dict(COPA2024_FIFA_ELO)
    return {}


def build_repo_fixture_overrides(dataset: str) -> list[dict[str, Any]]:
    """Build curated fixture rows from repo match tuples (one match per day schedule)."""
    key = dataset.lower()
    if key not in TOURNAMENT_STARTS:
        raise ValueError(f"No fixture config for {dataset}")
    _, start = TOURNAMENT_STARTS[key]
    matches = _load_tournament_matches(key)
    kickoffs = KNOWN_KICKOFFS.get(key, {})
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        match_date = (start + timedelta(days=index)).isoformat()
        neutral = getattr(match, "neutral", True)
        stage = getattr(match, "stage", "group")
        pair = _match_pair_key(match.home, match.away)
        row: dict[str, Any] = {
            "home_team": match.home,
            "away_team": match.away,
            "date": match_date,
            "sequence_index": index + 1,
            "stage": stage,
            "neutral_ground": neutral,
            "source": "repo_match_order_one_per_day",
        }
        if pair in kickoffs:
            row["kickoff_time"] = kickoffs[pair]
        rows.append(row)
    return rows


def build_all_repo_fixture_overrides() -> dict[str, list[dict[str, Any]]]:
    return {key: build_repo_fixture_overrides(key) for key in TOURNAMENT_STARTS}


def write_match_dates_overrides_file(path: Path | None = None) -> Path:
    """Write complete overrides JSON from repo tournament data."""
    target = path or _overrides_path()
    payload: dict[str, Any] = {
        "description": (
            "Curated fixture metadata from repo match order + tournament start dates "
            "(Phase 2F). Dates follow nt_history_bundle one-match-per-day schedule. "
            "kickoff_time only where explicitly known in repo — do not invent times."
        ),
        "data_quality_note": (
            "exact_datetime when kickoff_time present; otherwise exact_date with "
            "deterministic sequence_index per tournament."
        ),
    }
    for key, rows in build_all_repo_fixture_overrides().items():
        payload[key] = rows
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target


def build_rating_priors_document() -> dict[str, Any]:
    doc: dict[str, Any] = {
        "description": (
            "Pre-tournament Elo priors from FIFA_ELO constants in repository modules. "
            "Not walk-forward historical Elo — label source in each block."
        ),
    }
    for key in TOURNAMENT_STARTS:
        elo_map = _fifa_elo_map(key)
        doc[key] = {
            "as_of": PRIOR_AS_OF[key],
            "source": PRIOR_SOURCES[key],
            "quality_note": "repo_static_fifa_elo_pre_tournament",
            "teams": {
                name: {"elo": elo, "confidence": 0.85} for name, elo in sorted(elo_map.items())
            },
        }
    return doc


def write_rating_priors_file(path: Path | None = None) -> Path:
    target = path or _priors_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(build_rating_priors_document(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target


def historical_match_pairs(dataset: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for match in _load_tournament_matches(dataset):
        pairs.add(_match_pair_key(match.home, match.away))
    return pairs


def normalize_team_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip())


@dataclass
class OverrideValidationReport:
    dataset: str
    matches: int
    overrides: int
    matched: int
    unmatched: int
    duplicates: int
    exact_datetime: int
    exact_date: int
    estimated: int
    status: str
    unmatched_pairs: list[str] = field(default_factory=list)
    duplicate_pairs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_dataset_overrides(dataset: str) -> OverrideValidationReport:
    key = dataset.lower()
    if key not in TOURNAMENT_STARTS:
        raise ValueError(f"Unknown tournament dataset: {dataset}")
    repo_matches = list(_load_tournament_matches(key))
    overrides = []
    path = _overrides_path()
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        overrides = list(data.get(key, []))

    by_seq: dict[int, dict[str, Any]] = {}
    duplicate_pairs: list[str] = []
    pair_counts: dict[tuple[str, str], int] = {}
    exact_dt = exact_d = 0
    unmatched_pairs: list[str] = []
    matched = 0

    for item in overrides:
        seq = int(item.get("sequence_index", 0))
        if seq in by_seq:
            unmatched_pairs.append(f"duplicate_sequence:{seq}")
        by_seq[seq] = item
        pair = _match_pair_key(item["home_team"], item["away_team"])
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
        date_str = item.get("date", "")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            unmatched_pairs.append(f"bad_date:{pair[0]} vs {pair[1]}")
        if item.get("kickoff_time"):
            exact_dt += 1
        else:
            exact_d += 1

    duplicate_pairs = [
        f"{h} vs {a} (x{c})" for (h, a), c in pair_counts.items() if c > 1
    ]

    for index, match in enumerate(repo_matches, start=1):
        ov = by_seq.get(index)
        if not ov:
            unmatched_pairs.append(f"missing_sequence:{index}")
            continue
        expected = _match_pair_key(match.home, match.away)
        actual = _match_pair_key(ov["home_team"], ov["away_team"])
        if expected != actual:
            unmatched_pairs.append(
                f"team_mismatch_seq_{index}:{actual[0]} vs {actual[1]}"
            )
            continue
        matched += 1

    seq_by_day: dict[str, list[int]] = {}
    for item in overrides:
        day = item.get("date", "")
        if not item.get("kickoff_time"):
            seq_by_day.setdefault(day, []).append(int(item.get("sequence_index", 0)))
    seq_ok = all(len(set(seqs)) == len(seqs) for seqs in seq_by_day.values())

    duplicates = sum(1 for c in pair_counts.values() if c > 1)
    estimated = len(repo_matches) - matched

    if unmatched_pairs or not seq_ok:
        status = "fail"
    elif matched < len(repo_matches) or len(overrides) != len(repo_matches):
        status = "incomplete"
    else:
        status = "ok"

    return OverrideValidationReport(
        dataset=key,
        matches=len(repo_matches),
        overrides=len(overrides),
        matched=matched,
        unmatched=len(unmatched_pairs),
        duplicates=duplicates,
        exact_datetime=exact_dt,
        exact_date=exact_d,
        estimated=estimated,
        status=status,
        unmatched_pairs=unmatched_pairs[:10],
        duplicate_pairs=duplicate_pairs[:10],
    )


def format_override_validation_table(reports: list[OverrideValidationReport]) -> str:
    header = (
        f"{'dataset':10} | {'matches':>7} | {'overrides':>9} | {'matched':>7} | "
        f"{'unmatched':>9} | {'dups':>4} | {'ex_dt':>5} | {'ex_d':>4} | "
        f"{'est':>3} | status"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        lines.append(
            f"{r.dataset:10} | {r.matches:7d} | {r.overrides:9d} | {r.matched:7d} | "
            f"{r.unmatched:9d} | {r.duplicates:4d} | {r.exact_datetime:5d} | "
            f"{r.exact_date:4d} | {r.estimated:3d} | {r.status}"
        )
    return "\n".join(lines)


@dataclass
class DatasetCoverageReport:
    dataset: str
    matches: int
    exact_datetime_count: int
    exact_date_count: int
    estimated_order_count: int
    missing_date_count: int
    override_coverage: float
    prior_coverage: float
    leakage_label: str
    data_quality_score: float
    low_leakage_ready: bool
    external_snapshot_available: bool = False
    external_snapshot_coverage: float = 0.0
    external_snapshot_as_of: str = ""
    snapshot_leakage: str = "high"
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _same_day_ordering_ok(matches: list[Any]) -> bool:
    by_day: dict[str, list[Any]] = {}
    for m in matches:
        by_day.setdefault(m.date, []).append(m)
    for day_matches in by_day.values():
        if len(day_matches) <= 1:
            continue
        has_kickoff = any(getattr(m, "kickoff_time", None) for m in day_matches)
        if has_kickoff:
            continue
        seqs = [getattr(m, "sequence_index", 0) for m in day_matches]
        if len(set(seqs)) != len(seqs):
            return False
    return True


def classify_dataset_leakage(
    matches: list[Any],
    *,
    world_elo_mode: str = "none",
    external_rating_mode: str = "none",
    prior_mode: str = "default_internal",
    dataset_key: str = "",
) -> tuple[str, bool, list[str]]:
    """Return (leakage_label, low_leakage_ready, blockers)."""
    from core.external_rating_mode import resolve_external_rating_mode
    from core.temporal_match_data import load_rating_priors

    ext_mode = resolve_external_rating_mode(
        external_rating_mode=external_rating_mode if external_rating_mode != "none" else None,
        world_elo_mode=world_elo_mode,
    )

    blockers: list[str] = []
    if ext_mode == "current_static_world_elo" or world_elo_mode == "current_static":
        blockers.append("WORLD_ELO_CURRENT_STATIC_HISTORICAL")
        return "high", False, blockers

    if not matches:
        blockers.append("NO_MATCHES")
        return "high", False, blockers

    estimated = sum(1 for m in matches if m.data_quality == "estimated_order")
    missing = sum(1 for m in matches if m.data_quality == "missing_date")
    exact_dt = sum(1 for m in matches if m.data_quality == "exact_datetime")
    exact_d = sum(1 for m in matches if m.data_quality == "exact_date")

    if missing > 0:
        blockers.append("MATCH_DATES_MISSING")
    if estimated > 0:
        blockers.append("MATCH_DATES_ESTIMATED")

    if not _same_day_ordering_ok(matches):
        blockers.append("SAME_DAY_ORDER_AMBIGUOUS")

    priors = load_rating_priors(dataset_key) if dataset_key else None
    if prior_mode == "tournament_prior_file":
        if not priors or not priors.get("teams"):
            blockers.append("PRIORS_MISSING")
        elif matches:
            first = min(m.date for m in matches)
            if priors.get("as_of", "") >= first:
                blockers.append("PRIOR_AS_OF_AFTER_FIRST_MATCH")

    if ext_mode == "world_elo_snapshot" and dataset_key:
        from core.external_rating_snapshots import (
            WARNING_SNAPSHOT_AFTER_TOURNAMENT_START,
            validate_external_rating_snapshot,
        )

        snap_report = validate_external_rating_snapshot(
            dataset_key, external_rating_mode="world_elo_snapshot"
        )
        if WARNING_SNAPSHOT_AFTER_TOURNAMENT_START in snap_report.warnings:
            blockers.append("EXTERNAL_SNAPSHOT_AFTER_TOURNAMENT_START")
        if snap_report.world_elo_coverage < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:
            blockers.append("EXTERNAL_SNAPSHOT_PARTIAL_COVERAGE")
        if snap_report.world_elo_coverage == 0.0:
            blockers.append("EXTERNAL_SNAPSHOT_EMPTY")

    if ext_mode == "fifa_points_snapshot" and dataset_key:
        from core.external_rating_snapshots import (
            WARNING_SNAPSHOT_AFTER_TOURNAMENT_START,
            validate_external_rating_snapshot,
        )

        snap_report = validate_external_rating_snapshot(
            dataset_key, external_rating_mode="fifa_points_snapshot"
        )
        if WARNING_SNAPSHOT_AFTER_TOURNAMENT_START in snap_report.warnings:
            blockers.append("EXTERNAL_SNAPSHOT_AFTER_TOURNAMENT_START")
        if (
            snap_report.fifa_points_coverage
            < config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
        ):
            blockers.append("EXTERNAL_FIFA_PARTIAL_COVERAGE")
        if snap_report.fifa_points_coverage == 0.0:
            blockers.append("EXTERNAL_FIFA_POINTS_EMPTY")

    if blockers:
        high_blockers = (
            "MATCH_DATES_MISSING",
            "PRIOR_AS_OF_AFTER_FIRST_MATCH",
            "WORLD_ELO_CURRENT_STATIC_HISTORICAL",
            "EXTERNAL_SNAPSHOT_AFTER_TOURNAMENT_START",
        )
        if any(b in blockers for b in high_blockers):
            return "high", False, blockers
        if ext_mode == "world_elo_snapshot" and "EXTERNAL_SNAPSHOT_EMPTY" in blockers:
            return "high", False, blockers
        if ext_mode == "fifa_points_snapshot" and "EXTERNAL_FIFA_POINTS_EMPTY" in blockers:
            return "high", False, blockers
        return "medium", False, blockers

    if exact_dt > 0 and exact_dt == len(matches):
        return "low", True, []
    if exact_d == len(matches) and _same_day_ordering_ok(matches):
        if prior_mode == "tournament_prior_file":
            if not priors or not priors.get("teams"):
                return "medium", False, blockers
            if priors.get("as_of", "") >= min(m.date for m in matches):
                blockers.append("PRIOR_AS_OF_AFTER_FIRST_MATCH")
                return "high", False, blockers
        return "low", True, []
    if exact_dt + exact_d == len(matches):
        if prior_mode == "tournament_prior_file":
            if not priors or not priors.get("teams"):
                return "medium", False, blockers
        return "low", True, []

    return "medium", False, blockers


def audit_dataset_coverage(
    dataset: str,
    *,
    prior_mode: str = "tournament_prior_file",
    world_elo_mode: str = "none",
) -> DatasetCoverageReport:
    from core.temporal_backtest import load_historical_matches
    from core.temporal_match_data import (
        WARNING_MATCH_DATES_ESTIMATED,
        WARNING_PRIORS_MISSING,
        WARNING_SAME_DAY_ORDER_AMBIGUOUS,
        load_match_date_overrides,
        load_rating_priors,
    )

    key = dataset.lower()
    matches = load_historical_matches(key, apply_overrides=True)
    if key in TOURNAMENT_STARTS:
        raw_count = len(_load_tournament_matches(key))
    else:
        raw_count = len(matches)
    overrides = load_match_date_overrides(key)
    override_coverage = round(len(overrides) / raw_count, 3) if raw_count else 0.0
    priors = load_rating_priors(key)
    teams = {m.home_team for m in matches} | {m.away_team for m in matches}
    prior_teams = set(priors.get("teams", {}).keys()) if priors else set()
    prior_coverage = round(len(teams & prior_teams) / len(teams), 3) if teams else 0.0

    exact_dt = sum(1 for m in matches if m.data_quality == "exact_datetime")
    exact_d = sum(1 for m in matches if m.data_quality == "exact_date")
    estimated = sum(1 for m in matches if m.data_quality == "estimated_order")
    missing = sum(1 for m in matches if m.data_quality == "missing_date")

    leakage, low_ready, blockers = classify_dataset_leakage(
        matches,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
        dataset_key=key,
    )

    warnings: list[str] = []
    if estimated:
        warnings.append(WARNING_MATCH_DATES_ESTIMATED)
    if not prior_teams and prior_mode == "tournament_prior_file":
        warnings.append(WARNING_PRIORS_MISSING)
    if not _same_day_ordering_ok(matches):
        warnings.append(WARNING_SAME_DAY_ORDER_AMBIGUOUS)

    from core.external_rating_snapshots import (
        WARNING_SNAPSHOT_EMPTY,
        WARNING_SNAPSHOT_PARTIAL_COVERAGE,
        get_external_rating_snapshot,
        validate_external_rating_snapshot,
    )

    snap_block = get_external_rating_snapshot(key)
    snap_report = validate_external_rating_snapshot(key)
    if snap_report.warnings:
        warnings.extend(snap_report.warnings)
    if WARNING_SNAPSHOT_EMPTY in snap_report.warnings:
        pass
    elif WARNING_SNAPSHOT_PARTIAL_COVERAGE in snap_report.warnings:
        pass

    n = len(matches) or 1
    score = round((exact_dt * 1.0 + exact_d * 0.85 + estimated * 0.5) / n, 3)

    return DatasetCoverageReport(
        dataset=key,
        matches=len(matches),
        exact_datetime_count=exact_dt,
        exact_date_count=exact_d,
        estimated_order_count=estimated,
        missing_date_count=missing,
        override_coverage=override_coverage,
        prior_coverage=prior_coverage,
        leakage_label=leakage,
        data_quality_score=score,
        low_leakage_ready=low_ready,
        external_snapshot_available=bool(snap_block),
        external_snapshot_coverage=snap_report.coverage,
        external_snapshot_as_of=snap_report.as_of,
        snapshot_leakage=snap_report.leakage,
        blockers=blockers,
        warnings=sorted(set(warnings)),
    )


def format_coverage_table(reports: list[DatasetCoverageReport]) -> str:
    header = (
        f"{'dataset':10} | {'n':>4} | {'ex_dt':>5} | {'ex_d':>4} | {'est':>4} | "
        f"{'miss':>4} | {'ovr%':>5} | {'pri%':>5} | {'ext%':>5} | {'snap':>4} | "
        f"{'leak':>4} | {'score':>5} | {'ready':>5} | blockers"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        block = ",".join(r.blockers) if r.blockers else "-"
        ready = "yes" if r.low_leakage_ready else "no"
        snap = "yes" if r.external_snapshot_available else "no"
        lines.append(
            f"{r.dataset:10} | {r.matches:4d} | {r.exact_datetime_count:5d} | "
            f"{r.exact_date_count:4d} | {r.estimated_order_count:4d} | "
            f"{r.missing_date_count:4d} | {r.override_coverage:5.2f} | "
            f"{r.prior_coverage:5.2f} | {r.external_snapshot_coverage:5.2f} | "
            f"{snap:>4} | {r.leakage_label:>4} | {r.data_quality_score:5.2f} | "
            f"{ready:>5} | {block}"
        )
    return "\n".join(lines)
