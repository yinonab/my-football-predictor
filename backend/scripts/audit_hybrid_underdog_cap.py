"""Read-only audit: four-level underdog xG cap validation."""

from __future__ import annotations

import os

# Production-parity baseline: ignore local elo_overrides.json (must precede api import).
os.environ.setdefault("AUDIT_ELO_BASELINE", "production")

import argparse
import json
import math
import subprocess
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
    ("weak", "England", "DR Congo"),
    ("medium_underdog", "France", "Curaçao"),
    ("medium_underdog", "France", "Paraguay"),
    ("reference", "Brazil", "Japan"),
    ("strong_underdog", "France", "Croatia"),
    ("strong_underdog", "Spain", "Portugal"),
    ("strong_underdog", "Belgium", "Senegal"),
    ("strong_underdog", "Spain", "Austria"),
    ("strong_underdog", "Portugal", "Croatia"),
    ("competitive", "Netherlands", "Morocco"),
    ("competitive", "Switzerland", "Algeria"),
    ("competitive", "USA", "Iran"),
    ("competitive", "Mexico", "Canada"),
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


def _score_label(row: dict | None) -> str:
    if not row:
        return ""
    return f"{row['home_goals']}-{row['away_goals']}"


def _underdog_side(data: dict) -> str:
    hp, ap = float(data["home_power"]), float(data["away_power"])
    return "away" if hp >= ap else "home"


def extract_row(group: str, home: str, away: str, data: dict) -> dict[str, Any]:
    sd = data.get("scoreline_decision") or {}
    probs = data["probabilities_1x2"]
    md = data.get("model_diagnostics") or {}
    cap = md.get("active_model_weak_underdog_cap") or {}
    ud = _underdog_side(data)
    fav_xg = float(data["home_xg"] if ud == "away" else data["away_xg"])
    ud_xg = float(data["away_xg"] if ud == "away" else data["home_xg"])
    primary = sd.get("primary_predicted_score")
    modal = sd.get("top_exact_score_overall")
    return {
        "group": group,
        "fixture": f"{home} vs {away}",
        "tier": cap.get("active_model_weak_underdog_tier"),
        "attack_used": cap.get("active_model_weak_underdog_attack_used"),
        "raw_attack": cap.get("active_model_weak_underdog_raw_attack"),
        "history_attack": cap.get("active_model_weak_underdog_history_attack"),
        "attack_source": cap.get("active_model_weak_underdog_attack_source"),
        "attack_source_conflict": cap.get("active_model_weak_underdog_attack_source_conflict"),
        "gf_ga_fallback": cap.get("active_model_weak_underdog_gf_ga_fallback_used"),
        "power_gap": cap.get("active_model_power_gap"),
        "favorite_defense": cap.get("active_model_favorite_defense_used"),
        "cap_applied": cap.get("active_model_weak_underdog_cap_applied"),
        "cap_reason": cap.get("active_model_weak_underdog_cap_reason"),
        "cap_band_min": cap.get("active_model_weak_underdog_cap_band_min"),
        "cap_band_max": cap.get("active_model_weak_underdog_cap_band_max"),
        "cap_value": cap.get("active_model_weak_underdog_cap_value"),
        "underdog_xg_before_cap": cap.get("active_model_weak_underdog_cap_original_xg"),
        "favorite_xg": fav_xg,
        "underdog_xg": ud_xg,
        "total_xg": round(fav_xg + ud_xg, 2),
        "home_win_pct": probs["home_win"],
        "draw_pct": probs["draw"],
        "away_win_pct": probs["away_win"],
        "underdog_p_scores": sd.get("underdog_scores_probability"),
        "btts_pct": sd.get("both_teams_score_probability"),
        "primary_score": _score_label(primary),
        "modal_score": _score_label(modal),
        "top_5_scores": [
            {"score": t["score"], "probability": t["probability"]}
            for t in (data.get("top_scores") or [])[:5]
        ],
    }


def run_audit() -> list[dict[str, Any]]:
    client = TestClient(api_main.app)
    rows = []
    for group, home, away in FIXTURES:
        resp = client.post("/api/predict", json={**BASELINE, "home_team": home, "away_team": away})
        resp.raise_for_status()
        rows.append(extract_row(group, home, away, resp.json()))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BACKEND.parent, text=True).strip()
    rows = run_audit()
    out = args.json_out or REPORTS / f"four_level_cap_audit_{commit[:8]}.json"
    payload = {"commit": commit, "generated_at": datetime.now(timezone.utc).isoformat(), "fixtures": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    for r in rows:
        print(
            f"{r['fixture']:32} tier={r['tier']} atk={r['attack_used']} "
            f"ud={r['underdog_xg']} P={r['underdog_p_scores']}% "
            f"primary={r['primary_score']} cap={r['cap_applied']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
