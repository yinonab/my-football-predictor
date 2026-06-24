"""Discover Sofascore national-team IDs for WC 2026 registry teams."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from data.database import FIFA_ELO_2026
from data.nt_team_aliases import registry_english_for_alias
from data.sofascore import (
    KNOWN_SOFASCORE_NT_TEAM_IDS,
    SofascoreClient,
    is_senior_mens_football_team,
    normalize_search_name,
    parse_team_search_results,
)

Confidence = Literal["exact", "likely", "ambiguous", "missing"]

REGISTRY = set(FIFA_ELO_2026.keys())

# Verified WC 2026 participant IDs from sofascore.com FIFA World Cup 2026 tournament page.
# Used for offline seeding/validation when RapidAPI discovery is unavailable.
WC2026_SOFASCORE_NT_TEAM_IDS: dict[str, int] = {
    "algeria": 4691,
    "argentina": 4819,
    "australia": 4741,
    "austria": 4718,
    "belgium": 4717,
    "bosnia": 4479,
    "brazil": 4748,
    "canada": 4752,
    "cape verde": 4753,
    "colombia": 4820,
    "croatia": 4715,
    "curacao": 55827,
    "czechia": 4714,
    "dr congo": 4823,
    "ecuador": 4757,
    "egypt": 4758,
    "england": 4713,
    "france": 4481,
    "germany": 4711,
    "ghana": 4764,
    "haiti": 7229,
    "iran": 4766,
    "iraq": 4767,
    "ivory coast": 4768,
    "japan": 4770,
    "jordan": 4771,
    "mexico": 4781,
    "morocco": 4778,
    "netherlands": 4705,
    "new zealand": 4784,
    "norway": 4475,
    "panama": 5164,
    "paraguay": 4789,
    "portugal": 4704,
    "qatar": 4792,
    "saudi arabia": 4834,
    "scotland": 4695,
    "senegal": 4739,
    "south africa": 4736,
    "south korea": 4735,
    "spain": 4698,
    "sweden": 4688,
    "switzerland": 4699,
    "tunisia": 4729,
    "turkey": 4700,
    "usa": 4724,
    "uruguay": 4725,
    "uzbekistan": 4723,
}

# Search query overrides when registry English label differs from Sofascore naming.
SOFASCORE_SEARCH_QUERY_OVERRIDES: dict[str, str] = {
    "usa": "United States",
    "bosnia": "Bosnia and Herzegovina",
    "south korea": "Korea Republic",
    "czechia": "Czech Republic",
    "ivory coast": "Cote d'Ivoire",
    "dr congo": "DR Congo",
    "curacao": "Curacao",
    "cape verde": "Cape Verde",
    "saudi arabia": "Saudi Arabia",
    "turkey": "Turkey",
}

# FIFA nameCode hints for disambiguation (not provider IDs).
WC2026_FIFA_NAME_CODES: dict[str, str] = {
    "mexico": "MEX",
    "south africa": "RSA",
    "south korea": "KOR",
    "czechia": "CZE",
    "czech republic": "CZE",
    "canada": "CAN",
    "bosnia and herzegovina": "BIH",
    "bosnia": "BIH",
    "qatar": "QAT",
    "switzerland": "SUI",
    "brazil": "BRA",
    "morocco": "MAR",
    "haiti": "HAI",
    "scotland": "SCO",
    "united states": "USA",
    "usa": "USA",
    "paraguay": "PAR",
    "australia": "AUS",
    "turkey": "TUR",
    "germany": "GER",
    "curacao": "CUW",
    "ivory coast": "CIV",
    "ecuador": "ECU",
    "netherlands": "NED",
    "japan": "JPN",
    "sweden": "SWE",
    "tunisia": "TUN",
    "belgium": "BEL",
    "egypt": "EGY",
    "iran": "IRN",
    "new zealand": "NZL",
    "spain": "ESP",
    "cape verde": "CPV",
    "saudi arabia": "KSA",
    "uruguay": "URU",
    "france": "FRA",
    "senegal": "SEN",
    "iraq": "IRQ",
    "norway": "NOR",
    "argentina": "ARG",
    "algeria": "ALG",
    "austria": "AUT",
    "jordan": "JOR",
    "portugal": "POR",
    "dr congo": "COD",
    "uzbekistan": "UZB",
    "colombia": "COL",
    "england": "ENG",
    "croatia": "CRO",
    "ghana": "GHA",
    "panama": "PAN",
}


@dataclass(frozen=True)
class SofascoreTeamDiscoveryRow:
    registry_key: str
    english_name: str
    search_query: str
    sofascore_team_id: int | None
    selected_name: str | None
    selected_name_code: str | None
    selected_country: str | None
    confidence: Confidence
    rejection_reason: str | None
    candidate_count: int
    filtered_candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_query_for_registry_key(registry_key: str) -> str:
    english = registry_key.split(" (")[0].strip()
    canonical = registry_english_for_alias(english)
    norm = normalize_search_name(canonical)
    return SOFASCORE_SEARCH_QUERY_OVERRIDES.get(norm, canonical)


def _name_code(entity: dict[str, Any]) -> str:
    return str(entity.get("nameCode") or entity.get("shortName") or "").upper()


def _country_label(entity: dict[str, Any]) -> str | None:
    country = entity.get("country")
    if isinstance(country, dict):
        return str(country.get("name") or country.get("alpha2") or "") or None
    if country is not None:
        return str(country)
    return entity.get("country") or entity.get("category")


def _score_candidate(
    entity: dict[str, Any],
    *,
    expected_norm: str,
    expected_code: str | None,
) -> int:
    score = 0
    name_norm = normalize_search_name(str(entity.get("name") or ""))
    if name_norm == expected_norm:
        score += 100
    if expected_code and _name_code(entity) == expected_code:
        score += 50
    if entity.get("national") is True:
        score += 10
    sport = entity.get("sport") or {}
    if isinstance(sport, dict) and int(sport.get("id") or 0) == 1:
        score += 5
    if str(entity.get("gender") or "").upper() == "M":
        score += 3
    return score


def classify_discovery_row(
    registry_key: str,
    *,
    search_results: list[dict[str, Any]],
    search_query: str,
) -> SofascoreTeamDiscoveryRow:
    english = registry_key.split(" (")[0].strip()
    expected_norm = normalize_search_name(registry_english_for_alias(english))
    expected_code = WC2026_FIFA_NAME_CODES.get(expected_norm)

    filtered = [t for t in search_results if is_senior_mens_football_team(t)]
    known_id = KNOWN_SOFASCORE_NT_TEAM_IDS.get(expected_norm)

    if not filtered:
        reason = "no_senior_mens_football_candidate"
        if search_results and not filtered:
            reason = "rejected_non_nt_or_youth_women"
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=None,
            selected_name=None,
            selected_name_code=None,
            selected_country=None,
            confidence="missing",
            rejection_reason=reason,
            candidate_count=len(search_results),
            filtered_candidate_count=0,
        )

    ranked = sorted(
        filtered,
        key=lambda e: _score_candidate(
            e,
            expected_norm=expected_norm,
            expected_code=expected_code,
        ),
        reverse=True,
    )
    top = ranked[0]
    top_score = _score_candidate(top, expected_norm=expected_norm, expected_code=expected_code)
    second_score = (
        _score_candidate(ranked[1], expected_norm=expected_norm, expected_code=expected_code)
        if len(ranked) > 1
        else -1
    )

    if known_id is not None:
        known_matches = [t for t in filtered if int(t.get("id") or 0) == known_id]
        if len(known_matches) == 1:
            pick = known_matches[0]
            return SofascoreTeamDiscoveryRow(
                registry_key=registry_key,
                english_name=english,
                search_query=search_query,
                sofascore_team_id=int(pick["id"]),
                selected_name=str(pick.get("name") or ""),
                selected_name_code=_name_code(pick) or None,
                selected_country=_country_label(pick),
                confidence="exact",
                rejection_reason=None,
                candidate_count=len(search_results),
                filtered_candidate_count=len(filtered),
            )

    exact_name = [t for t in filtered if normalize_search_name(str(t.get("name") or "")) == expected_norm]
    if len(exact_name) == 1:
        pick = exact_name[0]
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=int(pick["id"]),
            selected_name=str(pick.get("name") or ""),
            selected_name_code=_name_code(pick) or None,
            selected_country=_country_label(pick),
            confidence="exact",
            rejection_reason=None,
            candidate_count=len(search_results),
            filtered_candidate_count=len(filtered),
        )

    if expected_code:
        code_matches = [t for t in filtered if _name_code(t) == expected_code]
        if len(code_matches) == 1:
            pick = code_matches[0]
            return SofascoreTeamDiscoveryRow(
                registry_key=registry_key,
                english_name=english,
                search_query=search_query,
                sofascore_team_id=int(pick["id"]),
                selected_name=str(pick.get("name") or ""),
                selected_name_code=_name_code(pick) or None,
                selected_country=_country_label(pick),
                confidence="exact",
                rejection_reason=None,
                candidate_count=len(search_results),
                filtered_candidate_count=len(filtered),
            )

    if len(filtered) > 1 and top_score == second_score:
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=None,
            selected_name=None,
            selected_name_code=None,
            selected_country=None,
            confidence="ambiguous",
            rejection_reason="multiple_equal_candidates",
            candidate_count=len(search_results),
            filtered_candidate_count=len(filtered),
        )

    if len(filtered) > 1 and top_score < 50:
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=None,
            selected_name=None,
            selected_name_code=None,
            selected_country=None,
            confidence="ambiguous",
            rejection_reason="weak_top_candidate",
            candidate_count=len(search_results),
            filtered_candidate_count=len(filtered),
        )

    if len(filtered) == 1:
        pick = filtered[0]
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=int(pick["id"]),
            selected_name=str(pick.get("name") or ""),
            selected_name_code=_name_code(pick) or None,
            selected_country=_country_label(pick),
            confidence="likely",
            rejection_reason=None,
            candidate_count=len(search_results),
            filtered_candidate_count=len(filtered),
        )

    if top_score >= 50:
        return SofascoreTeamDiscoveryRow(
            registry_key=registry_key,
            english_name=english,
            search_query=search_query,
            sofascore_team_id=int(top["id"]),
            selected_name=str(top.get("name") or ""),
            selected_name_code=_name_code(top) or None,
            selected_country=_country_label(top),
            confidence="likely",
            rejection_reason=None,
            candidate_count=len(search_results),
            filtered_candidate_count=len(filtered),
        )

    return SofascoreTeamDiscoveryRow(
        registry_key=registry_key,
        english_name=english,
        search_query=search_query,
        sofascore_team_id=None,
        selected_name=None,
        selected_name_code=None,
        selected_country=None,
        confidence="ambiguous",
        rejection_reason="unresolved_multiple_candidates",
        candidate_count=len(search_results),
        filtered_candidate_count=len(filtered),
    )


def discover_sofascore_team_ids(
    client: SofascoreClient,
    *,
    registry_keys: list[str] | None = None,
    sleep_seconds: float = 0.75,
) -> tuple[list[SofascoreTeamDiscoveryRow], dict[str, int]]:
    """
    Discover Sofascore team IDs for registry teams.

    Returns rows plus validated id_map (exact/likely only).
    """
    keys = registry_keys or sorted(REGISTRY)
    rows: list[SofascoreTeamDiscoveryRow] = []
    id_map: dict[str, int] = {}

    for idx, registry_key in enumerate(keys):
        query = search_query_for_registry_key(registry_key)
        payload = client._request("/teams/search", params={"name": query})
        results = parse_team_search_results(payload) if payload else []
        row = classify_discovery_row(registry_key, search_results=results, search_query=query)
        rows.append(row)
        if row.confidence in ("exact", "likely") and row.sofascore_team_id is not None:
            id_map[registry_key] = int(row.sofascore_team_id)
        if sleep_seconds and idx + 1 < len(keys):
            time.sleep(sleep_seconds)

    return rows, id_map


def validated_name_id_map(rows: list[SofascoreTeamDiscoveryRow]) -> dict[str, int]:
    """English normalized name -> Sofascore id for exact/likely rows."""
    out: dict[str, int] = {}
    for row in rows:
        if row.confidence not in ("exact", "likely") or row.sofascore_team_id is None:
            continue
        out[normalize_search_name(row.english_name)] = int(row.sofascore_team_id)
    return out


def seed_wc2026_discovery_rows() -> tuple[list[SofascoreTeamDiscoveryRow], dict[str, int]]:
    """Build exact-confidence rows from curated WC 2026 Sofascore tournament IDs."""
    rows: list[SofascoreTeamDiscoveryRow] = []
    id_map: dict[str, int] = {}
    for registry_key in sorted(REGISTRY):
        english = registry_key.split(" (")[0].strip()
        norm = normalize_search_name(english)
        sofa_id = WC2026_SOFASCORE_NT_TEAM_IDS.get(norm)
        if sofa_id is None:
            rows.append(
                SofascoreTeamDiscoveryRow(
                    registry_key=registry_key,
                    english_name=english,
                    search_query=search_query_for_registry_key(registry_key),
                    sofascore_team_id=None,
                    selected_name=None,
                    selected_name_code=None,
                    selected_country=None,
                    confidence="missing",
                    rejection_reason="not_in_wc2026_curated_map",
                    candidate_count=0,
                    filtered_candidate_count=0,
                )
            )
            continue
        code = WC2026_FIFA_NAME_CODES.get(norm)
        rows.append(
            SofascoreTeamDiscoveryRow(
                registry_key=registry_key,
                english_name=english,
                search_query=search_query_for_registry_key(registry_key),
                sofascore_team_id=int(sofa_id),
                selected_name=english,
                selected_name_code=code,
                selected_country=None,
                confidence="exact",
                rejection_reason=None,
                candidate_count=1,
                filtered_candidate_count=1,
            )
        )
        id_map[registry_key] = int(sofa_id)
    return rows, id_map
