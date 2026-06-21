"""Phase 4R.3 — Multi-provider recent-form fusion diagnostic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from core.api_football_recent_form import ApiFootballRecentFormClient  # noqa: E402
from core.football_data_recent_form import discover_football_data_team_ids  # noqa: E402
from core.recent_form_fusion import (  # noqa: E402
    build_team_fusion,
    parse_cli_team_names,
    resolve_cli_team_registry_keys,
)
from data.football_data import FootballDataClient  # noqa: E402

DEFAULT_TEAMS = (
    "Brazil",
    "New Zealand",
    "Haiti",
    "Cape Verde",
    "Sweden",
    "Morocco",
)


def _print_team_report(
    team_key: str,
    *,
    dry_run: bool,
    id_map: dict[str, int],
    fd_client: FootballDataClient | None,
    apif_client: ApiFootballRecentFormClient | None,
) -> None:
    english = team_key.split(" (")[0]
    print(f"\n=== {english} ===")
    print(f"  registry_key: {team_key}")
    print(f"  football_data_team_id: {id_map.get(team_key)}")
    if apif_client and config.api_football_recent_form_enabled():
        team_obj, candidates, err = apif_client.search_national_team(english)
        apif_id = team_obj.get("id") if team_obj else None
        print(f"  api_football_team_id: {apif_id}")
        if err:
            print(f"  api_football_search_error: {err.category}")
        if len(candidates) > 1:
            print(f"  api_football_search_ambiguous: {len(candidates)} candidates")
    else:
        print("  api_football: disabled or key missing")

    if dry_run and not (config.recent_form_api_enabled() or config.api_football_recent_form_enabled()):
        print("  dry_run: no API keys — static-only fusion preview unavailable without --write cache")
        return

    result = build_team_fusion(
        team_key,
        fd_client=fd_client,
        apif_client=apif_client,
        id_map=id_map,
        include_live_apis=not dry_run or (
            config.recent_form_api_enabled() or config.api_football_recent_form_enabled()
        ),
    )
    print(f"  provider_availability: {result.provider_availability}")
    print(f"  provider_candidate_counts: {result.provider_candidate_counts}")
    print(f"  candidate_count: {result.candidate_count}")
    print(f"  deduped_count: {result.coverage_count}")
    print(f"  last_10_count: {len(result.last_10_finished)}")
    print(f"  last_15_available: {result.last_15_available}")
    print(f"  source_mix: {result.source_mix}")
    print(f"  latest_match_date: {result.latest_match_date}")
    print(f"  oldest_match_date: {result.oldest_match_date}")
    print(f"  freshness_gap_days: {result.freshness_gap_days}")
    print(f"  coverage_quality: {result.coverage_quality}")
    if result.coverage_warnings:
        print(f"  warnings: {', '.join(result.coverage_warnings)}")
    if result.fetch_errors:
        print(f"  fetch_errors: {', '.join(result.fetch_errors)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4R.3 recent-form fusion diagnostic",
        epilog='PowerShell: --teams "Brazil,New Zealand,Haiti" (quote comma lists with spaces)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--teams", type=str, default=",".join(DEFAULT_TEAMS))
    parser.add_argument("--team", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true", help="No cache write; may still call APIs if keys set")
    parser.add_argument("--sleep", type=float, default=None, help="Override API-Football sleep seconds")
    args = parser.parse_args()

    names = parse_cli_team_names(args.teams or None, args.team)
    if not names:
        names = list(DEFAULT_TEAMS)
    keys = resolve_cli_team_registry_keys(names)

    fd_client = FootballDataClient() if config.recent_form_api_enabled() else None
    apif_client = None
    if config.api_football_recent_form_enabled():
        apif_client = ApiFootballRecentFormClient(sleep_seconds=args.sleep)

    id_map: dict[str, int] = {}
    if fd_client and config.recent_form_api_enabled():
        id_map, _, _ = discover_football_data_team_ids(fd_client)

    print("Phase 4R.3 recent-form fusion diagnostic")
    print(f"  football_data_enabled: {config.recent_form_api_enabled()}")
    print(f"  api_football_enabled: {config.api_football_recent_form_enabled()}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  teams: {', '.join(names)}")

    for team_key in keys:
        _print_team_report(
            team_key,
            dry_run=args.dry_run,
            id_map=id_map,
            fd_client=fd_client,
            apif_client=apif_client,
        )


if __name__ == "__main__":
    main()
