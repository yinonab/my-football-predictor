"""Official World Cup 2026 registry — FIFA Elo + derived metrics."""

from __future__ import annotations

import re
from typing import Any

from data.api_football import ApiFootballClient

DEFAULT_TEAM: dict[str, float] = {
    "elo": 1500.0,
    "form": 0.5,
    "attack": 0.5,
    "defense": 0.5,
}

# FIFA ranking points — June 2026 (sources: FIFA/ESPN/BBC, June 11–14 2026)
# Teams not in top-50 use rank-based estimates aligned with FIFA scale.
FIFA_ELO_2026: dict[str, int] = {
    # Group A
    "Mexico (מקסיקו)": 1695,
    "South Africa (דרום אפריקה)": 1375,
    "South Korea (דרום קוריאה)": 1612,
    "Czechia (צ'כיה)": 1495,
    # Group B
    "Canada (קנדה)": 1572,
    "Bosnia (בוסניה)": 1350,
    "Qatar (קטר)": 1400,
    "Switzerland (שוויץ)": 1658,
    # Group C
    "Brazil (ברזיל)": 1765,
    "Morocco (מרוקו)": 1755,
    "Haiti (האיטי)": 1265,
    "Scotland (סקוטלנד)": 1480,
    # Group D
    "USA (ארצות הברית)": 1673,
    "Paraguay (פרגוואי)": 1500,
    "Australia (אוסטרליה)": 1595,
    "Turkey (טורקיה)": 1635,
    # Group E
    "Germany (גרמניה)": 1735,
    "Curacao (קוראסאו)": 1270,
    "Ivory Coast (חוף השנהב)": 1543,
    "Ecuador (אקוודור)": 1628,
    # Group F
    "Netherlands (הולנד)": 1753,
    "Japan (יפן)": 1665,
    "Sweden (שבדיה)": 1515,
    "Tunisia (תוניסיה)": 1475,
    # Group G
    "Belgium (בלגיה)": 1742,
    "Egypt (מצרים)": 1580,
    "Iran (איראן)": 1650,
    "New Zealand (ניו זילנד)": 1255,
    # Group H
    "Spain (ספרד)": 1874,
    "Cape Verde (כף ורד)": 1330,
    "Saudi Arabia (ערב הסעודית)": 1370,
    "Uruguay (אורוגוואי)": 1680,
    # Group I
    "France (צרפת)": 1870,
    "Senegal (סנגל)": 1688,
    "Iraq (עיראק)": 1395,
    "Norway (נורווג)": 1565,
    # Group J
    "Argentina (ארגנטינה)": 1877,
    "Algeria (אלג׳יריה)": 1588,
    "Austria (אוסטריה)": 1620,
    "Jordan (יורדן)": 1360,
    # Group K
    "Portugal (פורטוגל)": 1767,
    "DR Congo (קונגו)": 1460,
    "Uzbekistan (אוזבקיסטן)": 1435,
    "Colombia (קולומביה)": 1705,
    # Group L
    "England (אנגליה)": 1828,
    "Croatia (קרואטיה)": 1720,
    "Ghana (גאנה)": 1305,
    "Panama (פנמה)": 1550,
}


def compute_derived_metrics(elo: float) -> dict[str, float]:
    """Derive form/attack/defense from FIFA-scale Elo (1350–1900 → 0–1)."""
    normalized = max(0.0, min(1.0, (elo - 1350) / 550))
    attack = round(min(0.95, 0.10 + normalized * 0.85), 2)
    defense = round(min(0.95, 0.12 + normalized * 0.80), 2)
    form = round(min(0.95, 0.08 + normalized * 0.87), 2)
    return {
        "elo": float(elo),
        "form": form,
        "attack": attack,
        "defense": defense,
    }


