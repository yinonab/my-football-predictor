"""Tests for WC 2026 live match persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core import match_store
from core.match_store import append_live_match, load_live_matches, save_live_matches
from data.nt_match import NationalTeamMatch


def test_append_live_match_dedupes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "live.json"
    monkeypatch.setattr(match_store, "LIVE_MATCHES_PATH", path)

    append_live_match(
        home_key="Brazil (ברזיל)",
        away_key="France (צרפת)",
        home_goals=2,
        away_goals=1,
        match_date="2026-06-15",
    )
    append_live_match(
        home_key="Brazil (ברזיל)",
        away_key="France (צרפת)",
        home_goals=2,
        away_goals=1,
        match_date="2026-06-15",
    )
    matches = load_live_matches()
    assert len(matches) == 1
    assert matches[0].competition == "FIFA World Cup 2026"


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "live.json"
    monkeypatch.setattr(match_store, "LIVE_MATCHES_PATH", path)
    sample = [
        NationalTeamMatch(
            date="2026-06-20",
            home="Argentina (ארגנטינה)",
            away="Germany (גרמניה)",
            home_goals=1,
            away_goals=1,
            competition="FIFA World Cup 2026",
        )
    ]
    save_live_matches(sample)
    loaded = load_live_matches()
    assert len(loaded) == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["match_count"] == 1
