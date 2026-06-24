"""Sofascore RapidAPI client (Phase A/B — read-only adapter; fusion refresh when enabled)."""

from __future__ import annotations

import logging
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import config
from data.nt_match import registry_key_for_nt

logger = logging.getLogger(__name__)

PROVIDER_ID = "sofascore"
PROVIDER_NAMESPACE = "sofascore"
SOFASCORE_FUSION_PROVIDER = "sofascore_recent_form"
SOFASCORE_FUSION_PRIORITY = 98

FINISHED_STATUS_TYPES = frozenset(
    {
        "finished",
        "ended",
        "afterpenalties",
        "afterextratime",
        "ap",
        "aet",
    }
)

KEY_MISSING = "KEY_MISSING"
DISABLED = "DISABLED"
HTTP_ERROR = "HTTP_ERROR"
NETWORK_ERROR = "NETWORK_ERROR"
JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
OK = "OK"

# Verified senior men's national-team IDs (Sofascore-specific; never mix with other providers).
KNOWN_SOFASCORE_NT_TEAM_IDS: dict[str, int] = {
    "brazil": 4748,
}

VALIDATED_TEAM_IDS_PATH = Path(__file__).resolve().parent / "sofascore_validated_team_ids.json"


def _load_validated_sofascore_team_ids() -> dict[str, int]:
    if not VALIDATED_TEAM_IDS_PATH.exists():
        return {}
    try:
        payload = json.loads(VALIDATED_TEAM_IDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    by_name = payload.get("by_english_name") if isinstance(payload, dict) else {}
    if not isinstance(by_name, dict):
        return {}
    out: dict[str, int] = {}
    for key, val in by_name.items():
        try:
            out[normalize_search_name(str(key))] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def merged_sofascore_nt_team_ids() -> dict[str, int]:
    merged = dict(KNOWN_SOFASCORE_NT_TEAM_IDS)
    merged.update(_load_validated_sofascore_team_ids())
    return merged


def known_sofascore_nt_team_id(name: str) -> int | None:
    return merged_sofascore_nt_team_ids().get(normalize_search_name(name))


def known_sofascore_registry_team_id(registry_key: str) -> int | None:
    english = registry_key.split(" (")[0]
    hit = known_sofascore_nt_team_id(english)
    if hit is not None:
        return hit
    if not VALIDATED_TEAM_IDS_PATH.exists():
        return None
    try:
        payload = json.loads(VALIDATED_TEAM_IDS_PATH.read_text(encoding="utf-8"))
        by_registry = payload.get("by_registry_key") or {}
        val = by_registry.get(registry_key)
        return int(val) if val is not None else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def load_sofascore_registry_id_map() -> dict[str, int]:
    """Registry key -> Sofascore team id from validated discovery file."""
    if not VALIDATED_TEAM_IDS_PATH.exists():
        return {}
    try:
        payload = json.loads(VALIDATED_TEAM_IDS_PATH.read_text(encoding="utf-8"))
        raw = payload.get("by_registry_key") or {}
        return {str(k): int(v) for k, v in raw.items() if v is not None}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}

YOUTH_WOMEN_TEAM_RE = re.compile(
    r"(^|\s|-)(u\s?\d{1,2}|under\s?\d{1,2}|youth|women|woman|femenin|féminin|female|girls)(\s|$|-)",
    re.IGNORECASE,
)

