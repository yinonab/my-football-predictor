"""Phase 4O — Home advantage / venue mode regression audit (offline)."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from api import main as api_main

REPORTS = BACKEND / "reports"

CASES: list[dict[str, object]] = [
    {"home": "USA", "away": "Australia", "venue_mode": "neutral", "neutral_ground": True},
    {"home": "USA", "away": "Australia", "venue_mode": "first_team_home", "neutral_ground": True},
    {"home": "USA", "away": "Australia", "venue_mode": "second_team_home", "neutral_ground": True},
    {"home": "Canada", "away": "Qatar", "venue_mode": "neutral", "neutral_ground": True},
    {"home": "Canada", "away": "Qatar", "venue_mode": "first_team_home", "neutral_ground": True},
    {"home": "Qatar", "away": "Canada", "venue_mode": "second_team_home", "neutral_ground": True},
    {"home": "Germany", "away": "Haiti", "venue_mode": "neutral", "neutral_ground": True},
    {"home": "Germany", "away": "Haiti", "venue_mode": "first_team_home", "neutral_ground": True},
]


def _predict(client: TestClient, case: dict[str, object]) -> dict:
    payload = {
        "home_team": case["home"],
        "away_team": case["away"],
        "neutral_ground": case["neutral_ground"],
        "venue_mode": case["venue_mode"],
    }
    resp = client.post("/api/predict", json=payload)
    resp.raise_for_status()
    return resp.json()


def _primary_score(data: dict) -> str:
    sd = data.get("scoreline_decision") or {}
    primary = sd.get("primary_predicted_score")
    if not primary:
        return ""
    return f"{primary['home_goals']}-{primary['away_goals']}"


def run_audit() -> list[dict[str, str]]:
    client = TestClient(api_main.app)
    neutral_cache: dict[str, dict] = {}
    rows: list[dict[str, str]] = []

    for case in CASES:
        data = _predict(client, case)
        diag = data["match_context_diagnostics"]
        probs = data["probabilities_1x2"]
        match_key = f"{case['home']} vs {case['away']}"
        if case["venue_mode"] == "neutral":
            neutral_cache[match_key] = data

        neutral = neutral_cache.get(match_key)
        delta_home = ""
        delta_away = ""
        if neutral and case["venue_mode"] != "neutral":
            delta_home = str(
                round(probs["home_win"] - neutral["probabilities_1x2"]["home_win"], 2)
            )
            delta_away = str(
                round(probs["away_win"] - neutral["probabilities_1x2"]["away_win"], 2)
            )

        rows.append(
            {
                "match": match_key,
                "venue_mode": str(case["venue_mode"]),
                "home_advantage_team": str(diag.get("home_advantage_team", "")),
                "home_advantage_applied": str(diag.get("host_advantage_applied", "")),
                "home_advantage_power_delta": str(diag.get("home_advantage_power_delta", "")),
                "home_xg": str(data.get("home_xg", "")),
                "away_xg": str(data.get("away_xg", "")),
                "home_win_pct": str(probs.get("home_win", "")),
                "draw_pct": str(probs.get("draw", "")),
                "away_win_pct": str(probs.get("away_win", "")),
                "primary_score": _primary_score(data),
                "delta_home_win_vs_neutral": delta_home,
                "delta_away_win_vs_neutral": delta_away,
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
        "# Home advantage audit (Phase 4O)",
        "",
        f"Generated: {ts}",
        "",
        "| Match | venue_mode | HA team | applied | Δ power | home_xg | away_xg | "
        "H/D/A % | primary | ΔH vs neutral | ΔA vs neutral | warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['match']} | {row['venue_mode']} | {row['home_advantage_team']} | "
            f"{row['home_advantage_applied']} | {row['home_advantage_power_delta']} | "
            f"{row['home_xg']} | {row['away_xg']} | "
            f"{row['home_win_pct']}/{row['draw_pct']}/{row['away_win_pct']} | "
            f"{row['primary_score']} | {row['delta_home_win_vs_neutral']} | "
            f"{row['delta_away_win_vs_neutral']} | {row['warnings']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit home advantage venue modes")
    parser.add_argument("--markdown", type=Path, default=REPORTS / "home_advantage_audit.md")
    parser.add_argument("--csv", type=Path, default=REPORTS / "home_advantage_audit.csv")
    args = parser.parse_args()

    rows = run_audit()
    write_markdown(args.markdown, rows)
    write_csv(args.csv, rows)
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.csv}")
    for row in rows:
        print(
            f"{row['match']} [{row['venue_mode']}]: "
            f"H={row['home_win_pct']}% dH={row['delta_home_win_vs_neutral'] or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
