"""Phase 4Q — Scoreline realism audit (offline; no API keys required)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from api import main as api_main

REPORTS = BACKEND / "reports"

AUDIT_CASES: list[tuple[str, str, str]] = [
    ("Switzerland", "Canada", "neutral"),
    ("Tunisia", "Japan", "neutral"),
    ("Netherlands", "Sweden", "neutral"),
    ("Brazil", "Haiti", "neutral"),
    ("United States", "Australia", "neutral"),
    ("United States", "Australia", "first_team_home"),
    ("United States", "Australia", "second_team_home"),
    ("Germany", "Haiti", "neutral"),
    ("Germany", "Haiti", "first_team_home"),
]


def _predict(
    client: TestClient, home: str, away: str, *, venue_mode: str
) -> dict:
    body: dict = {
        "home_team": home,
        "away_team": away,
        "venue_mode": venue_mode,
        "neutral_ground": venue_mode == "neutral",
    }
    resp = client.post("/api/predict", json=body)
    resp.raise_for_status()
    return resp.json()


def _score_label(row: dict | None) -> str:
    if not row:
        return ""
    return f"{row['home_goals']}-{row['away_goals']}"


def _top_matrix_scores(data: dict, limit: int = 15) -> str:
    sd = data.get("scoreline_decision") or {}
    groups = sd.get("score_groups") or {}
    all_candidates: list[tuple[str, float]] = []
    for outcome in ("home_win", "draw", "away_win"):
        for item in groups.get(outcome, []):
            label = f"{item['home_goals']}-{item['away_goals']}"
            all_candidates.append((label, float(item["probability"])))
    if not all_candidates:
        for item in data.get("top_scores") or []:
            all_candidates.append((item["score"], float(item["probability"])))
    seen: set[str] = set()
    ordered: list[tuple[str, float]] = []
    for label, prob in sorted(all_candidates, key=lambda x: x[1], reverse=True):
        if label in seen:
            continue
        seen.add(label)
        ordered.append((label, prob))
    return "|".join(f"{s}({p:.1f}%)" for s, p in ordered[:limit])


def _favorite_top_scores(sd: dict) -> str:
    rows = sd.get("favorite_outcome_top_scores") or []
    return "|".join(_score_label(r) for r in rows)


def _realism_warnings(sd: dict) -> str:
    codes = list(sd.get("primary_score_warnings") or [])
    codes.extend(sd.get("warnings") or [])
    return "|".join(dict.fromkeys(codes))


def run_audit() -> list[dict[str, str]]:
    client = TestClient(api_main.app)
    rows: list[dict[str, str]] = []

    for home, away, venue_mode in AUDIT_CASES:
        data = _predict(client, home, away, venue_mode=venue_mode)
        sd = data["scoreline_decision"]
        probs = data["probabilities_1x2"]
        mcd = data.get("match_context_diagnostics") or {}
        bands = sd.get("favorite_goal_band_probabilities") or {}

        primary = sd.get("primary_predicted_score")
        top_exact = sd.get("top_exact_score_overall")

        rows.append(
            {
                "match": f"{home} vs {away}",
                "venue_mode": venue_mode,
                "home_win_pct": str(probs["home_win"]),
                "draw_pct": str(probs["draw"]),
                "away_win_pct": str(probs["away_win"]),
                "home_xg": str(data["home_xg"]),
                "away_xg": str(data["away_xg"]),
                "home_power": str(data["home_power"]),
                "away_power": str(data["away_power"]),
                "power_gap": str(round(data["home_power"] - data["away_power"], 2)),
                "top_exact_score_overall": _score_label(top_exact),
                "primary_predicted_score": _score_label(primary),
                "favorite_outcome": sd["favorite_outcome"],
                "favorite_outcome_top_scores": _favorite_top_scores(sd),
                "top_15_matrix_hint": _top_matrix_scores(data, 15),
                "btts_probability": str(sd.get("both_teams_score_probability", "")),
                "underdog_scores_probability": str(
                    sd.get("underdog_scores_probability", "")
                ),
                "favorite_2_plus": str(bands.get("favorite_2_plus", "")),
                "favorite_3_plus": str(bands.get("favorite_3_plus", "")),
                "favorite_4_plus": str(bands.get("favorite_4_plus", "")),
                "selection_rationale": sd.get("selection_rationale") or "",
                "primary_score_reason": sd.get("primary_score_reason") or "",
                "realism_warnings": _realism_warnings(sd),
                "representative_method": sd.get("representative_score_method") or "",
                "primary_candidates": json.dumps(
                    sd.get("primary_score_candidates") or [], ensure_ascii=False
                ),
                "host_advantage_applied": str(mcd.get("host_advantage_applied", "")),
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
        "# Scoreline Realism Audit (Phase 4Q)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Offline audit via FastAPI TestClient — no live API keys required.",
        "",
        "## Summary",
        "",
        "| Match | Venue | H/D/A | xG | Primary | Top exact | BTTS | Underdog≥1 | Fav 2+ | Warnings |",
        "|-------|-------|-------|-----|---------|-----------|------|------------|--------|----------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['match']} | {row['venue_mode']} "
            f"| {row['home_win_pct']}/{row['draw_pct']}/{row['away_win_pct']} "
            f"| {row['home_xg']}-{row['away_xg']} "
            f"| **{row['primary_predicted_score']}** "
            f"| {row['top_exact_score_overall']} "
            f"| {row['btts_probability']} "
            f"| {row['underdog_scores_probability']} "
            f"| {row['favorite_2_plus']} "
            f"| {row['realism_warnings'] or '-'} |"
        )

    lines.extend(["", "## Details", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row['match']} ({row['venue_mode']})",
                "",
                f"- Powers: {row['home_power']} vs {row['away_power']} (gap {row['power_gap']})",
                f"- Favorite pool top: {row['favorite_outcome_top_scores']}",
                f"- Goal bands: 2+={row['favorite_2_plus']}%, 3+={row['favorite_3_plus']}%, "
                f"4+={row['favorite_4_plus']}%",
                f"- Selection: {row['selection_rationale'] or '_n/a_'}",
                f"- Reason: {row['primary_score_reason']}",
                f"- Candidates: `{row['primary_candidates']}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4Q scoreline realism audit")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=REPORTS / "scoreline_realism_audit.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=REPORTS / "scoreline_realism_audit.csv",
    )
    args = parser.parse_args()
    rows = run_audit()
    write_markdown(args.markdown, rows)
    write_csv(args.csv, rows)
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.csv}")
    print(f"Rows: {len(rows)}")
    for row in rows:
        print(
            f"  {row['match']} [{row['venue_mode']}]: "
            f"primary={row['primary_predicted_score']} "
            f"top_exact={row['top_exact_score_overall']} "
            f"xG={row['home_xg']}-{row['away_xg']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
