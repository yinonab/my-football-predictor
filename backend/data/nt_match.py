"""National-team match record — tournaments, qualifiers, friendlies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# English API / dataset name → registry key in database.FIFA_ELO_2026
NT_REGISTRY_ALIASES: dict[str, str] = {
    "United States": "USA (ארצות הברית)",
    "USA": "USA (ארצות הברית)",
    "Korea Republic": "South Korea (דרום קוריאה)",
    "South Korea": "South Korea (דרום קוריאה)",
    "Cote d'Ivoire": "Ivory Coast (חוף השנהב)",
    "Ivory Coast": "Ivory Coast (חוף השנהב)",
    "Cote d'Ivoire": "Ivory Coast (חוף השנהב)",
    "Congo DR": "DR Congo (קונגו)",
    "DR Congo": "DR Congo (קונגו)",
    "Cabo Verde": "Cape Verde (כף ורד)",
    "Cape Verde": "Cape Verde (כף ורד)",
    "Czech Republic": "Czechia (צ'כיה)",
    "Czechia": "Czechia (צ'כיה)",
    "Bosnia and Herzegovina": "Bosnia (בוסניה)",
    "Bosnia": "Bosnia (בוסניה)",
    "Türkiye": "Turkey (טורקיה)",
    "Turkey": "Turkey (טורקיה)",
    "Curacao": "Curacao (קוראסאו)",
    "Curaçao": "Curacao (קוראסאו)",
    "Iran": "Iran (איראן)",
    "Iraq": "Iraq (עיראק)",
    "Jordan": "Jordan (יורדן)",
    "Uzbekistan": "Uzbekistan (אוזבקיסטן)",
    "Saudi Arabia": "Saudi Arabia (ערב הסעודית)",
    "New Zealand": "New Zealand (ניו זילנד)",
    "Qatar": "Qatar (קטר)",
    "Mexico": "Mexico (מקסיקו)",
    "Canada": "Canada (קנדה)",
    "Brazil": "Brazil (ברזיל)",
    "Argentina": "Argentina (ארגנטינה)",
    "France": "France (צרפת)",
    "Germany": "Germany (גרמניה)",
    "Spain": "Spain (ספרד)",
    "England": "England (אנגליה)",
    "Portugal": "Portugal (פורטוגל)",
    "Netherlands": "Netherlands (הולנד)",
    "Belgium": "Belgium (בלגיה)",
    "Croatia": "Croatia (קרואטיה)",
    "Morocco": "Morocco (מרוקו)",
    "Japan": "Japan (יפן)",
    "Senegal": "Senegal (סנגל)",
    "Switzerland": "Switzerland (שוויץ)",
    "Uruguay": "Uruguay (אורוגוואי)",
    "Colombia": "Colombia (קולומביה)",
    "Ecuador": "Ecuador (אקוודור)",
    "Australia": "Australia (אוסטרליה)",
    "Tunisia": "Tunisia (תוניסיה)",
    "Ghana": "Ghana (גאנה)",
    "Egypt": "Egypt (מצרים)",
    "Algeria": "Algeria (אלג׳יריה)",
    "Austria": "Austria (אוסטריה)",
    "Norway": "Norway (נורווג)",
    "Sweden": "Sweden (שבדיה)",
    "Scotland": "Scotland (סקוטלנד)",
    "Paraguay": "Paraguay (פרגוואי)",
    "Panama": "Panama (פנמה)",
    "Haiti": "Haiti (האיטי)",
    "South Africa": "South Africa (דרום אפריקה)",
}

COMPETITION_WEIGHTS: dict[str, float] = {
    "world cup": 1.0,
    "european championship": 0.95,
    "copa america": 0.95,
    "africa cup": 0.9,
    "asian cup": 0.9,
    "concacaf": 0.85,
    "nations league": 0.8,
    "qualification": 0.75,
    "friendly": 0.5,
}


@dataclass(frozen=True)
class NationalTeamMatch:
    date: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    neutral: bool = True
    competition: str = "unknown"
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NationalTeamMatch:
        return cls(
            date=str(data["date"]),
            home=str(data["home"]),
            away=str(data["away"]),
            home_goals=int(data["home_goals"]),
            away_goals=int(data["away_goals"]),
            neutral=bool(data.get("neutral", True)),
            competition=str(data.get("competition", "unknown")),
            weight=float(data.get("weight", 1.0)),
        )


def registry_key_for_nt(name: str, registry_keys: set[str]) -> str | None:
    """Map a match team label to a WC 2026 registry key, if known."""
    cleaned = name.strip()
    if cleaned in registry_keys:
        return cleaned
    if cleaned in NT_REGISTRY_ALIASES:
        alias = NT_REGISTRY_ALIASES[cleaned]
        if alias in registry_keys:
            return alias
    for key in registry_keys:
        english = key.split(" (")[0]
        if cleaned.lower() == english.lower():
            return key
    return None


def competition_weight(league_name: str) -> float:
    lower = league_name.lower()
    if "qualif" in lower:
        return COMPETITION_WEIGHTS["qualification"]
    if "friendly" in lower or "friendlies" in lower:
        return COMPETITION_WEIGHTS["friendly"]
    for token, weight in COMPETITION_WEIGHTS.items():
        if token in lower:
            return weight
    return 0.7