class LiveDataManager:
    """World Cup 2026 data — official 48 teams, FIFA Elo June 2026."""

    def __init__(self) -> None:
        from core.elo_store import load_elo_overrides
        from core.team_ratings import load_ratings

        self._api = ApiFootballClient()
        self._history_ratings = load_ratings()
        self._elo_overrides = load_elo_overrides()
        self.team_database: dict[str, dict[str, float]] = {}
        for name, elo in FIFA_ELO_2026.items():
            data = compute_derived_metrics(elo)
            if name in self._elo_overrides:
                data["elo"] = self._elo_overrides[name]
            self.team_database[name] = data

        self.aliases: dict[str, str] = {}
        for key in self.team_database:
            english = key.split(" (")[0].lower()
            self.aliases[english] = key
            self.aliases[english.replace("'", "")] = key
            hebrew_match = re.search(r"\(([^)]+)\)", key)
            if hebrew_match:
                self.aliases[hebrew_match.group(1).strip()] = key

        # Common alternate names
        extra_aliases = {
            "usa": "USA (ארצות הברית)",
            "united states": "USA (ארצות הברית)",
            "ארה\"ב": "USA (ארצות הברית)",
            "türkiye": "Turkey (טורקיה)",
            "turkiye": "Turkey (טורקיה)",
            "korea": "South Korea (דרום קוריאה)",
            "korea republic": "South Korea (דרום קוריאה)",
            "cote d'ivoire": "Ivory Coast (חוף השנהב)",
            "ivory coast": "Ivory Coast (חוף השנהב)",
            "cape verde": "Cape Verde (כף ורד)",
            "cab verde": "Cape Verde (כף ורד)",
            "congo dr": "DR Congo (קונגו)",
            "congo": "DR Congo (קונגו)",
            "curacao": "Curacao (קוראסאו)",
            "czech republic": "Czechia (צ'כיה)",
            "bosnia and herzegovina": "Bosnia (בוסניה)",
            "bosnia-herzegovina": "Bosnia (בוסניה)",
            "saudi": "Saudi Arabia (ערב הסעודית)",
            "nz": "New Zealand (ניו זילנד)",
        }
        self.aliases.update(extra_aliases)

    def list_teams(self) -> list[str]:
        return list(self.team_database.keys())

    def get_team_data(self, team_name: str, *, use_live: bool = False) -> dict[str, Any]:
        key, data = self.resolve_team(team_name)
        payload = dict(data)
        hist = self._history_ratings.get(key)
        if hist and int(hist.get("matches_used", 0)) > 0:
            payload["elo"] = float(hist["elo"])
            payload["attack"] = float(hist["attack"])
            payload["defense"] = float(hist["defense"])
            payload["form"] = float(hist["form"])
            payload["matches_used"] = int(hist["matches_used"])
            payload["rating_source"] = hist.get("rating_source", "history_blend")
        if use_live and self._api.is_available:
            payload = self._api.enrich_team_data(key, payload)
        return payload

    def get_group_info(self, team_name: str) -> dict[str, Any]:
        """Return group letter and sibling teams for a resolved team."""
        resolved, data = self.resolve_team(team_name)
        group = self.get_group(resolved)
        groups = _build_groups()
        siblings = groups.get(group, []) if group else []
        return {
            "team": resolved,
            "group": group,
            "elo": data["elo"],
            "group_teams": siblings,
        }

    def list_groups(self) -> dict[str, list[dict[str, Any]]]:
        groups = _build_groups()
        result: dict[str, list[dict[str, Any]]] = {}
        for letter, teams in groups.items():
            result[letter] = [
                {
                    "name": team,
                    "elo": self.team_database[team]["elo"],
                }
                for team in teams
            ]
        return result

    def resolve_team(self, team_name: str) -> tuple[str, dict[str, float]]:
        name = team_name.strip()
        if not name:
            return team_name, dict(DEFAULT_TEAM)

        if name in self.team_database:
            return name, dict(self.team_database[name])

        if name in self.aliases:
            key = self.aliases[name]
            return key, dict(self.team_database[key])

        lowered = name.lower()
        if lowered in self.aliases:
            key = self.aliases[lowered]
            return key, dict(self.team_database[key])

        for alias, key in self.aliases.items():
            if lowered in alias.lower() or alias.lower() in lowered:
                return key, dict(self.team_database[key])

        for key, data in self.team_database.items():
            if lowered in key.lower() or key.lower() in lowered:
                return key, dict(data)

        return name, compute_derived_metrics(1500)

    def is_known_team(self, team_name: str) -> bool:
        resolved, _ = self.resolve_team(team_name)
        return resolved in self.team_database

    def get_group(self, team_name: str) -> str | None:
        """Return group letter (A–L) for a known team."""
        resolved, _ = self.resolve_team(team_name)
        groups = _build_groups()
        for group, teams in groups.items():
            if resolved in teams:
                return group
        return None


def _build_groups() -> dict[str, list[str]]:
    """Official FIFA World Cup 2026 group assignments."""
    keys = list(FIFA_ELO_2026.keys())
    return {
        "A": keys[0:4],
        "B": keys[4:8],
        "C": keys[8:12],
        "D": keys[12:16],
        "E": keys[16:20],
        "F": keys[20:24],
        "G": keys[24:28],
        "H": keys[28:32],
        "I": keys[32:36],
        "J": keys[36:40],
        "K": keys[40:44],
        "L": keys[44:48],
    }