NON_FOOTBALL_SPORT_RE = re.compile(
    r"(basketball|handball|volleyball|hockey|futsal|beach)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SofascoreRequestError:
    category: str
    message: str
    http_status: int | None = None


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_search_name(name: str) -> str:
    base = name.split(" (")[0].strip()
    return _strip_accents(base).lower()


def sofascore_provider_ids(team_id: int) -> dict[str, int]:
    """Namespaced provider_ids fragment for future fusion cache entries."""
    return {PROVIDER_NAMESPACE: int(team_id)}


def _is_football_sport(entity: dict[str, Any]) -> bool:
    sport = entity.get("sport")
    if isinstance(sport, dict):
        slug = str(sport.get("slug") or sport.get("name") or "").lower()
        if slug and "football" in slug:
            return True
        if slug and NON_FOOTBALL_SPORT_RE.search(slug):
            return False
    sport_name = str(entity.get("sportName") or "").lower()
    if sport_name:
        return "football" in sport_name and not NON_FOOTBALL_SPORT_RE.search(sport_name)
    return True


def _is_mens_team(entity: dict[str, Any]) -> bool:
    gender = str(entity.get("gender") or "").upper()
    if gender in ("F", "FEMALE"):
        return False
    name = str(entity.get("name") or "")
    if YOUTH_WOMEN_TEAM_RE.search(name):
        return False
    return True


def is_senior_mens_football_team(entity: dict[str, Any]) -> bool:
    if not isinstance(entity, dict):
        return False
    if not _is_football_sport(entity):
        return False
    if not _is_mens_team(entity):
        return False
    if entity.get("national") is False:
        return False
    return True


def _team_entities_from_search_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    for key in ("entities", "teams", "results"):
        block = payload.get(key)
        if not isinstance(block, list):
            continue
        for item in block:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "team" and isinstance(item.get("entity"), dict):
                out.append(item["entity"])
            elif "id" in item and "name" in item:
                out.append(item)
    return out


def parse_team_search_results(payload: Any) -> list[dict[str, Any]]:
    """Normalize team search payload to a list of team entity dicts."""
    return _team_entities_from_search_payload(payload)


def select_national_mens_football_team(
    results: list[dict[str, Any]],
    *,
    expected_name: str | None = None,
    expected_code: str | None = None,
) -> dict[str, Any] | None:
    """Pick senior men's national football team from search results."""
    candidates = [t for t in results if is_senior_mens_football_team(t)]
    if not candidates:
        return None

    expected_norm = normalize_search_name(expected_name) if expected_name else None
    code_norm = (expected_code or "").strip().upper() or None

    if expected_norm:
        exact = [
            t
            for t in candidates
            if normalize_search_name(str(t.get("name") or "")) == expected_norm
        ]
        if exact:
            candidates = exact

    if code_norm:
        code_matches = [
            t
            for t in candidates
            if str(t.get("nameCode") or t.get("shortName") or "").upper() == code_norm
        ]
        if code_matches:
            candidates = code_matches

    if expected_norm:
        known_id = merged_sofascore_nt_team_ids().get(expected_norm)
        if known_id is not None:
            for t in candidates:
                if int(t.get("id") or 0) == known_id:
                    return t

    return candidates[0]


def _nested_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_team_side(team: Any) -> dict[str, Any]:
    data = _nested_dict(team)
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "nameCode": data.get("nameCode") or data.get("shortName"),
        "ranking": data.get("ranking"),
    }


def _parse_status(status: Any) -> dict[str, Any]:
    data = _nested_dict(status)
    return {
        "code": data.get("code"),
        "type": data.get("type"),
        "description": data.get("description"),
    }


def _parse_tournament_block(value: Any) -> dict[str, Any]:
    data = _nested_dict(value)
    return {
        "name": data.get("name"),
        "id": data.get("id"),
    }


def _score_current(score: Any) -> int | None:
    data = _nested_dict(score)
    for key in ("current", "display", "normaltime"):
        val = data.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return None


