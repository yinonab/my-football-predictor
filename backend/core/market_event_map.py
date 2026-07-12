"""Shared team-name normalization for provider event map and auto resolver."""

from __future__ import annotations

import re
import unicodedata

from data.nt_team_aliases import normalize_nt_team_label


def normalize_team_for_event_map(name: str) -> str:
    cleaned = re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip()
    return re.sub(r"\s+", " ", cleaned)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_team_for_resolver(name: str) -> str:
    """Event-map strip + NT aliases + accent fold for resolver comparisons."""
    base = normalize_team_for_event_map(name)
    base = normalize_nt_team_label(base)
    base = _strip_accents(base)
    return re.sub(r"\s+", " ", base).strip()


def make_event_map_key(home_team: str, away_team: str) -> str:
    return f"{normalize_team_for_event_map(home_team)}|{normalize_team_for_event_map(away_team)}"
