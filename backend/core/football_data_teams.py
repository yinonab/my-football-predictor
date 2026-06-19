"""Team name normalization for football-data.org fixture matching."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Extra aliases: normalized key -> canonical comparison key (space-separated, no accents)
FOOTBALL_DATA_TEAM_ALIASES: dict[str, str] = {
    "usa": "united states",
    "united states": "united states",
    "south korea": "korea republic",
    "korea republic": "korea republic",
    "bosnia and herzegovina": "bosnia herzegovina",
    "bosnia herzegovina": "bosnia herzegovina",
    "dr congo": "congo dr",
    "democratic republic of congo": "congo dr",
    "congo dr": "congo dr",
    "ivory coast": "cote divoire",
    "cote divoire": "cote divoire",
    "côte d'ivoire": "cote divoire",
    "curacao": "curacao",
    "curaçao": "curacao",
    "republic of ireland": "ireland",
    "ireland": "ireland",
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_team_key(name: str) -> str:
    """Lowercase, accent-stripped key for alias lookup and comparison."""
    base = name.split(" (")[0].strip()
    base = _strip_accents(base).lower()
    base = base.replace("'", "").replace(".", "")
    base = re.sub(r"[^a-z0-9]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return FOOTBALL_DATA_TEAM_ALIASES.get(base, base)


def football_data_team_keys(team: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("name", "shortName", "tla"):
        raw = team.get(field)
        if raw:
            keys.add(normalize_team_key(str(raw)))
    return {k for k in keys if k}


def teams_match(request_name: str, football_data_team: dict[str, Any]) -> bool:
    req = normalize_team_key(request_name)
    if not req:
        return False
    fd_keys = football_data_team_keys(football_data_team)
    if req in fd_keys:
        return True
    # TLA exact match (e.g. USA)
    tla = (football_data_team.get("tla") or "").lower()
    if tla and req == tla:
        return True
    return False