def parse_match_event(event: dict[str, Any]) -> dict[str, Any]:
    """Parse one Sofascore event into a schema-tolerant normalized dict."""
    return {
        "provider": PROVIDER_ID,
        "provider_match_id": event.get("id"),
        "startTimestamp": event.get("startTimestamp"),
        "status": _parse_status(event.get("status")),
        "tournament": _parse_tournament_block(event.get("tournament")),
        "uniqueTournament": _parse_tournament_block(event.get("uniqueTournament")),
        "season": _parse_tournament_block(event.get("season")),
        "roundInfo": _nested_dict(event.get("roundInfo")) or None,
        "homeTeam": _parse_team_side(event.get("homeTeam")),
        "awayTeam": _parse_team_side(event.get("awayTeam")),
        "homeScore": _nested_dict(event.get("homeScore")),
        "awayScore": _nested_dict(event.get("awayScore")),
        "winnerCode": event.get("winnerCode"),
        "hasXg": bool(event.get("hasXg")),
        "hasEventPlayerStatistics": bool(event.get("hasEventPlayerStatistics")),
        "hasEventPlayerHeatMap": bool(event.get("hasEventPlayerHeatMap")),
    }


def _events_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "lastMatches", "nextMatches", "data"):
        block = payload.get(key)
        if isinstance(block, list):
            return [e for e in block if isinstance(e, dict)]
    return []


def _add_team_perspective(parsed: dict[str, Any], team_id: int) -> dict[str, Any]:
    home = parsed.get("homeTeam") or {}
    away = parsed.get("awayTeam") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    home_goals = _score_current(parsed.get("homeScore"))
    away_goals = _score_current(parsed.get("awayScore"))

    row = dict(parsed)
    if home_id == team_id:
        row["team"] = home.get("name")
        row["opponent"] = away.get("name")
        row["goals_for"] = home_goals
        row["goals_against"] = away_goals
        row["is_home"] = True
    elif away_id == team_id:
        row["team"] = away.get("name")
        row["opponent"] = home.get("name")
        row["goals_for"] = away_goals
        row["goals_against"] = home_goals
        row["is_home"] = False
    return row


def parse_last_matches(
    payload: Any,
    *,
    team_id: int | None = None,
) -> list[dict[str, Any]]:
    """Parse last-matches response; optional team_id adds team/opponent/score perspective."""
    rows = [parse_match_event(e) for e in _events_from_payload(payload)]
    if team_id is not None:
        return [_add_team_perspective(r, team_id) for r in rows]
    return rows


def parse_next_matches(
    payload: Any,
    *,
    team_id: int | None = None,
) -> list[dict[str, Any]]:
    """Parse next-matches response (same shape as last matches)."""
    return parse_last_matches(payload, team_id=team_id)


def is_finished_sofascore_event(event: dict[str, Any]) -> bool:
    status = event.get("status") or {}
    if not isinstance(status, dict):
        return False
    stype = str(status.get("type") or "").lower()
    if stype in FINISHED_STATUS_TYPES:
        return True
    code = status.get("code")
    if code in (100, 110, 120):
        return True
    desc = str(status.get("description") or "").lower()
    return desc in ("ended", "finished")


def _timestamp_to_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _penalty_score(score: dict[str, Any]) -> int | None:
    for key in ("penalty", "penalties"):
        val = score.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return None


