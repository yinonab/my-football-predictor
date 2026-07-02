"""Validation: NR3 vs matchup_relative_v1 on fixture set."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

logging.disable(logging.CRITICAL)

import config
from api.main import app
from fastapi.testclient import TestClient

config.NR3_FCC_SERVED_ENABLED = True
config.nr3_fcc_served_enabled = lambda: True
config.MODEL_ACTIVATION_ENABLED = True
config.POWER_CANDIDATE_AFFECTS_PREDICTION = True

client = TestClient(app)

FIXTURES = [
    ("France", "Haiti"),
    ("France", "Curaçao"),
    ("France", "Croatia"),
    ("Spain", "Austria"),
    ("Portugal", "Croatia"),
    ("Spain", "Portugal"),
    ("Belgium", "Senegal"),
    ("England", "DR Congo"),
    ("Brazil", "Japan"),
    ("Netherlands", "Morocco"),
]

BASE = {
    "neutral_ground": True,
    "include_diagnostics": True,
    "odds_affect_prediction": False,
    "use_match_context": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
    "rho": -0.15,
    "alpha": 0.0,
    "top_n": 10,
}


def primary_score(data: dict) -> str:
    sld = data.get("scoreline_decision") or {}
    p = sld.get("primary_predicted_score")
    if isinstance(p, dict):
        return f"{p.get('home_goals')}-{p.get('away_goals')}"
    return str(p)


def predict(home: str, away: str, fusion: bool, variant: str) -> dict:
    payload = {
        **BASE,
        "home_team": home,
        "away_team": away,
        "fusion_blowout_enabled": fusion,
        "xg_model_variant": variant,
    }
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def main() -> None:
    print("=== DETAIL TABLE ===")
    print(
        "Fixture | Fusion | Model | Home xG | Away xG | 1 | X | 2 | "
        "Primary | Total xG | Notes"
    )
    for home, away in FIXTURES:
        for fusion in (False, True):
            for variant in ("nr3_fcc", "matchup_relative_v1"):
                d = predict(home, away, fusion, variant)
                p = d["probabilities_1x2"]
                md = d.get("model_diagnostics") or {}
                expected = (
                    "matchup_relative_v1"
                    if variant == "matchup_relative_v1"
                    else "nr3_fcc"
                )
                notes = "ok" if md.get("active_xg_source") == expected else "SRC_MISMATCH"
                if variant == "matchup_relative_v1":
                    rel = md.get("matchup_relative_diagnostics") or {}
                    if fusion and rel.get("fusion_ignored_for_model_variant"):
                        notes += ";fusion_ignored"
                print(
                    f"{home} vs {away} | {fusion} | {variant} | "
                    f"{d['home_xg']} | {d['away_xg']} | "
                    f"{p['home_win']:.1f} | {p['draw']:.1f} | {p['away_win']:.1f} | "
                    f"{primary_score(d)} | {round(d['home_xg'] + d['away_xg'], 2)} | {notes}"
                )

    print()
    print("=== COMPARISON TABLE ===")
    print(
        "Fixture | Fusion | NR3 xG | Matchup xG | dHome | dAway | "
        "NR3 primary | MR primary | Verdict"
    )
    for home, away in FIXTURES:
        for fusion in (False, True):
            nr3 = predict(home, away, fusion, "nr3_fcc")
            mr = predict(home, away, fusion, "matchup_relative_v1")
            dh = round(mr["home_xg"] - nr3["home_xg"], 2)
            da = round(mr["away_xg"] - nr3["away_xg"], 2)
            if away in ("Haiti", "Curaçao") and da < 0:
                verdict = "weak_ud_reduced"
            elif away in ("Haiti", "Curaçao") and da >= 0:
                verdict = "weak_ud_not_reduced"
            else:
                verdict = "plausible_shift"
            print(
                f"{home} vs {away} | {fusion} | "
                f"{nr3['home_xg']}-{nr3['away_xg']} | {mr['home_xg']}-{mr['away_xg']} | "
                f"{dh:+.2f} | {da:+.2f} | {primary_score(nr3)} | {primary_score(mr)} | {verdict}"
            )

    print()
    print("=== NR3 PARITY (missing vs explicit nr3_fcc) ===")
    failures = 0
    for home, away in FIXTURES:
        base = {**BASE, "home_team": home, "away_team": away, "fusion_blowout_enabled": False}
        miss = client.post("/api/predict", json=base).json()
        expl = client.post(
            "/api/predict", json={**base, "xg_model_variant": "nr3_fcc"}
        ).json()
        ok = (
            miss["home_xg"] == expl["home_xg"]
            and miss["away_xg"] == expl["away_xg"]
            and miss["probabilities_1x2"] == expl["probabilities_1x2"]
            and miss["top_scores"] == expl["top_scores"]
            and primary_score(miss) == primary_score(expl)
        )
        if not ok:
            failures += 1
            print("FAIL", home, away)
    print("ALL_PARITY_OK" if failures == 0 else f"PARITY_FAILED count={failures}")


if __name__ == "__main__":
    main()
