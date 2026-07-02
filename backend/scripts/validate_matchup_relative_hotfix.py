"""Validation fixtures for matchup relative consistency hotfix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

BASE = {
    "neutral_ground": True,
    "include_diagnostics": True,
    "fusion_blowout_enabled": False,
    "odds_affect_prediction": False,
    "use_match_context": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
    "rho": -0.15,
    "alpha": 0.0,
    "top_n": 10,
}

FIXTURES = [
    ("Switzerland", "Algeria"),
    ("Portugal", "Croatia"),
    ("France", "Haiti"),
    ("France", "Curaçao"),
    ("France", "Croatia"),
    ("Spain", "Austria"),
    ("Belgium", "Senegal"),
    ("Brazil", "Japan"),
    ("Netherlands", "Morocco"),
]


def _top_bucket(probs: dict) -> str:
    return max(("home_win", "draw", "away_win"), key=lambda k: float(probs[k]))


def _primary_bucket(primary: dict) -> str:
    h, a = int(primary["home_goals"]), int(primary["away_goals"])
    if h > a:
        return "home_win"
    if a > h:
        return "away_win"
    return "draw"


def main() -> None:
    config.NR3_FCC_SERVED_ENABLED = True
    rows: list[dict] = []
    for home, away in FIXTURES:
        for fusion in (False, True):
            for variant in ("nr3_fcc", "matchup_relative_v1"):
                payload = {
                    **BASE,
                    "home_team": home,
                    "away_team": away,
                    "fusion_blowout_enabled": fusion,
                    "xg_model_variant": variant,
                }
                resp = client.post("/api/predict", json=payload)
                if resp.status_code != 200:
                    print(f"FAIL {home} vs {away} {variant} fusion={fusion}: {resp.text}")
                    continue
                data = resp.json()
                probs = data["probabilities_1x2"]
                primary = data["scoreline_decision"]["primary_predicted_score"]
                top_bucket = _top_bucket(probs)
                primary_bucket = _primary_bucket(primary)
                diag = data.get("model_diagnostics") or {}
                mgc = diag.get("matchup_goal_capability") or {}
                ud_p = (mgc.get("probabilities") or {}).get("underdog_scores_probability")
                rows.append(
                    {
                        "fixture": f"{home} vs {away}",
                        "model": variant,
                        "fusion": fusion,
                        "home_xg": data["home_xg"],
                        "away_xg": data["away_xg"],
                        "home_win": probs["home_win"],
                        "draw": probs["draw"],
                        "away_win": probs["away_win"],
                        "top_bucket": top_bucket,
                        "primary_score": f"{primary['home_goals']}-{primary['away_goals']}",
                        "primary_bucket": primary_bucket,
                        "bucket_consistent": top_bucket == primary_bucket
                        or variant == "nr3_fcc",
                        "opponent_p_score": ud_p,
                        "clean_sheet_adjusted": diag.get("clean_sheet_primary_adjusted"),
                        "clean_sheet_warning": diag.get("clean_sheet_primary_warning"),
                        "underdog_capability": mgc.get("underdog_goal_capability"),
                        "notes": ",".join(diag.get("reason_codes") or [])[:80],
                    }
                )

    print(
        "Fixture | Model | Fusion | Home xG | Away xG | 1 | X | 2 | "
        "Top bucket | Primary | Primary bucket | Consistent | Opp P(score) | CS adj/warn | Notes"
    )
    for row in rows:
        cs = "adj" if row["clean_sheet_adjusted"] else ("warn" if row["clean_sheet_warning"] else "-")
        print(
            f"{row['fixture']} | {row['model']} | {row['fusion']} | "
            f"{row['home_xg']:.2f} | {row['away_xg']:.2f} | "
            f"{row['home_win']:.1f} | {row['draw']:.1f} | {row['away_win']:.1f} | "
            f"{row['top_bucket']} | {row['primary_score']} | {row['primary_bucket']} | "
            f"{'yes' if row['bucket_consistent'] else 'NO'} | "
            f"{row['opponent_p_score']} | {cs} | {row['underdog_capability']} | {row['notes']}"
        )

    out = BACKEND_ROOT / "reports" / "matchup_relative_hotfix_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
