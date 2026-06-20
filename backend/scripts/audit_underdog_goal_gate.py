"""Phase 4Q.1 — Underdog goal gate audit (offline; no API keys)."""

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
from core.math_engine import AdvancedDixonColesEngine
from core.scoreline_decision import build_scoreline_decision

REPORTS = BACKEND / "reports"

AUDIT_CASES: list[tuple[str, str, str]] = [
    ("Brazil", "Haiti", "neutral"),
    ("Brazil", "Haiti", "first_team_home"),
    ("Netherlands", "Sweden", "neutral"),
    ("Tunisia", "Japan", "neutral"),
    ("Switzerland", "Canada", "neutral"),
    ("United States", "Australia", "neutral"),
    ("United States", "Australia", "first_team_home"),
    ("United States", "Australia", "second_team_home"),
    ("Germany", "Haiti", "neutral"),
    ("Germany", "Haiti", "first_team_home"),
]

SYNTHETIC_CASES: list[tuple[str, float, float, dict[str, float]]] = [
    (
        "synthetic_elite_blowout",
        4.4,
        0.9,
        {"home_win": 78.6, "draw": 12.1, "away_win": 9.3},
    ),
    (
        "synthetic_low_xg_underdog",
        1.9,
        0.45,
        {"home_win": 62.0, "draw": 24.0, "away_win": 14.0},
    ),
    (
        "synthetic_balanced",
        1.25,
        1.15,
        {"home_win": 38.0, "draw": 32.0, "away_win": 30.0},
    ),
]


def _predict(client: TestClient, home: str, away: str, *, venue_mode: str) -> dict:
    body = {
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


def _synthetic_row(name: str, home_xg: float, away_xg: float, probs: dict[str, float]) -> dict[str, str]:
    engine = AdvancedDixonColesEngine(alpha=0.3)
    result = engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=result["top_scores"],
        all_scores=result["all_scores"],
        home_xg=home_xg,
        away_xg=away_xg,
        home_team="Favorite",
        away_team="Underdog",
    )
    sd = decision.to_dict()
    gate = sd.get("underdog_goal_gate") or {}
    cmp_ = sd.get("candidate_comparison_summary") or {}
    return {
        "match": name,
        "venue_mode": "synthetic",
        "home_xg": str(home_xg),
        "away_xg": str(away_xg),
        "primary_predicted_score": _score_label(sd.get("primary_predicted_score")),
        "top_exact_score_overall": _score_label(sd.get("top_exact_score_overall")),
        "gate_level": gate.get("level", ""),
        "support_score": str(gate.get("support_score", "")),
        "threshold": str(gate.get("threshold", "")),
        "favorite_class": gate.get("favorite_class", ""),
        "underdog_scores_probability": str(gate.get("underdog_scores_probability", "")),
        "btts_probability": str(gate.get("both_teams_score_probability", "")),
        "recent_form_available": str(gate.get("recent_form_available", "")),
        "last_10_scored_rate": str(gate.get("last_10_scored_rate", "")),
        "best_clean_sheet": cmp_.get("best_clean_sheet_candidate", ""),
        "best_underdog_goal": cmp_.get("best_underdog_goal_candidate", ""),
        "prob_gap": str(cmp_.get("exact_probability_gap", "")),
        "rep_gap": str(cmp_.get("representative_score_gap", "")),
        "reason_codes": "|".join(gate.get("reason_codes") or []),
        "selection_rationale": sd.get("selection_rationale", ""),
    }


def run_audit() -> list[dict[str, str]]:
    client = TestClient(api_main.app)
    rows: list[dict[str, str]] = []

    for home, away, venue_mode in AUDIT_CASES:
        data = _predict(client, home, away, venue_mode=venue_mode)
        sd = data["scoreline_decision"]
        gate = sd.get("underdog_goal_gate") or {}
        cmp_ = sd.get("candidate_comparison_summary") or {}
        rows.append(
            {
                "match": f"{home} vs {away}",
                "venue_mode": venue_mode,
                "home_xg": str(data["home_xg"]),
                "away_xg": str(data["away_xg"]),
                "home_power": str(data["home_power"]),
                "away_power": str(data["away_power"]),
                "home_win_pct": str(data["probabilities_1x2"]["home_win"]),
                "primary_predicted_score": _score_label(sd.get("primary_predicted_score")),
                "top_exact_score_overall": _score_label(sd.get("top_exact_score_overall")),
                "gate_level": gate.get("level", ""),
                "support_score": str(gate.get("support_score", "")),
                "threshold": str(gate.get("threshold", "")),
                "favorite_class": gate.get("favorite_class", ""),
                "underdog_scores_probability": str(gate.get("underdog_scores_probability", "")),
                "btts_probability": str(gate.get("both_teams_score_probability", "")),
                "recent_form_available": str(gate.get("recent_form_available", "")),
                "last_10_scored_rate": str(gate.get("last_10_scored_rate", "")),
                "best_clean_sheet": cmp_.get("best_clean_sheet_candidate", ""),
                "best_underdog_goal": cmp_.get("best_underdog_goal_candidate", ""),
                "prob_gap": str(cmp_.get("exact_probability_gap", "")),
                "rep_gap": str(cmp_.get("representative_score_gap", "")),
                "reason_codes": "|".join(gate.get("reason_codes") or []),
                "selection_rationale": sd.get("selection_rationale", ""),
            }
        )

    for name, hxg, axg, probs in SYNTHETIC_CASES:
        rows.append(_synthetic_row(name, hxg, axg, probs))

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
        "# Underdog Goal Gate Audit (Phase 4Q.1)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Match | Venue | xG | Primary | Gate | Support | Clean | Dog | Gap |",
        "|-------|-------|-----|---------|------|---------|-------|-----|-----|",
    ]
    for row in rows:
        lines.append(
            f"| {row['match']} | {row['venue_mode']} | {row.get('home_xg', '')}-{row.get('away_xg', '')} "
            f"| **{row['primary_predicted_score']}** | {row['gate_level']} "
            f"| {row['support_score']}/{row['threshold']} | {row['best_clean_sheet']} "
            f"| {row['best_underdog_goal']} | {row['prob_gap']} |"
        )
    lines.extend(["", "## Details", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row['match']} ({row['venue_mode']})",
                "",
                f"- Class: {row['favorite_class']}, BTTS={row['btts_probability']}%, "
                f"underdog≥1={row['underdog_scores_probability']}%",
                f"- Form: available={row['recent_form_available']}, "
                f"scored_rate={row['last_10_scored_rate']}",
                f"- {row['selection_rationale']}",
                f"- Reasons: {row['reason_codes'] or '-'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4Q.1 underdog goal gate audit")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=REPORTS / "underdog_goal_gate_audit.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=REPORTS / "underdog_goal_gate_audit.csv",
    )
    args = parser.parse_args()
    rows = run_audit()
    write_markdown(args.markdown, rows)
    write_csv(args.csv, rows)
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.csv}")
    for row in rows:
        print(
            f"  {row['match']} [{row['venue_mode']}]: primary={row['primary_predicted_score']} "
            f"gate={row['gate_level']} gap={row['prob_gap']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
