"""Centralized national-team name aliases → WC 2026 registry keys."""

from __future__ import annotations

import re
import unicodedata

# English / API / provider variants → canonical English name used in registry_key lookup.
# Registry keys are "English (Hebrew)" in FIFA_ELO_2026; resolution continues in nt_match.
NT_TEAM_ALIASES: dict[str, str] = {
    # USA
    "USA": "United States",
    "United States": "United States",
    # Czechia
    "Czechia": "Czechia",
    "Czech Republic": "Czechia",
    # DR Congo
    "DR Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    # Ivory Coast
    "Ivory Coast": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    # Bosnia
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    # Curacao
    "Curacao": "Curacao",
    "Curaçao": "Curacao",
    # Korea
    "South Korea": "South Korea",
    "Korea Republic": "South Korea",
    # Iran
    "Iran": "Iran",
    "IR Iran": "Iran",
    # Cape Verde
    "Cape Verde": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    # Common extras
    "Türkiye": "Turkey",
    "Turkey": "Turkey",
    "New Zealand": "New Zealand",
    "Haiti": "Haiti",
    "Saudi Arabia": "Saudi Arabia",
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_nt_team_label(name: str) -> str:
    """Normalize raw label to canonical English for alias lookup."""
    cleaned = name.strip()
    if not cleaned:
        return cleaned
    # Already a registry key
    if " (" in cleaned:
        cleaned = cleaned.split(" (")[0].strip()
    base = _strip_accents(cleaned)
    base = base.replace("'", "'").strip()
    if base in NT_TEAM_ALIASES:
        return NT_TEAM_ALIASES[base]
    # Case-insensitive alias lookup
    lower_map = {k.lower(): v for k, v in NT_TEAM_ALIASES.items()}
    if base.lower() in lower_map:
        return lower_map[base.lower()]
    return cleaned


def registry_english_for_alias(name: str) -> str:
    """Return canonical English team name after alias normalization."""
    return normalize_nt_team_label(name)