def sofascore_event_to_fusion_match(
    event: dict[str, Any],
    *,
    team_registry_key: str,
    sofascore_team_id: int,
    registry: set[str] | None = None,
) -> dict[str, Any] | None:
    """Parse one Sofascore last-match event into fusion candidate dict."""
    if not is_finished_sofascore_event(event):
        return None

    parsed = parse_match_event(event)
    home = parsed.get("homeTeam") or {}
    away = parsed.get("awayTeam") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    home_goals = _score_current(parsed.get("homeScore"))
    away_goals = _score_current(parsed.get("awayScore"))
    if home_goals is None or away_goals is None:
        return None

    english = team_registry_key.split(" (")[0]
    is_home: bool | None = None
    opponent_name = "unknown"
    opponent_ranking: int | None = None
    score_for = 0
    score_against = 0

    if home_id == sofascore_team_id:
        score_for, score_against = home_goals, away_goals
        opponent_name = str(away.get("name") or "unknown")
        opponent_ranking = away.get("ranking")
        is_home = True
    elif away_id == sofascore_team_id:
        score_for, score_against = away_goals, home_goals
        opponent_name = str(home.get("name") or "unknown")
        opponent_ranking = home.get("ranking")
        is_home = False
    else:
        return None

    if score_for > score_against:
        result = "W"
    elif score_for < score_against:
        result = "L"
    else:
        result = "D"

    date_str = _timestamp_to_date(parsed.get("startTimestamp"))
    if not date_str:
        return None

    reg = registry if registry is not None else set()
    opponent_registry_key = registry_key_for_nt(opponent_name, reg) if reg else None

    tournament = parsed.get("tournament") or {}
    unique_tournament = parsed.get("uniqueTournament") or {}
    season = parsed.get("season") or {}
    competition_name = (
        str(unique_tournament.get("name") or tournament.get("name") or "unknown")
    )

    home_score_block = parsed.get("homeScore") or {}
    away_score_block = parsed.get("awayScore") or {}
    season_year = None
    season_name = season.get("name")
    if season_name:
        m = re.match(r"(\d{4})", str(season_name))
        if m:
            season_year = int(m.group(1))
    if season_year is None:
        season_year = season.get("id") if isinstance(season.get("id"), int) else None

    status = parsed.get("status") or {}

    return {
        "provider": SOFASCORE_FUSION_PROVIDER,
        "source_priority": SOFASCORE_FUSION_PRIORITY,
        "provider_fixture_id": str(parsed.get("provider_match_id")),
        "team": english,
        "opponent": opponent_name,
        "date": date_str,
        "startTimestamp": parsed.get("startTimestamp"),
        "status": str(status.get("type") or status.get("description") or "finished"),
        "status_code": status.get("code"),
        "status_type": status.get("type"),
        "status_description": status.get("description"),
        "home_team": str(home.get("name") or ""),
        "away_team": str(away.get("name") or ""),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name_code": home.get("nameCode"),
        "away_team_name_code": away.get("nameCode"),
        "home_team_ranking": home.get("ranking"),
        "away_team_ranking": away.get("ranking"),
        "home_score": home_goals,
        "away_score": away_goals,
        "home_penalty_score": _penalty_score(home_score_block),
        "away_penalty_score": _penalty_score(away_score_block),
        "score_for": score_for,
        "score_against": score_against,
        "result_for_team": result,
        "competition_name": competition_name,
        "competition_id": tournament.get("id"),
        "unique_tournament_name": unique_tournament.get("name"),
        "unique_tournament_id": unique_tournament.get("id"),
        "season_name": season.get("name"),
        "season_id": season.get("id"),
        "season": season_year,
        "round_info": parsed.get("roundInfo"),
        "winner_code": parsed.get("winnerCode"),
        "has_xg": parsed.get("hasXg"),
        "has_event_player_statistics": parsed.get("hasEventPlayerStatistics"),
        "has_event_player_heat_map": parsed.get("hasEventPlayerHeatMap"),
        "opponent_ranking": opponent_ranking,
        "is_home": is_home,
        "is_neutral": None,
        "confidence_level": "high",
        "quality_flags": [],
        "raw_source_ref": {
            "provider": PROVIDER_NAMESPACE,
            "match_id": parsed.get("provider_match_id"),
        },
        "team_registry_key": team_registry_key,
        "opponent_registry_key": opponent_registry_key,
    }


