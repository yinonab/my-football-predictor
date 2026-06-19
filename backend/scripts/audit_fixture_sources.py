"""Phase 4X — Fixture source regression audit (uses env providers; no token output)."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.fixture_state_resolver import FixtureStateResolver
from core.match_context_diagnostics import build_match_context_diagnostics
from core.venue_advantage import resolve_venue_advantage
from data.api_football import ApiFootballClient
from data.football_data import FootballDataClient

REPORTS = BACKEND / "reports"

REGRESSION_MATCHUPS: list[tuple[str, str]] = [
    ("Canada", "Qatar"),
    ("Mexico", "South Korea"),
    ("USA", "Australia"),
    ("Switzerland", "Canada"),
    ("Bosnia and Herzegovina", "Qatar"),
    ("Germany", "Ivory Coast"),
    ("Brazil", "Haiti"),
]


def _actual_score_label(diag: dict) -> str:
    score = diag.get("actual_score")
    if not score:
        return ""
    return f"{score.get('home')}-{score.get('away')}"


def run_audit() -> list[dict[str, str]]:
    resolver = FixtureStateResolver(ApiFootballClient(), football_data=FootballDataClient())
    rows: list[dict[str, str]] = []
    for home, away in REGRESSION_MATCHUPS:
        state = resolver.resolve(home, away)
        venue_adv = resolve_venue_advantage(
            home_team=state.home_team,
            away_team=state.away_team,
            fixture_state=state,
            venue_mode=None,
            neutral_ground=True,
            request_home_advantage=0.0,
            request_venue_city=None,
            request_altitude=0,
        )
        diag = build_match_context_diagnostics(
            fixture_state=state,
            neutral_ground_requested=True,
            venue_advantage=venue_adv,
            request_venue_city=None,
            request_altitude=0,
        ).to_dict()
        rows.append(
            {
                "home_team": home,
                "away_team": away,
                "source": str(diag.get("fixture_source", "")),
                "fixture_status": str(diag.get("fixture_status", "")),
                "kickoff_time_utc": str(diag.get("kickoff_time_utc") or ""),
                "actual_score": _actual_score_label(diag),
                "prediction_valid": str(diag.get("prediction_valid", "")),
                "prediction_mode": str(diag.get("prediction_mode", "")),
                "warnings": "|".join(diag.get("warnings") or []),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Fixture sources audit (Phase 4X)",
        "",
        f"Generated: {ts}",
        "",
        "| Match | Source | Status | Kickoff (UTC) | Score | prediction_valid | Warnings |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        match = f"{row['home_team']} vs {row['away_team']}"
        lines.append(
            f"| {match} | {row['source']} | {row['fixture_status']} | "
            f"{row['kickoff_time_utc']} | {row['actual_score']} | "
            f"{row['prediction_valid']} | {row['warnings']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit fixture resolution sources")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=REPORTS / "fixture_sources_audit.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=REPORTS / "fixture_sources_audit.csv",
    )
    args = parser.parse_args()

    fd = FootballDataClient()
    print(f"football-data enabled={fd.enabled} key_present={fd.key_present}")

    rows = run_audit()
    write_markdown(args.markdown, rows)
    write_csv(args.csv, rows)
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.csv}")

    for row in rows:
        print(
            f"{row['home_team']} vs {row['away_team']}: "
            f"source={row['source']} status={row['fixture_status']} "
            f"score={row['actual_score'] or '-'} valid={row['prediction_valid']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
