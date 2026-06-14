"""API-Football client tests (no network)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from data.api_football import ApiFootballClient


def test_unavailable_without_key() -> None:
    client = ApiFootballClient(api_key="")
    assert not client.is_available


def test_enrich_falls_back_without_key() -> None:
    client = ApiFootballClient(api_key="")
    base = {"elo": 1700.0, "form": 0.5, "attack": 0.5, "defense": 0.5}
    assert client.enrich_team_data("Brazil (ברזיל)", base) == base


def test_enrich_merges_live_form() -> None:
    client = ApiFootballClient(api_key="test-key")
    base = {"elo": 1700.0, "form": 0.5, "attack": 0.5, "defense": 0.5}

    with patch.object(client, "search_team", return_value={"id": 6, "name": "Brazil"}):
        with patch.object(
            client,
            "fetch_recent_form",
            return_value={"form": 0.8, "attack": 0.7, "defense": 0.6},
        ):
            merged = client.enrich_team_data("Brazil (ברזיל)", base)

    assert merged["form"] == 0.8
    assert merged["attack"] == 0.7
    assert merged["elo"] == 1700.0
