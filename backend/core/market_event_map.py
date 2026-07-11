"""Shared team-name normalization for provider event map and auto resolver."""

from __future__ import annotations

import re


def normalize_team_for_event_map(name: str) -> str:
    cleaned = re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip()
    return re.sub(r"\s+", " ", cleaned)


def make_event_map_key(home_team: str, away_team: str) -> str:
    return f"{normalize_team_for_event_map(home_team)}|{normalize_team_for_event_map(away_team)}"