def extract_expected_goals_from_statistics(payload: Any) -> dict[str, float | None]:
    """Extract aggregate expectedGoals from /matches/get-statistics."""
    home_xg: float | None = None
    away_xg: float | None = None

    statistics = []
    if isinstance(payload, dict):
        statistics = payload.get("statistics") or []
    elif isinstance(payload, list):
        statistics = payload

    for period_block in statistics:
        if not isinstance(period_block, dict):
            continue
        groups = period_block.get("groups") or []
        for group in groups:
            if not isinstance(group, dict):
                continue
            for item in group.get("statisticsItems") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("key") or "").lower() != "expectedgoals":
                    continue
                home_xg = _parse_float(item.get("home"))
                away_xg = _parse_float(item.get("away"))
                return {
                    "home_expected_goals": home_xg,
                    "away_expected_goals": away_xg,
                }

    return {"home_expected_goals": home_xg, "away_expected_goals": away_xg}


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_shot_xg_from_shotmap(payload: Any) -> list[dict[str, Any]]:
    """Extract shot-level xG fields from /matches/get-shotmap."""
    shots_raw: list[Any] = []
    if isinstance(payload, dict):
        block = payload.get("shotmap")
        if isinstance(block, list):
            shots_raw = block
    elif isinstance(payload, list):
        shots_raw = payload

    out: list[dict[str, Any]] = []
    for shot in shots_raw:
        if not isinstance(shot, dict):
            continue
        player = _nested_dict(shot.get("player"))
        coords = _nested_dict(shot.get("playerCoordinates"))
        row: dict[str, Any] = {
            "player_id": player.get("id"),
            "player_name": player.get("name"),
            "isHome": shot.get("isHome"),
            "shotType": shot.get("shotType"),
            "situation": shot.get("situation"),
            "bodyPart": shot.get("bodyPart"),
            "xg": _parse_float(shot.get("xg")),
            "time": shot.get("time"),
            "timeSeconds": shot.get("timeSeconds"),
            "playerCoordinates": coords or None,
            "incidentType": shot.get("incidentType"),
        }
        if "xgot" in shot:
            row["xgot"] = _parse_float(shot.get("xgot"))
        out.append(row)
    return out


def parse_incidents_summary(payload: Any) -> dict[str, Any]:
    """Summarize match incidents (goals, cards) without full raw payload."""
    incidents: list[Any] = []
    if isinstance(payload, dict):
        incidents = payload.get("incidents") or payload.get("data") or []
    elif isinstance(payload, list):
        incidents = payload

    goals = 0
    cards = 0
    for inc in incidents:
        if not isinstance(inc, dict):
            continue
        inc_type = str(inc.get("incidentType") or inc.get("type") or "").lower()
        if inc_type in ("goal", "penalty", "owngoal", "own-goal"):
            goals += 1
        if "card" in inc_type:
            cards += 1

    return {
        "incident_count": len([i for i in incidents if isinstance(i, dict)]),
        "goal_incidents": goals,
        "card_incidents": cards,
    }


def parse_lineups_summary(payload: Any) -> dict[str, Any]:
    """Summarize lineups (counts and formation) from get-lineups response."""
    home_players = 0
    away_players = 0
    home_formation: str | None = None
    away_formation: str | None = None

    if isinstance(payload, dict):
        home = _nested_dict(payload.get("home"))
        away = _nested_dict(payload.get("away"))
        home_players = len(home.get("players") or [])
        away_players = len(away.get("players") or [])
        home_formation = home.get("formation")
        away_formation = away.get("formation")

    return {
        "home_player_count": home_players,
        "away_player_count": away_players,
        "home_formation": home_formation,
        "away_formation": away_formation,
    }


