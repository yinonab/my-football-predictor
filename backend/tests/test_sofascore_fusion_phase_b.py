"""Phase B — Sofascore fusion collector and cache integration tests (fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.recent_form_fusion import (
    FUSION_SOURCE_ID,
    build_fusion_cache_payload,
    build_team_fusion,
    collect_sofascore_candidates,
    fuse_team_matches,
    fusion_match_to_normalized,
    fusion_rows_from_payload,
    load_fusion_cache_rows,
    summarize_sofascore_fusion_coverage,
)
from data.sofascore import (
    SOFASCORE_FUSION_PROVIDER,
    sofascore_event_to_fusion_match,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BRAZIL_REGISTRY = "Brazil (ברזיל)"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _brazil_home_event() -> dict:
    return _load_fixture("sofascore_last_matches_brazil_sample.json")["events"][0]


def _brazil_away_event() -> dict:
    return _load_fixture("sofascore_last_matches_brazil_away_sample.json")["events"][0]


def test_sofascore_event_to_fusion_match_home() -> None:
    match = sofascore_event_to_fusion_match(
        _brazil_home_event(),
        team_registry_key=BRAZIL_REGISTRY,
        sofascore_team_id=4748,
    )
    assert match is not None
    assert match["provider"] == SOFASCORE_FUSION_PROVIDER
    assert match["provider_fixture_id"] == "12456789"
    assert match["team"] == "Brazil"
    assert match["opponent"] == "Mexico"
    assert match["score_for"] == 2
    assert match["score_against"] == 0
    assert match["is_home"] is True
    assert match["has_xg"] is True
    assert match["opponent_ranking"] == 14
    assert match["status_type"] == "finished"
    assert match["unique_tournament_id"] == 851


def test_sofascore_event_to_fusion_match_away() -> None:
    match = sofascore_event_to_fusion_match(
        _brazil_away_event(),
        team_registry_key=BRAZIL_REGISTRY,
        sofascore_team_id=4748,
    )
    assert match is not None
    assert match["score_for"] == 2
    assert match["score_against"] == 1
    assert match["is_home"] is False
    assert match["opponent"] == "Mexico"
    assert match["opponent_ranking"] == 14


@patch("core.recent_form_fusion.config.sofascore_enabled", return_value=True)
def test_collect_sofascore_candidates_brazil(_mock_enabled: MagicMock) -> None:
    client = MagicMock()
    client.is_available = True
    client.fetch_last_match_events.return_value = [_brazil_home_event()]

    rows, meta = collect_sofascore_candidates(
        BRAZIL_REGISTRY,
        client=client,
        id_map={BRAZIL_REGISTRY: 4748},
    )
    assert meta["status"] == "ok"
    assert meta["sofascore_team_id"] == 4748
    assert len(rows) == 1
    assert rows[0]["provider"] == SOFASCORE_FUSION_PROVIDER
    assert rows[0]["provider_fixture_id"] == "12456789"


@patch("core.recent_form_fusion.config.sofascore_enabled", return_value=True)
def test_collect_sofascore_empty_last_matches(_mock_enabled: MagicMock) -> None:
    client = MagicMock()
    client.is_available = True
    client.fetch_last_match_events.return_value = []

    rows, meta = collect_sofascore_candidates(
        BRAZIL_REGISTRY,
        client=client,
        id_map={BRAZIL_REGISTRY: 4748},
    )
    assert rows == []
    assert meta["status"] == "no_results"


@patch("core.recent_form_fusion.config.sofascore_enabled", return_value=True)
def test_collect_sofascore_skips_unfinished(_mock_enabled: MagicMock) -> None:
    client = MagicMock()
    client.is_available = True
    unfinished = dict(_brazil_home_event())
    unfinished["status"] = {"code": 0, "type": "notstarted", "description": "Not started"}
    client.fetch_last_match_events.return_value = [unfinished]

    rows, meta = collect_sofascore_candidates(
        BRAZIL_REGISTRY,
        client=client,
        id_map={BRAZIL_REGISTRY: 4748},
    )
    assert rows == []
    assert meta["status"] == "no_finished_results"


@patch("core.recent_form_fusion.config.sofascore_enabled", return_value=True)
def test_provider_ids_namespaced_and_not_overwritten(_mock_enabled: MagicMock) -> None:
    ss_client = MagicMock()
    ss_client.is_available = True
    ss_client.fetch_last_match_events.return_value = [_brazil_home_event()]

    with patch(
        "core.recent_form_fusion.collect_football_data_candidates",
        return_value=([], {"status": "disabled", "football_data_team_id": None}),
    ), patch(
        "core.recent_form_fusion.collect_api_football_candidates",
        return_value=([], {"status": "disabled", "api_football_team_id": None}),
    ):
        result = build_team_fusion(
            BRAZIL_REGISTRY,
            sofascore_client=ss_client,
            include_sofascore=True,
            include_football_data=False,
            include_api_football=False,
        )

    assert result.provider_ids == {"sofascore": 4748}
    assert "football_data" not in result.provider_ids
    assert "api_football" not in result.provider_ids

    with patch(
        "core.recent_form_fusion.collect_football_data_candidates",
        return_value=(
            [{"provider": "football_data_recent_form", "date": "2025-01-01", "team": "Brazil", "opponent": "X", "score_for": 1, "score_against": 0, "source_priority": 110}],
            {"status": "ok", "football_data_team_id": 26},
        ),
    ), patch(
        "core.recent_form_fusion.collect_api_football_candidates",
        return_value=([], {"status": "ok", "api_football_team_id": 6}),
    ):
        merged = build_team_fusion(
            BRAZIL_REGISTRY,
            sofascore_client=ss_client,
            include_sofascore=True,
        )

    assert merged.provider_ids["sofascore"] == 4748
    assert merged.provider_ids["football_data"] == 26
    assert merged.provider_ids["api_football"] == 6


def test_fusion_cache_includes_sofascore_source_mix() -> None:
    sofa_match = sofascore_event_to_fusion_match(
        _brazil_home_event(),
        team_registry_key=BRAZIL_REGISTRY,
        sofascore_team_id=4748,
    )
    assert sofa_match is not None

    fused = fuse_team_matches(BRAZIL_REGISTRY, [sofa_match])
    assert fused.source_mix.get(SOFASCORE_FUSION_PROVIDER) == 1

    payload = build_fusion_cache_payload({BRAZIL_REGISTRY: fused})
    rows, meta = fusion_rows_from_payload(payload)
    assert len(rows) == 1
    assert rows[0].source == FUSION_SOURCE_ID
    assert meta["row_count"] == 1

    normalized = fusion_match_to_normalized(sofa_match)
    assert normalized.goals_for == 2
    assert normalized.goals_against == 0


def test_summarize_sofascore_fusion_coverage() -> None:
    sofa_match = sofascore_event_to_fusion_match(
        _brazil_home_event(),
        team_registry_key=BRAZIL_REGISTRY,
        sofascore_team_id=4748,
    )
    assert sofa_match is not None
    fused = fuse_team_matches(BRAZIL_REGISTRY, [sofa_match])
    fused.provider_ids = {"sofascore": 4748}
    payload = build_fusion_cache_payload({BRAZIL_REGISTRY: fused})

    summary = summarize_sofascore_fusion_coverage(payload)
    assert summary["teams_with_sofascore_id"] == 1
    assert summary["sofascore_candidate_rows"] == 1
    assert summary["finished_match_rows"] == 1
    assert summary["matches_with_has_xg"] == 1
    assert summary["source_mix_sofascore"] == 1


def test_football_data_priority_beats_sofascore_on_dedupe() -> None:
    fd_match = {
        "provider": "football_data_recent_form",
        "source_priority": 110,
        "provider_fixture_id": "fd:1",
        "team": "Brazil",
        "opponent": "Mexico",
        "date": "2024-06-10",
        "score_for": 2,
        "score_against": 0,
    }
    sofa_match = sofascore_event_to_fusion_match(
        _brazil_home_event(),
        team_registry_key=BRAZIL_REGISTRY,
        sofascore_team_id=4748,
    )
    assert sofa_match is not None

    fused = fuse_team_matches(BRAZIL_REGISTRY, [sofa_match, fd_match])
    assert fused.last_10_finished[0]["provider"] == "football_data_recent_form"


@patch("core.recent_form_fusion.config.sofascore_enabled", return_value=False)
def test_sofascore_disabled_by_default(_mock_enabled: MagicMock) -> None:
    rows, meta = collect_sofascore_candidates(BRAZIL_REGISTRY)
    assert rows == []
    assert meta["status"] == "disabled"
