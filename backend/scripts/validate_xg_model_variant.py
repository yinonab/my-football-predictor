"""Quick validation: NR3 vs matchup_relative_v1 on fixture set."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

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
    "use_match_context": False,
    "odds_affect_prediction": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
}


def main() -> None:
    print("fixture | NR3 xG | MR xG | NR3 ud | MR ud")
    for home, away in FIXTURES:
        payload = {**BASE, "home_team": home, "away_team": away}
        nr3 = client.post(
            "/api/predict", json={**payload, "xg_model_variant": "nr3_fcc"}
        ).json()
        mr = client.post(
            "/api/predict",
            json={**payload, "xg_model_variant": "matchup_relative_v1"},
        ).json()
        print(
            f"{home} vs {away} | "
            f"{nr3['home_xg']}-{nr3['away_xg']} | "
            f"{mr['home_xg']}-{mr['away_xg']} | "
            f"{nr3['away_xg']} | {mr['away_xg']}"
        )

    sw = client.post(
        "/api/predict", json={**BASE, "home_team": "France", "away_team": "Sweden"}
    ).json()
    sw2 = client.post(
        "/api/predict",
        json={
            **BASE,
            "home_team": "France",
            "away_team": "Sweden",
            "xg_model_variant": "nr3_fcc",
        },
    ).json()
    parity = (
        sw["home_xg"] == sw2["home_xg"]
        and sw["away_xg"] == sw2["away_xg"]
        and sw["probabilities_1x2"] == sw2["probabilities_1x2"]
        and sw["top_scores"] == sw2["top_scores"]
    )
    print(f"NR3 default parity France-Sweden: {parity}")


if __name__ == "__main__":
    main()
