"""Offline tests for Sofascore team ID discovery."""

from __future__ import annotations

from core.sofascore_team_discovery import (
    classify_discovery_row,
    search_query_for_registry_key,
    validated_name_id_map,
)
from data.sofascore import (
    PROVIDER_NAMESPACE,
    load_sofascore_registry_id_map,
    sofascore_provider_ids,
)


def _entity(
    *,
    team_id: int,
    name: str,
    name_code: str = "",
    gender: str = "M",
    national: bool = True,
    sport_id: int = 1,
    sport_slug: str = "football",
) -> dict:
    return {
        "id": team_id,
        "name": name,
        "nameCode": name_code,
        "gender": gender,
        "national": national,
        "sport": {"id": sport_id, "slug": sport_slug, "name": sport_slug.title()},
    }


def test_search_query_usa_override() -> None:
    assert search_query_for_registry_key("USA (ארצות הברית)") == "United States"


def test_discovery_rejects_women_and_u23() -> None:
    results = [
        _entity(team_id=7311, name="Brazil", gender="F"),
        _entity(team_id=21896, name="Brazil U23"),
        _entity(team_id=8801, name="Brazil", sport_id=2, sport_slug="basketball", name_code="BRA"),
    ]
    row = classify_discovery_row(
        "Brazil (ברזיל)",
        search_results=results,
        search_query="Brazil",
    )
    assert row.confidence == "missing"
    assert row.sofascore_team_id is None


def test_discovery_exact_brazil() -> None:
    results = [
        _entity(team_id=4748, name="Brazil", name_code="BRA"),
        _entity(team_id=21896, name="Brazil U23"),
    ]
    row = classify_discovery_row(
        "Brazil (ברזיל)",
        search_results=results,
        search_query="Brazil",
    )
    assert row.confidence == "exact"
    assert row.sofascore_team_id == 4748


def test_discovery_ambiguous_not_auto_selected() -> None:
    results = [
        _entity(team_id=100, name="Jordan", name_code="JOR"),
        _entity(team_id=101, name="Jordan", name_code="JOR"),
    ]
    row = classify_discovery_row(
        "Jordan (יורדן)",
        search_results=results,
        search_query="Jordan",
    )
    assert row.confidence == "ambiguous"
    assert row.sofascore_team_id is None


def test_provider_ids_namespaced() -> None:
    assert sofascore_provider_ids(4748) == {PROVIDER_NAMESPACE: 4748}


def test_validated_name_id_map_skips_ambiguous() -> None:
    from core.sofascore_team_discovery import SofascoreTeamDiscoveryRow

    rows = [
        SofascoreTeamDiscoveryRow(
            registry_key="Brazil (ברזיל)",
            english_name="Brazil",
            search_query="Brazil",
            sofascore_team_id=4748,
            selected_name="Brazil",
            selected_name_code="BRA",
            selected_country=None,
            confidence="exact",
            rejection_reason=None,
            candidate_count=2,
            filtered_candidate_count=1,
        ),
        SofascoreTeamDiscoveryRow(
            registry_key="Jordan (יורדן)",
            english_name="Jordan",
            search_query="Jordan",
            sofascore_team_id=None,
            selected_name=None,
            selected_name_code=None,
            selected_country=None,
            confidence="ambiguous",
            rejection_reason="multiple_equal_candidates",
            candidate_count=2,
            filtered_candidate_count=2,
        ),
    ]
    out = validated_name_id_map(rows)
    assert out == {"brazil": 4748}
    assert "jordan" not in out


def test_load_registry_id_map_empty_when_missing_file() -> None:
    # Does not require network; file may be absent locally.
    assert isinstance(load_sofascore_registry_id_map(), dict)


def test_seed_wc2026_covers_all_registry_teams() -> None:
    from core.sofascore_team_discovery import REGISTRY, seed_wc2026_discovery_rows

    rows, id_map = seed_wc2026_discovery_rows()
    assert len(rows) == len(REGISTRY) == 48
    assert len(id_map) == 48
    assert all(r.confidence == "exact" for r in rows)
    assert all(r.sofascore_team_id is not None for r in rows)


def test_all_validated_mappings_resolve_provider_ids() -> None:
    from data.database import FIFA_ELO_2026
    from data.sofascore import known_sofascore_registry_team_id, sofascore_provider_ids

    for registry_key in FIFA_ELO_2026:
        sofa_id = known_sofascore_registry_team_id(registry_key)
        assert sofa_id is not None, registry_key
        assert sofascore_provider_ids(sofa_id) == {"sofascore": sofa_id}


def test_wc2026_curated_brazil_unchanged() -> None:
    from core.sofascore_team_discovery import WC2026_SOFASCORE_NT_TEAM_IDS

    assert WC2026_SOFASCORE_NT_TEAM_IDS["brazil"] == 4748


def test_api_main_does_not_import_sofascore_client() -> None:
    import api.main as api_main

    source = api_main.__file__ or ""
    assert source.endswith("main.py")
    # Predict path must not import live Sofascore client module.
    assert "data.sofascore" not in open(source, encoding="utf-8").read()
