"""Phase 4M — Scoreline decision regression audit (offline; no API-Football required)."""

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

REGRESSION_MATCHUPS: list[tuple[str, str, bool]] = [
    ("Canada", "Qatar", True),
    ("Qatar", "Canada", True),
    ("Germany", "Haiti", True),
    ("Brazil", "Morocco", True),
    ("Argentina", "France", True),
    ("Portugal", "DR Congo", True),
    ("Mexico", "South Korea", True),
]


def _predict(client: TestClient, home: str, away: str, *, neutral: bool) -> dict:
    resp = client.post(
        "/api/predict",
        json={"home_team": home, "away_team": away, "neutral_ground": neutral},
    )
    resp.raise_for_status()
    return resp.json()


def _score_label(row: dict | None) -> str:
    if not row:
        return ""
    return f"{row['home_goals']}-{row['away_goals']}"


def run_audit() -> list[dict[str, str]]:
    client = TestClient(api_main.app)
    rows: list[dict[str, str]] = []
    for home, away, neutral in REGRESSION_MATCHUPS:
        data = _predict(client, home, away, neutral=neutral)
        sd = data["scoreline_decision"]
        top = sd["top_exact_score_overall"]
        primary = sd["primary_predicted_score"]
        rows.append(
            {
                "match": f"{home} vs {away}",
                "neutral_ground": str(neutral),
                "favorite_1x2": sd["favorite_outcome"],
                "favorite_probability": str(sd["favorite_outcome_probability"]),
                "top_exact_score_overall": _score_label(top),
                "top_exact_outcome": top["outcome"] if top else "",
                "primary_predicted_score": _score_label(primary),
                "primary_outcome": primary["outcome"] if primary else "",
                "differs": "yes" if sd["top_exact_score_differs_from_primary"] else "no",
                "confidence_label": sd["confidence_label"],
                "warnings": "|".join(sd.get("warnings") or []),
                "primary_score_reason": sd.get("primary_score_reason") or "",
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
    lines = [
        "# Scoreline Decision Audit (Phase 4M)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Offline audit via FastAPI TestClient — no live API-Football required.",
        "",
        "| Match | Favorite 1X2 | Top exact | Primary | Differs | Confidence | Warnings |",
        "|-------|--------------|-----------|---------|---------|------------|----------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['match']} | {row['favorite_1x2']} ({row['favorite_probability']}%) "
            f"| {row['top_exact_score_overall']} ({row['top_exact_outcome']}) "
            f"| {row['primary_predicted_score']} ({row['primary_outcome']}) "
            f"| {row['differs']} | {row['confidence_label']} | {row['warnings'] or '-'} |"
        )
    lines.extend(["", "## Reasons", ""])
    for row in rows:
        lines.append(f"### {row['match']}")
        lines.append(row["primary_score_reason"] or "_no reason_")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4M scoreline decision audit")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=REPORTS / "scoreline_decision_audit.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=REPORTS / "scoreline_decision_audit.csv",
    )
    args = parser.parse_args()
    rows = run_audit()
    write_markdown(args.markdown, rows)
    write_csv(args.csv, rows)
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.csv}")
    print(f"Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
