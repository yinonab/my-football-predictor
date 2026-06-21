"""Phase 4R.3 — Refresh multi-provider recent-form fusion cache."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from core.api_football_recent_form import ApiFootballRecentFormClient  # noqa: E402
from core.football_data_recent_form import discover_football_data_team_ids  # noqa: E402
from core.recent_form_fusion import (  # noqa: E402
    FUSION_CACHE_PATH,
    TeamFusionResult,
    all_wc_registry_keys,
    build_fusion_cache_payload,
    build_team_fusion,
    load_fusion_cache,
    parse_cli_team_names,
    resolve_cli_team_registry_keys,
    team_fusion_result_from_cache_entry,
    write_fusion_cache_safe,
)
from data.football_data import FootballDataClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh recent_form_fusion_cache.json")
    parser.add_argument("--teams", type=str, default="")
    parser.add_argument("--team", action="append", default=[])
    parser.add_argument("--all-wc-teams", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true", help="Allow overwrite even if new cache is empty/bad")
    parser.add_argument("--sleep", type=float, default=None, help="Sleep between API-Football calls")
    parser.add_argument("--fd-sleep", type=float, default=15.0, help="Sleep between football-data teams")
    args = parser.parse_args()

    if args.write and args.dry_run:
        print("Use either --dry-run or --write, not both.")
        sys.exit(1)

    if args.all_wc_teams:
        keys = all_wc_registry_keys()
    else:
        names = parse_cli_team_names(args.teams or None, args.team)
        keys = resolve_cli_team_registry_keys(names) if names else []

    if not keys:
        print("No teams selected. Use --teams, --team, or --all-wc-teams.")
        sys.exit(1)

    fd_enabled = config.recent_form_api_enabled()
    apif_enabled = config.api_football_recent_form_enabled()
    if not fd_enabled and not apif_enabled:
        print("No API keys configured. Static-only fusion can run but APIs disabled.")
        print("Set FOOTBALL_DATA_API_KEY and/or API_FOOTBALL_API_KEY in backend/.env")

    fd_client = FootballDataClient() if fd_enabled else None
    apif_client = ApiFootballRecentFormClient(sleep_seconds=args.sleep) if apif_enabled else None
    id_map: dict[str, int] = {}
    if fd_client:
        id_map, _, _ = discover_football_data_team_ids(fd_client)

    team_results: dict[str, TeamFusionResult] = {}
    refresh_errors: list[str] = []

    existing_payload, _ = load_fusion_cache()
    existing_teams = (existing_payload or {}).get("teams") or {}

    for idx, team_key in enumerate(keys):
        english = team_key.split(" (")[0]
        print(f"[{idx + 1}/{len(keys)}] {english}...")
        try:
            result = build_team_fusion(
                team_key,
                fd_client=fd_client,
                apif_client=apif_client,
                id_map=id_map,
                include_live_apis=True,
            )
            if result.coverage_count <= 0:
                preserved = team_fusion_result_from_cache_entry(
                    team_key, existing_teams.get(team_key) or {}
                )
                if preserved is not None:
                    team_results[team_key] = preserved
                    refresh_errors.append(f"{english}:preserved_existing_on_empty")
                    print("  preserved existing cache entry (empty refresh)")
                    continue
            team_results[team_key] = result
            print(
                f"  candidates={result.candidate_count} deduped={result.coverage_count} "
                f"last_10={len(result.last_10_finished)} quality={result.coverage_quality}"
            )
        except Exception as exc:
            refresh_errors.append(f"{english}:{type(exc).__name__}")
            print(f"  error: {type(exc).__name__}")
            preserved = team_fusion_result_from_cache_entry(
                team_key, existing_teams.get(team_key) or {}
            )
            if preserved is not None:
                team_results[team_key] = preserved
                print("  preserved existing cache entry (fetch error)")
        if fd_client and args.fd_sleep and idx + 1 < len(keys):
            time.sleep(args.fd_sleep)

    # Preserve teams not refreshed this run
    for team_key, entry in existing_teams.items():
        if team_key in team_results:
            continue
        preserved = team_fusion_result_from_cache_entry(team_key, entry)
        if preserved is not None:
            team_results[team_key] = preserved

    payload = build_fusion_cache_payload(team_results, refresh_errors=refresh_errors)

    if args.dry_run:
        print("\nDry run complete — no cache written.")
        print(f"  teams: {len(team_results)}")
        print(f"  total last_10 rows: {sum(len(tr.last_10_finished) for tr in team_results.values())}")
        return

    if not args.write:
        print("\nPass --write to persist cache (or --dry-run for preview only).")
        return

    path, status = write_fusion_cache_safe(
        payload,
        team_results=team_results,
        force=args.force,
    )
    if path is None:
        print(f"Write rejected: {status}")
        if FUSION_CACHE_PATH.exists():
            print(f"Preserving existing cache at {FUSION_CACHE_PATH}")
        sys.exit(1)

    print(f"Wrote fusion cache to {path}")


if __name__ == "__main__":
    main()
