"""Phase 4L — Resolve fixture state from curated data, overrides, and API-Football."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import config
from core.fixture_metadata import TOURNAMENT_STARTS, _match_pair_key
from core.fixture_state import (
    API_FOOTBALL_ACCOUNT_SUSPENDED,
    API_FOOTBALL_UNAVAILABLE,
    EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE,
    FixtureState,
    apply_fixture_state_rules,
)
from core.global_ratings import english_name
from core.team_ratings import build_all_matches
from data.api_football import ApiFootballClient
from data.nt_match import NT_REGISTRY_ALIASES

logger = logging.getLogger(__name__)

_LIVE_API_STATUSES = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT"})
_COMPLETED_API_STATUSES = frozenset({"FT", "AET", "PEN"})
_SCHEDULED_API_STATUSES = frozenset({"NS", "TBD", "PST"})


def _overrides_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    base = Path(__file__).resolve().parent.parent
    return base / config.FIXTURE_STATE_OVERRIDES_PATH


def _normalize_en(name: str) -> str:
    base = name.split(" (")[0].strip()
    return NT_REGISTRY_ALIASES.get(base, base)


def _pair_keys(home: str, away: str) -> set[tuple[str, str]]:
    h = _normalize_en(home)
    a = _normalize_en(away)
    return {(h, a), (a, h)}


def classify_api_football_error(exc: Exception) -> str:
    """Map API-Football failure to a safe diagnostic code (no secrets)."""
    msg = str(exc).lower()
    if "suspended" in msg:
        return API_FOOTBALL_ACCOUNT_SUSPENDED
    return API_FOOTBALL_UNAVAILABLE


def _api_status_to_fixture_status(short: str) -> str:
    s = (short or "").upper()
    if s in _COMPLETED_API_STATUSES:
        return "completed"
    if s in _LIVE_API_STATUSES:
        return "live"
    if s in _SCHEDULED_API_STATUSES:
        return "scheduled"
    return "unknown"


def _load_manual_overrides(path: Path | None = None) -> list[dict[str, Any]]:
    p = _overrides_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(data.get("fixtures") or [])


def _match_manual_override(
    home: str,
    away: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    home_n = _normalize_en(home)
    away_n = _normalize_en(away)
    target = frozenset({home_n, away_n})
    for row in rows:
        row_home = _normalize_en(row.get("home_team", ""))
        row_away = _normalize_en(row.get("away_team", ""))
        if frozenset({row_home, row_away}) == target:
            return row
    return None


def _state_from_manual_row(
    home_resolved: str,
    away_resolved: str,
    row: dict[str, Any],
) -> FixtureState:
    row_home = _normalize_en(row.get("home_team", ""))
    req_home = _normalize_en(home_resolved)
    swap = bool(row_home and row_home != req_home)

    ah = row.get("actual_home_goals")
    aa = row.get("actual_away_goals")
    if swap and ah is not None and aa is not None:
        ah, aa = aa, ah

    status = str(row.get("fixture_status", "unknown"))
    kickoff = row.get("kickoff_time_utc") or row.get("kickoff_time")
    if kickoff and len(str(kickoff)) == 10:
        kickoff = f"{kickoff}T00:00:00+00:00"

    return FixtureState(
        home_team=home_resolved,
        away_team=away_resolved,
        fixture_status=status,  # type: ignore[arg-type]
        kickoff_time_utc=kickoff,
        actual_home_goals=int(ah) if ah is not None else None,
        actual_away_goals=int(aa) if aa is not None else None,
        actual_score_available=ah is not None and aa is not None,
        source="manual_override",
        source_available=True,
        venue_name=row.get("venue_name"),
        venue_city=row.get("venue_city"),
        venue_country=row.get("venue_country"),
    )


def _lookup_historical_result(home_en: str, away_en: str) -> dict[str, Any] | None:
    """Match finished games from bundled history (no invented data)."""
    from data.database import FIFA_ELO_2026

    best: dict[str, Any] | None = None
    for match in build_all_matches():
        m_home = _normalize_en(match.home)
        m_away = _normalize_en(match.away)
        if {m_home, m_away} != {home_en, away_en}:
            continue
        if best is None or match.date > best["date"]:
            swap = m_home != home_en
            hg, ag = match.home_goals, match.away_goals
            if swap:
                hg, ag = ag, hg
            best = {
                "date": match.date,
                "actual_home_goals": hg,
                "actual_away_goals": ag,
                "neutral_ground": match.neutral,
                "stage": getattr(match, "stage", None),
            }
    return best


def _lookup_curated_metadata(home_en: str, away_en: str) -> dict[str, Any] | None:
    """Search match_dates_overrides across known tournament datasets."""
    from core.temporal_match_data import load_match_date_overrides

    pair = _match_pair_key(home_en, away_en)
    rev = (pair[1], pair[0])
    for dataset in TOURNAMENT_STARTS:
        for row in load_match_date_overrides(dataset):
            row_pair = _match_pair_key(row.get("home_team", ""), row.get("away_team", ""))
            if row_pair not in (pair, rev):
                continue
            kickoff = None
            if row.get("kickoff_time") and row.get("date"):
                kickoff = f"{row['date']}T{row['kickoff_time']}:00+00:00"
            elif row.get("date"):
                kickoff = f"{row['date']}T00:00:00+00:00"
            return {
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "date": row.get("date"),
                "kickoff_time_utc": kickoff,
                "stage": row.get("stage"),
                "neutral_ground": row.get("neutral_ground", True),
                "swap": row_pair == rev,
            }
    return None


def _state_from_curated(
    home_resolved: str,
    away_resolved: str,
    meta: dict[str, Any],
    historical: dict[str, Any] | None,
    *,
    reference_date: date | None = None,
) -> FixtureState:
    ref = reference_date or date.today()
    match_date_str = meta.get("date") or ""
    kickoff = meta.get("kickoff_time_utc")

    status: str = "unknown"
    ah: int | None = None
    aa: int | None = None

    if historical:
        status = "completed"
        ah = int(historical["actual_home_goals"])
        aa = int(historical["actual_away_goals"])
    elif match_date_str:
        try:
            match_day = date.fromisoformat(match_date_str[:10])
            if match_day > ref:
                status = "scheduled"
            elif match_day == ref:
                status = "unknown"
            else:
                status = "unknown"
        except ValueError:
            status = "unknown"

    if meta.get("swap") and ah is not None and aa is not None:
        ah, aa = aa, ah

    return FixtureState(
        home_team=home_resolved,
        away_team=away_resolved,
        fixture_status=status,  # type: ignore[arg-type]
        kickoff_time_utc=kickoff,
        actual_home_goals=ah,
        actual_away_goals=aa,
        actual_score_available=ah is not None and aa is not None,
        source="curated_fixture",
        source_available=True,
    )


def _pick_best_api_fixture(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None

    def sort_key(fx: dict[str, Any]) -> tuple[int, str]:
        fix = fx.get("fixture") or {}
        status = ((fix.get("status") or {}).get("short") or "").upper()
        date_s = fix.get("date") or ""
        priority = 0
        if status in _COMPLETED_API_STATUSES:
            priority = 3
        elif status in _LIVE_API_STATUSES:
            priority = 2
        elif status in _SCHEDULED_API_STATUSES:
            priority = 1
        return (priority, date_s)

    return sorted(items, key=sort_key, reverse=True)[0]


def _state_from_api_fixture(
    home_resolved: str,
    away_resolved: str,
    raw: dict[str, Any],
) -> FixtureState:
    fix = raw.get("fixture") or {}
    status_short = (fix.get("status") or {}).get("short", "")
    goals = raw.get("goals") or {}
    teams = raw.get("teams") or {}
    venue = fix.get("venue") or {}
    api_home = (teams.get("home") or {}).get("name", "")
    api_away = (teams.get("away") or {}).get("name", "")

    home_en = _normalize_en(home_resolved)
    away_en = _normalize_en(away_resolved)
    api_home_n = _normalize_en(api_home)
    swap = api_home_n != home_en and _normalize_en(api_away) == home_en

    ah = goals.get("home")
    aa = goals.get("away")
    if ah is not None and aa is not None:
        ah, aa = int(ah), int(aa)
        if swap:
            ah, aa = aa, ah
    else:
        ah, aa = None, None

    fixture_status = _api_status_to_fixture_status(status_short)
    kickoff = fix.get("date")

    return FixtureState(
        home_team=home_resolved,
        away_team=away_resolved,
        fixture_status=fixture_status,  # type: ignore[arg-type]
        kickoff_time_utc=kickoff,
        actual_home_goals=ah,
        actual_away_goals=aa,
        actual_score_available=ah is not None and aa is not None,
        source="api_football",
        source_available=True,
        venue_name=venue.get("name"),
        venue_city=venue.get("city"),
        venue_country=venue.get("country"),
    )


class FixtureStateResolver:
    """Resolve fixture state without blocking prediction on failure."""

    def __init__(
        self,
        api: ApiFootballClient | None = None,
        *,
        overrides_path: Path | None = None,
    ) -> None:
        self._api = api or ApiFootballClient()
        self._overrides_path = overrides_path
        self._last_api_error: str | None = None

    @property
    def last_api_error(self) -> str | None:
        return self._last_api_error

    def resolve(
        self,
        home_resolved: str,
        away_resolved: str,
        *,
        match_date: str | None = None,
        reference_date: date | None = None,
    ) -> FixtureState:
        home_en = english_name(home_resolved) or _normalize_en(home_resolved)
        away_en = english_name(away_resolved) or _normalize_en(away_resolved)

        manual_rows = _load_manual_overrides(self._overrides_path)
        manual = _match_manual_override(home_resolved, away_resolved, manual_rows)
        if manual:
            return apply_fixture_state_rules(
                _state_from_manual_row(home_resolved, away_resolved, manual)
            )

        curated = _lookup_curated_metadata(home_en, away_en)
        if curated:
            historical = _lookup_historical_result(home_en, away_en)
            return apply_fixture_state_rules(
                _state_from_curated(
                    home_resolved,
                    away_resolved,
                    curated,
                    historical,
                    reference_date=reference_date,
                )
            )

        api_state, api_warnings = self._resolve_from_api(home_resolved, away_resolved, home_en, away_en)
        if api_state is not None:
            api_state.warnings.extend(api_warnings)
            return apply_fixture_state_rules(api_state)

        warnings = list(api_warnings)
        return apply_fixture_state_rules(
            FixtureState(
                home_team=home_resolved,
                away_team=away_resolved,
                fixture_status="unknown",
                prediction_valid=True,
                prediction_mode="unknown",
                source="unavailable",
                source_available=False,
                source_error=self._last_api_error,
                warnings=warnings,
            )
        )

    def _resolve_from_api(
        self,
        home_resolved: str,
        away_resolved: str,
        home_en: str,
        away_en: str,
    ) -> tuple[FixtureState | None, list[str]]:
        warnings: list[str] = []
        if not self._api.is_available:
            self._last_api_error = API_FOOTBALL_UNAVAILABLE
            warnings.append(EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE)
            warnings.append(API_FOOTBALL_UNAVAILABLE)
            return None, warnings

        try:
            home_team = self._api.search_national_team(home_en)
            away_team = self._api.search_national_team(away_en)
            if not home_team or not away_team:
                return None, warnings

            items = self._api.find_h2h_fixtures(int(home_team["id"]), int(away_team["id"]))
            best = _pick_best_api_fixture(items)
            if not best:
                return None, warnings
            return _state_from_api_fixture(home_resolved, away_resolved, best), warnings
        except Exception as exc:
            code = classify_api_football_error(exc)
            self._last_api_error = code
            warnings.append(EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE)
            warnings.append(code)
            logger.warning(
                "Fixture state API lookup failed for %s vs %s: %s",
                home_en,
                away_en,
                code,
            )
            return None, warnings


def resolve_fixture_state(
    home_resolved: str,
    away_resolved: str,
    *,
    api: ApiFootballClient | None = None,
    overrides_path: Path | None = None,
    match_date: str | None = None,
) -> FixtureState:
    """Functional entry point used by predict()."""
    resolver = FixtureStateResolver(api=api, overrides_path=overrides_path)
    return resolver.resolve(home_resolved, away_resolved, match_date=match_date)
