"""Read-only audit: hybrid tier weak-underdog cap validation."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("NR3_FCC_SERVED_ENABLED", "true")
os.environ.setdefault("ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED", "true")

from fastapi.testclient import TestClient  # noqa: E402

from api import main as api_main  # noqa: E402

REPORTS = BACKEND / "reports"

FIXTURES: list[tuple[str, str, str]] = [
    ("ultra_weak", "France", "Haiti"),
    ("ultra_weak", "Argentina", "Cape Verde"),
    ("medium_weak", "France", "Curaçao"),
    ("medium_weak", "France", "Paraguay"),
    ("medium_weak", "England", "DR Congo"),
    ("medium_weak", "Brazil", "Japan"),
    ("strong", "France", "Croatia"),
    ("strong", "Spain", "Portugal"),
    ("strong", "Belgium", "Senegal"),
    ("strong", "Spain", "Austria"),
    ("strong", "Portugal", "Croatia"),
]

BASELINE = {
    "neutral_ground": True,
    "include_diagnostics": True,
    "fusion_blowout_enabled": True,
    "odds_affect_prediction": False,
    "use_match_context": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
    "rho": -0.15,
    "alpha": 0.0,
    "top_n": 10,
}


def _poisson_scores_prob(xg: float) -> float:
    return round((1.0 - math.exp(-max(float(xg), 0.0))) * 100.0, 2)


def _underdog_side(data: dict) -> str:
    hp = float(data["home_power"])
    ap = float(data["away_power"])
    return "away" if hp >= ap else "home"


def _extract(home: str, away: str, group: str, data: dict) -> dict[str, Any]:
    sd = data.get("scoreline_decision") or {}
    probs = data["probabilities_1x2"]
    md = data.get("model_diagnostics") or {}
    cap = md.get("active_model_weak_underdog_cap") or {}
    ud = _underdog_side(data)
    if ud == "home":
        fav_xg, ud_xg = float(data["away_xg"]), float(data["home_xg"])
    else:
        fav_xg, ud_xg = float(data["home_xg"]), float(data["away_xg"])
    primary = sd.get("primary_predicted_score")
    primary_s = f"{primary['home_goals']}-{primary['away_goals']}" if primary else ""
    top5 = [
        {"score": t["score"], "probability": t["probability"]}
        for t in (data.get("top_scores") or [])[:5]
    ]
    return {
        "group": group,
        "fixture": f"{home} vs {away}",
        "favorite_xg": fav_xg,
        "underdog_xg": ud_xg,
        "total_xg": round(fav_xg + ud_xg, 2),
        "home_win_pct": probs["home_win"],
        "draw_pct": probs["draw"],
        "away_win_pct": probs["away_win"],
        "underdog_p_scores": _poisson_scores_prob(ud_xg),
        "btts_pct": sd.get("both_teams_score_probability"),
        "primary_score": primary_s,
        "top_5_scores": top5,
        "cap_applied": cap.get("active_model_weak_underdog_cap_applied"),
        "tier": cap.get("active_model_weak_underdog_tier"),
        "cap_value": cap.get("active_model_weak_underdog_cap_value"),
        "cap_delta": cap.get("active_model_weak_underdog_cap_delta"),
        "cap_reason": cap.get("active_model_weak_underdog_cap_reason"),
        "attack_used": cap.get("active_model_weak_underdog_attack_used"),
        "attack_source": cap.get("active_model_weak_underdog_attack_source"),
        "raw_attack": cap.get("active_model_weak_underdog_raw_attack"),
        "history_attack": cap.get("active_model_weak_underdog_history_attack"),
        "favorite_defense_used": cap.get("active_model_favorite_defense_used"),
        "power_gap": cap.get("active_model_power_gap"),
        "gf_ga_fallback": cap.get("active_model_weak_underdog_gf_ga_fallback_used"),
    }


def run_audit() -> list[dict[str, Any]]:
    client = TestClient(api_main.app)
    rows: list[dict[str, Any]] = []
    for group, home, away in FIXTURES:
        body = {**BASELINE, "home_team": home, "away_team": away}
        resp = client.post("/api/predict", json=body)
        resp.raise_for_status()
        rows.append(_extract(home, away, group, resp.json()))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, default=REPORTS / "hybrid_underdog_cap_audit.json")
    args = parser.parse_args()
    rows = run_audit()
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "fixtures": rows}
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    for r in rows:
        print(
            f"{r['fixture']:32} tier={r['tier']} ud_xg={r['underdog_xg']} "
            f"P(sc)={r['underdog_p_scores']}% primary={r['primary_score']} cap={r['cap_applied']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
