"""Phase 4R.2 — Refresh football-data.org recent-form cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from core.football_data_recent_form import (  # noqa: E402
    FD_DEFAULT_ROLLING_WINDOWS,
    RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT,
    RECENT_FORM_API_UNDATED_FALLBACK_USED,
    RECENT_FORM_CACHE_PATH,
    RECENT_FORM_RATE_LIMIT_STOP,
    TEAM_FETCH_STATUS_PARTIAL,
    build_cache_payload,
    classify_client_error,
    discover_football_data_team_ids,
    fetch_team_recent_matches,
    format_error_detail,
    is_rate_limited_category,
    normalized_match_to_cache_dict,
    parse_cli_team_names,
    print_discovery_diagnostics,
    refresh_enabled,
    resolve_cli_team_registry_keys,
    safe_error_message,
    team_fetch_status_for_result,
    team_result_has_usable_rows,
    write_recent_form_cache_safe,
)
from data.database import FIFA_ELO_2026  # noqa: E402
from data.football_data import FootballDataClient, HTTP_429_RATE_LIMITED, KEY_MISSING, RATE_LIMITED  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh recent_form_cache.json from football-data.org",
        epilog=(
            "PowerShell examples:\n"
            '  python scripts\\refresh_recent_form_cache.py --dry-run --team Brazil --team "New Zealand" --sleep 15\n'
            '  python scripts\\refresh_recent_form_cache.py --dry-run --teams "Brazil,Sweden,Haiti,New Zealand" --sleep 10'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write cache")
    parser.add_argument("--write", action="store_true", help="Write cache file (validated, atomic)")
    parser.add_argument(
        "--allow-empty-cache-write",
        action="store_true",
        help="Dangerous: allow writing empty/degraded cache (default refuses)",
    )
    parser.add_argument(
        "--teams",
        type=str,
        metavar="NAMES",
        help='Comma-separated team names; quote in PowerShell: --teams "Brazil,New Zealand"',
    )
    parser.add_argument(
        "--team",
        dest="team_names",
        action="append",
        default=[],
        metavar="NAME",
        help="Single team name (repeatable; same matching as --teams)",
    )
    parser.add_argument("--all", action="store_true", help="Refresh all WC 2026 registry teams")
    parser.add_argument("--max-teams", type=int, default=0, help="Limit team count (0=all requested)")
    parser.add_argument("--force", action="store_true", help="Force refresh even if cache fresh")
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds between team API calls (default: 1.0; use 10-15 under rate limit)",
    )
    parser.add_argument(
        "--max-windows",
        type=int,
        default=FD_DEFAULT_ROLLING_WINDOWS,
        help=f"Dated rolling windows per team (default: {FD_DEFAULT_ROLLING_WINDOWS})",
    )
    parser.add_argument(
        "--deep-history",
        action="store_true",
        help="Fetch a second older 730-day window when first window has fewer than target matches",
    )
    args = parser.parse_args()

    max_windows = 2 if args.deep_history else max(1, args.max_windows)

    if not refresh_enabled():
        print("Recent-form API refresh disabled (missing FOOTBALL_DATA_API_KEY or RECENT_FORM_API_ENABLED=false).")
        return 0

    if not args.teams and not args.all and not args.team_names:
        print('Specify --teams "Name1,Name2" or --team Name1 --team Name2 or --all')
        return 1

    client = FootballDataClient()
    if not client.is_available:
        print(f"football-data client unavailable: {classify_client_error(client.last_error_code)}")
        return 1

    id_map, missing, meta = discover_football_data_team_ids(client)
    print(f"Discovered {len(id_map)} team IDs via {meta.get('sources_used')}")
    if meta.get("warnings"):
        print(f"Discovery warnings: {meta.get('warnings')}")
    print("Discovery diagnostics:")
    print_discovery_diagnostics(meta)

    if len(id_map) == 0:
        print("ERROR: team discovery returned 0 IDs — cache write blocked.")
        if args.write and not args.allow_empty_cache_write:
            if RECENT_FORM_CACHE_PATH.exists():
                print(f"Preserving existing cache at {RECENT_FORM_CACHE_PATH}")
            return 1

    if meta.get("rate_limit_stop"):
        wait = meta.get("rate_limit_wait_seconds")
        print("Discovery hit rate limit — skipping team fetches.")
        if wait:
            print(f"Recommended wait before retry: {wait}s (use --sleep {max(wait, 15)})")
        if args.write and not args.allow_empty_cache_write:
            if RECENT_FORM_CACHE_PATH.exists():
                print(f"Preserving existing cache at {RECENT_FORM_CACHE_PATH}")
            return 1
        if args.dry_run and not args.write:
            return 1

    if args.all:
        target_keys = sorted(FIFA_ELO_2026.keys())
    else:
        cli_names = parse_cli_team_names(args.teams, args.team_names)
        target_keys = resolve_cli_team_registry_keys(cli_names)
        print(f"CLI team names ({len(cli_names)}): {cli_names}")
        print(f"Resolved registry keys ({len(target_keys)}): {[k.split(' (')[0] for k in target_keys]}")
    print(f"Fetch settings: max_windows={max_windows} sleep={args.sleep}s")

    if args.max_teams > 0:
        target_keys = target_keys[: args.max_teams]

    if not target_keys:
        print("No teams resolved.")
        return 1

    team_results: dict[str, dict] = {}
    refresh_errors: list[str] = []
    rate_limited = False
    recommended_wait: int | None = meta.get("rate_limit_wait_seconds")

    for registry_key in target_keys:
        english = registry_key.split(" (")[0]
        if rate_limited:
            team_results[registry_key] = {
                "status": "skipped_rate_limit",
                "warnings": [RECENT_FORM_RATE_LIMIT_STOP],
                "reason_codes": [RECENT_FORM_RATE_LIMIT_STOP],
                "matches": [],
            }
            refresh_errors.append(f"{english}:skipped_rate_limit")
            continue

        team_id = id_map.get(registry_key)
        if not team_id:
            team_results[registry_key] = {
                "status": "missing_team_id",
                "warnings": ["FOOTBALL_DATA_TEAM_ID_NOT_FOUND"],
                "matches": [],
            }
            refresh_errors.append(f"{english}:missing_team_id")
            print(f"  {english}: missing football-data team id")
            continue

        try:
            result = fetch_team_recent_matches(
                client,
                team_registry_key=registry_key,
                football_data_team_id=team_id,
                sleep_seconds=args.sleep,
                max_windows=max_windows,
            )
        except Exception as exc:
            team_results[registry_key] = {
                "status": "error",
                "warnings": [safe_error_message(exc)],
                "matches": [],
            }
            refresh_errors.append(f"{english}:{type(exc).__name__}")
            continue

        if not result.rows and result.error_category:
            err_label = result.error_category
            team_results[registry_key] = {
                "status": err_label.lower(),
                "warnings": result.warnings or [err_label],
                "reason_codes": result.reason_codes,
                "matches": [],
                "window_index": result.window_index,
            }
            refresh_errors.append(f"{english}:{err_label}")
            detail = client.last_error_detail
            if detail is not None:
                print(f"  {english}: error={format_error_detail(detail)}")
            else:
                print(f"  {english}: error={err_label} window={result.window_index}")
            if result.rate_limit_wait_seconds is not None:
                recommended_wait = result.rate_limit_wait_seconds
                print(f"    recommended wait: {result.rate_limit_wait_seconds}s")
            if is_rate_limited_category(err_label):
                rate_limited = True
            continue

        if not result.rows:
            team_results[registry_key] = {
                "status": "no_matches",
                "warnings": result.warnings,
                "reason_codes": result.reason_codes,
                "matches": [],
            }
            refresh_errors.append(f"{english}:no_matches")
            print(f"  {english}: no finished matches")
            continue

        status = team_fetch_status_for_result(result)
        confidence = "medium" if RECENT_FORM_API_UNDATED_FALLBACK_USED in result.reason_codes else "high"
        if status == TEAM_FETCH_STATUS_PARTIAL:
            confidence = "medium"
        team_results[registry_key] = {
            "status": status,
            "warnings": result.warnings,
            "reason_codes": result.reason_codes,
            "fetch_strategy": result.fetch_strategy,
            "window_index": result.window_index,
            "source_confidence": confidence,
            "matches": [normalized_match_to_cache_dict(r) for r in result.rows],
        }
        strategy_note = f" strategy={result.fetch_strategy}" if result.fetch_strategy else ""
        window_note = f" window={result.window_index}" if result.window_index is not None else ""
        print(
            f"  {english}: status={status} {len(result.rows)} finished matches "
            f"(id={team_id}{strategy_note}{window_note})"
        )
        if result.reason_codes:
            print(f"    reason_codes={result.reason_codes}")
        if result.partial_success and RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT in result.reason_codes:
            rate_limited = True
            if result.rate_limit_wait_seconds:
                recommended_wait = result.rate_limit_wait_seconds
                print(f"    recommended wait: {result.rate_limit_wait_seconds}s — remaining teams skipped")

    payload = build_cache_payload(
        team_results=team_results,
        id_map=id_map,
        refresh_errors=refresh_errors,
    )
    payload["discovery_meta"] = {
        "sources_used": meta.get("sources_used"),
        "source_diagnostics": meta.get("source_diagnostics"),
    }

    usable = sum(1 for r in team_results.values() if team_result_has_usable_rows(r))
    row_count = sum(len(r.get("matches") or []) for r in team_results.values())

    print(f"\nTeams processed: {len(team_results)}")
    print(f"Teams with usable rows: {usable}")
    print(f"Total match rows: {row_count}")
    print(f"Missing IDs (global): {len(missing)}")
    print(f"Errors: {len(refresh_errors)}")
    if recommended_wait:
        print(f"Recommended sleep for next run: {max(recommended_wait, 15)}s")

    if args.dry_run and not args.write:
        print("Dry-run complete — cache not written.")
        return 0 if usable > 0 else 1

    if args.write:
        path, status = write_recent_form_cache_safe(
            payload,
            id_map=id_map,
            team_results=team_results,
            allow_empty=args.allow_empty_cache_write,
        )
        if path is None:
            print(f"Cache write REFUSED: {status}")
            if RECENT_FORM_CACHE_PATH.exists():
                print(f"Preserving existing cache at {RECENT_FORM_CACHE_PATH}")
            return 1
        print(f"Wrote {path}")
        return 0

    print("Use --write to persist cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
