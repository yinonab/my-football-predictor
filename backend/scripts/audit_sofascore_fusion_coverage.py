"""Audit Sofascore coverage inside local fusion cache (offline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.recent_form_fusion import (  # noqa: E402
    FUSION_CACHE_PATH,
    load_fusion_cache,
    summarize_sofascore_fusion_coverage,
)
from data.database import FIFA_ELO_2026  # noqa: E402
from data.sofascore import SOFASCORE_FUSION_PROVIDER, load_sofascore_registry_id_map  # noqa: E402

SAMPLE_TEAMS = (
    "Brazil",
    "Spain",
    "Scotland",
    "Haiti",
    "New Zealand",
    "Cape Verde",
    "Curacao",
    "DR Congo",
)


def _english_to_registry(english: str) -> str | None:
    for key in FIFA_ELO_2026:
        if key.split(" (")[0] == english:
            return key
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sofascore fusion cache coverage audit")
    parser.parse_args()

    payload, err = load_fusion_cache()
    if err or not payload:
        print(f"Fusion cache unavailable: {err}")
        return 1

    summary = summarize_sofascore_fusion_coverage(payload, registry_keys=set(FIFA_ELO_2026))
    id_map = load_sofascore_registry_id_map()
    teams = payload.get("teams") or {}

    ten_plus = 0
    under_five = 0
    refreshed_ok = 0
    for key, entry in teams.items():
        if not isinstance(entry, dict):
            continue
        fusion = entry.get("fusion") or {}
        count = len(fusion.get("last_10_finished") or [])
        if entry.get("provider_ids", {}).get("sofascore") is not None:
            refreshed_ok += 1
        if count >= 10:
            ten_plus += 1
        if count < 5:
            under_five += 1

    print("Sofascore fusion coverage")
    print(f"  cache_path: {FUSION_CACHE_PATH}")
    print(f"  last_updated_utc: {payload.get('last_updated_utc')}")
    print(f"  sources: {json.dumps(payload.get('sources') or {}, ensure_ascii=False)}")
    print(f"  mapped_ids_in_file: {len(id_map)}")
    print(f"  teams_with_provider_ids.sofascore: {summary['teams_with_sofascore_id']}")
    print(f"  teams_refreshed_with_sofascore_id: {refreshed_ok}")
    print(f"  sofascore_candidate_rows: {summary['sofascore_candidate_rows']}")
    print(f"  finished_rows: {summary['finished_match_rows']}")
    print(f"  teams_with_10_plus_last10: {ten_plus}")
    print(f"  teams_with_under_5_last10: {under_five}")
    print(f"  rows_with_has_xg: {summary['matches_with_has_xg']}")
    print(f"  source_mix_sofascore_recent_form: {summary['source_mix_sofascore']}")
    print(f"  missing_mappings: {len(summary['missing_sofascore_mappings'])}")
    if summary["missing_sofascore_mappings"]:
        print(f"    {', '.join(k.split(' (')[0] for k in summary['missing_sofascore_mappings'][:20])}")

    mapped_registry = set(id_map)
    wc_registry = set(FIFA_ELO_2026)
    unmapped = sorted(wc_registry - mapped_registry)
    print(f"  validated_id_file_entries: {len(id_map)}")
    if unmapped:
        print(f"  teams_without_validated_id: {len(unmapped)}")
        print(f"    {', '.join(k.split(' (')[0] for k in unmapped)}")

    print("\nSample teams:")
    for english in SAMPLE_TEAMS:
        reg = _english_to_registry(english)
        if not reg:
            continue
        entry = teams.get(reg) or {}
        fusion = entry.get("fusion") or {}
        mix = fusion.get("source_mix") or {}
        last10 = fusion.get("last_10_finished") or []
        sample = last10[0] if last10 else {}
        print(
            f"  {english}: sofa_id={entry.get('provider_ids', {}).get('sofascore')} "
            f"last10={len(last10)} mix={mix.get(SOFASCORE_FUSION_PROVIDER, 0)} "
            f"latest={sample.get('date')} vs {sample.get('opponent')} "
            f"has_xg={sample.get('has_xg')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
