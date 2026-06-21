"""Phase 4R.2 — football-data.org recent-form capability diagnostic (live key optional)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.football_data_recent_form import (  # noqa: E402
    FD_DEFAULT_ROLLING_WINDOWS,
    RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT,
    RECENT_FORM_API_UNDATED_FALLBACK_USED,
    RECENT_FORM_RATE_LIMIT_STOP,
    build_safe_date_window,
    classify_client_error,
    discover_football_data_team_ids,
    error_detail_from_client,
    fetch_team_recent_matches,
    format_error_detail,
    investigate_bosnia_discovery,
    is_rate_limited_category,
    parse_cli_team_names,
    print_discovery_diagnostics,
    probe_team_match_endpoint_variants,
    refresh_enabled,
    safe_error_message,
    team_fetch_status_for_result,
)
from data.database import FIFA_ELO_2026  # noqa: E402
from data.football_data import FootballDataClient, KEY_MISSING  # noqa: E402
from data.nt_match import registry_key_for_nt  # noqa: E402

DEFAULT_SAMPLE_TEAMS = ("Brazil", "New Zealand")


def _resolve_registry(name: str) -> str | None:
    return registry_key_for_nt(name, set(FIFA_ELO_2026.keys()))


def _print_error_block(client: FootballDataClient, *, verbose: bool) -> None:
    detail = error_detail_from_client(client)
    if detail is None:
        return
    print(f"    {format_error_detail(detail, verbose=verbose)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Low-volume football-data.org recent-form diagnostic",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show endpoint paths, HTTP status, params, and likely cause (secrets redacted)",
    )
    parser.add_argument(
        "--probe-variants",
        action="store_true",
        help="Run endpoint variant probes (extra API calls; off by default)",
    )
    parser.add_argument(
        "--sample-teams",
        type=str,
        default="Brazil,New Zealand",
        help='Comma-separated teams for match fetch sample (default: "Brazil,New Zealand")',
    )
    parser.add_argument(
        "--max-sample-teams",
        type=int,
        default=2,
        help="Max teams to fetch in sample match section (default: 2)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds between sample team fetches (default: 1.0)",
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
        help="Use 2 dated windows per team (--max-windows 2)",
    )
    args = parser.parse_args()

    max_windows = 2 if args.deep_history else max(1, args.max_windows)

    if not refresh_enabled():
        print("FOOTBALL_DATA_API_KEY not set or RECENT_FORM_API_ENABLED=false.")
        print("Set FOOTBALL_DATA_API_KEY in backend/.env locally to run this diagnostic.")
        print("No cache written; tests do not require this script.")
        return 0

    client = FootballDataClient()
    if not client.is_available:
        print(f"Client unavailable: {classify_client_error(client.last_error_code)}")
        return 1

    print("football-data.org recent-form diagnostic (low-volume mode)")
    print(f"base_url: {client.base_url}")
    print(f"key_present: {client.key_present}")
    print(f"sample_teams={args.sample_teams!r} max_sample={args.max_sample_teams} max_windows={max_windows}")

    id_map, missing, meta = discover_football_data_team_ids(client)
    print(f"\nTeam ID discovery: {meta.get('discovered_count')} / {len(FIFA_ELO_2026)}")
    print(f"sources: {', '.join(meta.get('sources_used') or [])}")
    if meta.get("warnings"):
        print(f"warnings: {meta['warnings']}")
    print("Discovery diagnostics:")
    print_discovery_diagnostics(meta, verbose=args.verbose)

    if meta.get("rate_limit_stop"):
        print("\nRate limited during discovery — skipping match fetches.")
        wait = meta.get("rate_limit_wait_seconds")
        if wait:
            print(f"Recommended wait before retry: {wait}s")
        return 1

    sample_names = parse_cli_team_names(args.sample_teams, [])[: max(0, args.max_sample_teams)]
    print("\nDiscovered IDs (sample list):")
    for name in sample_names:
        key = _resolve_registry(name)
        if not key:
            print(f"  {name}: registry unresolved")
            continue
        tid = id_map.get(key)
        print(f"  {name}: id={tid or 'MISSING'}")

    if args.verbose:
        bosnia_key = _resolve_registry("Bosnia")
        print("\nBosnia (from discovery map only):")
        print(f"  registry_key: {bosnia_key}")
        print(f"  discovered_id: {id_map.get(bosnia_key) if bosnia_key else None}")

    print("\nSample match fetch (recent dated window; stops on first 429):")
    recent_from, recent_to = build_safe_date_window()
    print(f"  expected first dated window: {recent_from} → {recent_to}")

    rate_limited = False
    for name in sample_names:
        if rate_limited:
            print(f"  {name}: skipped ({RECENT_FORM_RATE_LIMIT_STOP})")
            continue
        key = _resolve_registry(name)
        if not key:
            continue
        team_id = id_map.get(key)
        if not team_id:
            print(f"  {name}: skip — no football-data team id")
            continue
        try:
            result = fetch_team_recent_matches(
                client,
                team_registry_key=key,
                football_data_team_id=team_id,
                sleep_seconds=args.sleep,
                max_windows=max_windows,
            )
            status = team_fetch_status_for_result(result)
            if not result.rows and result.error_category:
                print(
                    f"  {name}: error={result.error_category} matches=0 window={result.window_index}"
                )
                _print_error_block(client, verbose=args.verbose)
                if result.rate_limit_wait_seconds is not None:
                    print(f"    recommended wait: {result.rate_limit_wait_seconds}s")
                if is_rate_limited_category(result.error_category):
                    rate_limited = True
            else:
                latest = result.rows[0].date if result.rows else "-"
                print(
                    f"  {name}: status={status} matches={len(result.rows)} latest={latest} "
                    f"strategy={result.fetch_strategy} window={result.window_index}"
                )
                if result.reason_codes:
                    print(f"    reason_codes={result.reason_codes}")
                if result.partial_success and RECENT_FORM_API_PARTIAL_DUE_RATE_LIMIT in result.reason_codes:
                    rate_limited = True
                    if result.rate_limit_wait_seconds:
                        print(f"    recommended wait: {result.rate_limit_wait_seconds}s")
        except Exception as exc:
            print(f"  {name}: error={safe_error_message(exc)}")

    if args.probe_variants and not rate_limited:
        print("\nEndpoint variant probe (explicit --probe-variants; stops on 429):")
        for name in sample_names[:1]:
            key = _resolve_registry(name)
            if not key:
                continue
            team_id = id_map.get(key)
            if not team_id:
                continue
            results = probe_team_match_endpoint_variants(
                client,
                team_id=team_id,
                team_label=name,
                stop_on_rate_limit=True,
            )
            for row in results:
                if row.get("ok"):
                    print(
                        f"  {name} [{row['variant']}]: status={row.get('http_status')} "
                        f"matches={row.get('match_count')}"
                    )
                else:
                    print(
                        f"  {name} [{row['variant']}]: category={row.get('category')} "
                        f"status={row.get('http_status')} likely={row.get('likely_cause')}"
                    )
                    if row.get("rate_limit_wait_seconds") is not None:
                        print(f"    wait_seconds={row.get('rate_limit_wait_seconds')}")
                if not row.get("ok") and is_rate_limited_category(row.get("category")):
                    print(f"  {name}: variant probes stopped due to rate limit")
                    break
    elif args.probe_variants:
        print("\nEndpoint variant probe skipped (rate limit already encountered).")

    print("\nDone (no cache written).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