class SofascoreClient:
    """Read-only Sofascore RapidAPI client."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        rapidapi_host: str | None = None,
        enabled: bool | None = None,
        timeout: int | None = None,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = config.sofascore_rapidapi_key()
        self.base_url = (base_url or config.SOFASCORE_RAPIDAPI_BASE).rstrip("/")
        self.rapidapi_host = rapidapi_host or config.SOFASCORE_RAPIDAPI_HOST
        self.enabled = config.SOFASCORE_ENABLED if enabled is None else enabled
        self.timeout = timeout or config.SOFASCORE_TIMEOUT_SECONDS
        self.last_error_code: str | None = None
        self.last_error: SofascoreRequestError | None = None
        self.request_count = 0

    @property
    def key_present(self) -> bool:
        return bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self.enabled and self.key_present

    def _headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.rapidapi_host,
            "Accept": "application/json",
        }

    def _set_error(self, error: SofascoreRequestError) -> None:
        self.last_error = error
        self.last_error_code = error.category

    def _clear_error(self) -> None:
        self.last_error = None
        self.last_error_code = OK

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            self._set_error(SofascoreRequestError(DISABLED, "Sofascore provider disabled"))
            return None
        if not self.key_present:
            self._set_error(SofascoreRequestError(KEY_MISSING, "SOFASCORE_RAPIDAPI_KEY is not set"))
            return None

        self.request_count += 1
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            self._set_error(SofascoreRequestError(NETWORK_ERROR, "request timeout"))
            logger.warning("Sofascore timeout %s: %s", path, exc.__class__.__name__)
            return None
        except requests.RequestException as exc:
            self._set_error(SofascoreRequestError(NETWORK_ERROR, "network error"))
            logger.warning("Sofascore network error %s: %s", path, exc.__class__.__name__)
            return None

        if response.status_code == 204:
            self._clear_error()
            return None

        if response.status_code != 200:
            self._set_error(
                SofascoreRequestError(
                    HTTP_ERROR,
                    f"HTTP {response.status_code}",
                    http_status=response.status_code,
                )
            )
            logger.warning("Sofascore HTTP %s for %s", response.status_code, path)
            return None

        try:
            payload = response.json()
        except ValueError:
            self._set_error(SofascoreRequestError(JSON_PARSE_ERROR, "invalid JSON"))
            return None

        self._clear_error()
        return payload if isinstance(payload, dict) else {"data": payload}

    def search_teams(self, name: str) -> list[dict[str, Any]]:
        payload = self._request("/teams/search", params={"name": name})
        if payload is None:
            return []
        return parse_team_search_results(payload)

    def fetch_last_match_events(self, team_id: int) -> list[dict[str, Any]]:
        """Raw finished-event payloads from get-last-matches (empty on 204/error)."""
        payload = self._request(
            "/teams/get-last-matches",
            params={"teamId": team_id},
        )
        if payload is None:
            return []
        return _events_from_payload(payload)

    def get_last_matches(self, team_id: int) -> list[dict[str, Any]]:
        payload = self._request(
            "/teams/get-last-matches",
            params={"teamId": team_id},
        )
        if payload is None:
            return []
        return parse_last_matches(payload, team_id=team_id)

    def get_next_matches(self, team_id: int) -> list[dict[str, Any]]:
        payload = self._request(
            "/teams/get-next-matches",
            params={"teamId": team_id},
        )
        if payload is None:
            return []
        return parse_next_matches(payload, team_id=team_id)

    def get_match_detail(self, match_id: int) -> dict[str, Any] | None:
        payload = self._request("/matches/detail", params={"matchId": match_id})
        if payload is None:
            return None
        event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
        if isinstance(event, dict) and event.get("id") is not None:
            return parse_match_event(event)
        return payload if isinstance(payload, dict) else None

    def get_match_statistics(self, match_id: int) -> dict[str, Any] | None:
        return self._request("/matches/get-statistics", params={"matchId": match_id})

    def get_match_shotmap(self, match_id: int) -> dict[str, Any] | None:
        return self._request("/matches/get-shotmap", params={"matchId": match_id})

    def get_match_incidents(self, match_id: int) -> dict[str, Any] | None:
        return self._request("/matches/get-incidents", params={"matchId": match_id})

    def get_match_lineups(self, match_id: int) -> dict[str, Any] | None:
        return self._request("/matches/get-lineups", params={"matchId": match_id})

    def get_match_h2h(self, match_id: int) -> dict[str, Any] | None:
        return self._request("/matches/get-h2h", params={"matchId": match_id})
