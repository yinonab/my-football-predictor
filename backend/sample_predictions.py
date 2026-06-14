import httpx

matches = [
    ("Argentina (ארגנטינה)", "France (צרפת)"),
    ("Canada (קנדה)", "Bosnia (בוסניה)"),
    ("Brazil (ברזיל)", "Germany (גרמניה)"),
]

for home, away in matches:
    r = httpx.post(
        "http://127.0.0.1:8000/api/predict",
        json={
            "home_team": home,
            "away_team": away,
            "neutral_ground": True,
            "alpha": 0.12,
        },
    )
    d = r.json()
    p = d["probabilities_1x2"]
    print(f"\n=== {home} vs {away} ===")
    print(f"1X2: Home {p['home_win']}% | Draw {p['draw']}% | Away {p['away_win']}%")
    print(f"xG: {d['home_xg']} - {d['away_xg']}")
    for s in d["top_scores"]:
        print(f"  {s['score']}: {s['probability']}%")
