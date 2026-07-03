"""Read-only audit: stable Goliath/Fusion, underdog xG, scoreline bias (cff4c30 path).

Does not modify prediction logic or persisted data.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from api import main as api_main
from core.maher import estimate_xg_pair

REPORTS = BACKEND / "reports"

FIXTURES: list[tuple[str, str]] = [
    ("Argentina", "Cape Verde"),
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
    ("Switzerland", "Algeria"),
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

SCENARIOS: dict[str, dict[str, Any]] = {
    "A_goliath_on_alt0_ctx_off": {
        "fusion_blowout_enabled": True,
        "altitude": 0,
        "use_match_context": False,
        "auto_stadium_altitude": False,
    },
    "B_goliath_on_alt1500_ctx_off": {
        "fusion_blowout_enabled": True,
        "altitude": 1500,
        "use_match_context": False,
        "auto_stadium_altitude": False,
    },
    "C_goliath_on_alt0_ctx_on": {
        "fusion_blowout_enabled": True,
        "altitude": 0,
        "use_match_context": True,
        "auto_stadium_altitude": False,
        "match_date": "2026-06-15",
        "venue_city": "Houston",
    },
    "D_goliath_off_alt0_ctx_off": {
        "fusion_blowout_enabled": False,
        "altitude": 0,
        "use_match_context": False,
        "auto_stadium_altitude": False,
    },
    "E_goliath_off_alt1500_ctx_off": {
        "fusion_blowout_enabled": False,
        "altitude": 1500,
        "use_match_context": False,
        "auto_stadium_altitude": False,
    },
}

CITY_SENSITIVITY = [
    None,
    "Houston",
    "Miami",
    "New York",
    "Los Angeles",
    "Dallas",
    "Mexico City",
]


def _poisson_scores_prob(xg: float) -> float:
    return round((1.0 - math.exp(-max(float(xg), 0.0))) * 100.0, 2)


def _poisson_btts(home_xg: float, away_xg: float) -> float:
    p_h = 1.0 - math.exp(-max(home_xg, 0.0))
    p_a = 1.0 - math.exp(-max(away_xg, 0.0))
    return round(p_h * p_a * 100.0, 2)


def _score_label(row: dict | None) -> str:
    if not row:
        return ""
    return f"{row['home_goals']}-{row['away_goals']}"


def _top_scores(data: dict, limit: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in data.get("top_scores") or []:
        out.append({"score": item["score"], "probability": float(item["probability"])})
    return out[:limit]


def _gf_ga_source(team_data: dict) -> str:
    matches = int(team_data.get("matches_used") or 0)
    gf = float(team_data.get("goals_for_per_game") or 0.0)
    ga = float(team_data.get("goals_against_per_game") or 0.0)
    if matches > 0 and (gf > 0 or ga > 0):
        return "real"
    if gf == 0 and ga == 0:
        return "fallback_zero"
    return "unknown"


def _team_meta(home: str, away: str) -> dict[str, Any]:
    dm = api_main._data_manager
    _, home_data = dm.resolve_team(home)
    _, away_data = dm.resolve_team(away)
    maher_h, maher_a = estimate_xg_pair(
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        global_avg=2.6,
    )
    return {
        "home_attack": home_data.get("attack"),
        "home_defense": home_data.get("defense"),
        "away_attack": away_data.get("attack"),
        "away_defense": away_data.get("defense"),
        "home_gf_pg": home_data.get("goals_for_per_game"),
        "home_ga_pg": home_data.get("goals_against_per_game"),
        "away_gf_pg": away_data.get("goals_for_per_game"),
        "away_ga_pg": away_data.get("goals_against_per_game"),
        "home_matches_used": home_data.get("matches_used"),
        "away_matches_used": away_data.get("matches_used"),
        "home_gf_ga_source": _gf_ga_source(home_data),
        "away_gf_ga_source": _gf_ga_source(away_data),
        "maher_home_xg": maher_h,
        "maher_away_xg": maher_a,
    }


def _underdog_side(data: dict) -> str:
    sd = data.get("scoreline_decision") or {}
    fav = sd.get("favorite_outcome")
    if fav == "home_win":
        return "away"
    if fav == "away_win":
        return "home"
    hp = float(data["home_power"])
    ap = float(data["away_power"])
    return "away" if hp >= ap else "home"


def _suspicious_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    ud_p = float(row.get("underdog_p_scores") or 0.0)
    btts = float(row.get("btts_probability") or 0.0)
    primary = str(row.get("primary_score") or "")
    fusion_delta_fav = float(row.get("fusion_delta_favorite_xg") or 0.0)
    if row.get("fusion_active") and fusion_delta_fav >= 0.8:
        flags.append("GOLIATH_LARGE_FAVORITE_XG_JUMP")
    if ud_p >= 45.0 and primary.endswith("-0") and "-" in primary:
        parts = primary.split("-")
        if len(parts) == 2 and parts[1] == "0":
            flags.append("CLEAN_SHEET_VS_HIGH_UD_SCORE_PROB")
    if ud_p >= 50.0 and btts >= 40.0 and primary.endswith("-0"):
        flags.append("BTTS_ELEVATED_BUT_CLEAN_SHEET_PRIMARY")
    if float(row.get("underdog_xg") or 0.0) >= 0.7 and row.get("underdog_gf_ga_source") == "fallback_zero":
        flags.append("WEAK_UNDERDOG_FALLBACK_XG_FLOOR")
    return flags


def _predict(client: TestClient, home: str, away: str, **overrides: Any) -> dict:
    body = {**BASELINE, "home_team": home, "away_team": away, **overrides}
    resp = client.post("/api/predict", json=body)
    resp.raise_for_status()
    return resp.json()


def _extract_row(
    *,
    home: str,
    away: str,
    scenario: str,
    data: dict,
    meta: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sd = data.get("scoreline_decision") or {}
    probs = data["probabilities_1x2"]
    fusion = data.get("fusion_blowout_diagnostics") or {}
    std_blowout = data.get("standard_blowout_diagnostics") or {}
    env = data.get("environment_diagnostics") or {}
    mcd = data.get("match_context_diagnostics") or {}
    uf = data.get("underdog_foundation_diagnostics") or {}

    ud_side = _underdog_side(data)
    if ud_side == "home":
        ud_xg = float(data["home_xg"])
        fav_xg = float(data["away_xg"])
    else:
        ud_xg = float(data["away_xg"])
        fav_xg = float(data["home_xg"])

    xg_before = fusion.get("xg_before") or {}
    xg_after = fusion.get("xg_after") or {}
    fav_side = fusion.get("favorite_side")
    fusion_delta_home = None
    fusion_delta_away = None
    fusion_delta_favorite = None
    if xg_before and xg_after:
        fusion_delta_home = round(float(xg_after.get("home", 0)) - float(xg_before.get("home", 0)), 2)
        fusion_delta_away = round(float(xg_after.get("away", 0)) - float(xg_before.get("away", 0)), 2)
        if fav_side == "home":
            fusion_delta_favorite = fusion_delta_home
        elif fav_side == "away":
            fusion_delta_favorite = fusion_delta_away

    primary = sd.get("primary_predicted_score")
    row: dict[str, Any] = {
        "fixture": f"{home} vs {away}",
        "scenario": scenario,
        "venue_city": extra.get("venue_city") if extra else mcd.get("venue_city"),
        "fusion_blowout_enabled": data.get("fusion_blowout_enabled", extra.get("fusion_blowout_enabled") if extra else None),
        "use_match_context": extra.get("use_match_context") if extra is not None else None,
        "auto_stadium_altitude": extra.get("auto_stadium_altitude") if extra is not None else None,
        "altitude_input": extra.get("altitude") if extra is not None else None,
        "resolved_altitude_m": env.get("venue_altitude_m"),
        "altitude_source": env.get("altitude_source"),
        "base_home_xg": data.get("base_home_xg"),
        "base_away_xg": data.get("base_away_xg"),
        "pre_fusion_home_xg": xg_before.get("home"),
        "pre_fusion_away_xg": xg_before.get("away"),
        "post_fusion_home_xg": xg_after.get("home"),
        "post_fusion_away_xg": xg_after.get("away"),
        "fusion_applied": fusion.get("active"),
        "fusion_blowout_t": fusion.get("blowout_t"),
        "fusion_triggers": fusion.get("triggers"),
        "fusion_suppressed_by": fusion.get("suppressed_by"),
        "fusion_delta_home_xg": fusion_delta_home,
        "fusion_delta_away_xg": fusion_delta_away,
        "fusion_delta_favorite_xg": fusion_delta_favorite,
        "standard_blowout_applied": data.get("blowout_adjustment_applied") and not fusion.get("active"),
        "final_home_xg": data["home_xg"],
        "final_away_xg": data["away_xg"],
        "total_xg": round(float(data["home_xg"]) + float(data["away_xg"]), 2),
        "home_win": probs["home_win"],
        "draw": probs["draw"],
        "away_win": probs["away_win"],
        "primary_score": _score_label(primary),
        "top_exact_score": _score_label(sd.get("top_exact_score_overall")),
        "primary_score_reason": sd.get("primary_score_reason"),
        "top_5_scores": _top_scores(data, 5),
        "underdog_side": ud_side,
        "underdog_xg": ud_xg,
        "underdog_p_scores": _poisson_scores_prob(ud_xg),
        "favorite_xg": fav_xg,
        "favorite_clean_sheet_prob_approx": round(100.0 - _poisson_scores_prob(ud_xg), 2),
        "btts_probability": sd.get("both_teams_score_probability") or _poisson_btts(
            float(data["home_xg"]), float(data["away_xg"])
        ),
        "underdog_scores_probability_sd": sd.get("underdog_scores_probability"),
        "home_power": data["home_power"],
        "away_power": data["away_power"],
        "power_gap": round(float(data["home_power"]) - float(data["away_power"]), 2),
        "home_attack": meta["home_attack"],
        "home_defense": meta["home_defense"],
        "away_attack": meta["away_attack"],
        "away_defense": meta["away_defense"],
        "maher_home_xg": meta["maher_home_xg"],
        "maher_away_xg": meta["maher_away_xg"],
        "home_gf_ga_source": meta["home_gf_ga_source"],
        "away_gf_ga_source": meta["away_gf_ga_source"],
        "home_matches_used": meta["home_matches_used"],
        "away_matches_used": meta["away_matches_used"],
        "maher_fallback_confidence": uf.get("maher_fallback_confidence"),
        "maher_fallback_confidence_applied": uf.get("maher_fallback_confidence_applied"),
        "underdog_floor_applied": uf.get("underdog_floor_applied"),
        "underdog_floor_standard": uf.get("underdog_floor_standard"),
        "underdog_floor_adaptive": uf.get("underdog_floor_adaptive"),
        "underdog_floor_reason": uf.get("underdog_floor_reason"),
        # Stage 3A — Fusion adaptive dog floor
        "fusion_dog_floor_original": fusion.get("fusion_dog_floor_original"),
        "fusion_dog_floor_adaptive": fusion.get("fusion_dog_floor_adaptive"),
        "fusion_dog_floor_adaptive_applied": fusion.get("fusion_dog_floor_adaptive_applied"),
        "fusion_dog_floor_reason": fusion.get("fusion_dog_floor_reason"),
        "fusion_underdog_attack": fusion.get("fusion_underdog_attack"),
        "fusion_favorite_defense": fusion.get("fusion_favorite_defense"),
        "fusion_underdog_gf_ga_fallback": fusion.get("fusion_underdog_gf_ga_fallback"),
        # Part 4 — Standard Blowout adaptive dog floor
        "standard_dog_floor_original": std_blowout.get("dog_floor_original"),
        "standard_dog_floor_adaptive": std_blowout.get("dog_floor_adaptive"),
        "standard_dog_floor_adaptive_applied": std_blowout.get("dog_floor_adaptive_applied"),
        "standard_dog_floor_reason": std_blowout.get("dog_floor_reason"),
        # Stage 3B — scoreline clean-sheet guard
        "clean_sheet_guard_applied": sd.get("clean_sheet_guard_applied"),
        "clean_sheet_guard_reason": sd.get("clean_sheet_guard_reason"),
        "original_primary_score": sd.get("original_primary_score"),
        "guarded_primary_score": sd.get("guarded_primary_score"),
        "best_btts_candidate": sd.get("best_btts_candidate"),
        "clean_sheet_guard_utility_gap": sd.get("clean_sheet_guard_utility_gap"),
        "scoreline_warnings": sd.get("primary_score_warnings"),
        "representative_method": sd.get("representative_score_method"),
        "gate_level": (sd.get("underdog_goal_gate") or {}).get("level"),
        "candidate_comparison": sd.get("candidate_comparison_summary"),
    }
    if extra:
        row.update(extra)
    row["suspicious_flags"] = _suspicious_flags(row)
    return row


def run_core_audit(client: TestClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for home, away in FIXTURES:
        meta = _team_meta(home, away)
        for scenario_name, overrides in SCENARIOS.items():
            payload = {**BASELINE, **overrides}
            data = _predict(
                client,
                home,
                away,
                **{k: v for k, v in payload.items() if k not in ("home_team", "away_team")},
            )
            rows.append(
                _extract_row(
                    home=home,
                    away=away,
                    scenario=scenario_name,
                    data=data,
                    meta=meta,
                    extra=overrides,
                )
            )
    return rows


def run_altitude_probe(client: TestClient) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    home, away = "Argentina", "Cape Verde"
    meta = _team_meta(home, away)
    cases = [
        {"altitude": 0, "auto_stadium_altitude": False, "label": "manual_0"},
        {"altitude": 1500, "auto_stadium_altitude": False, "label": "manual_1500"},
        {
            "altitude": 0,
            "auto_stadium_altitude": True,
            "venue_city": "Houston",
            "label": "auto_houston",
        },
        {
            "altitude": 0,
            "auto_stadium_altitude": True,
            "venue_city": "Miami",
            "label": "auto_miami",
        },
        {"altitude": 0, "auto_stadium_altitude": False, "label": "default_no_field"},
    ]
    for case in cases:
        label = case.pop("label")
        data = _predict(
            client,
            home,
            away,
            fusion_blowout_enabled=True,
            use_match_context=False,
            odds_affect_prediction=False,
            **case,
        )
        row = _extract_row(
            home=home,
            away=away,
            scenario=f"altitude_probe_{label}",
            data=data,
            meta=meta,
            extra=case,
        )
        row["probe_label"] = label
        probes.append(row)
    return probes


def run_city_sensitivity(client: TestClient) -> list[dict[str, Any]]:
    """Limited city grid: Goliath ON, auto altitude OFF, context ON/OFF."""
    rows: list[dict[str, Any]] = []
    home, away = "Argentina", "Cape Verde"
    meta = _team_meta(home, away)
    for city in CITY_SENSITIVITY:
        for ctx_on in (False, True):
            overrides: dict[str, Any] = {
                "fusion_blowout_enabled": True,
                "use_match_context": ctx_on,
                "auto_stadium_altitude": False,
                "altitude": 0,
                "match_date": "2026-06-15",
            }
            if city:
                overrides["venue_city"] = city
            label = f"city={city or 'none'}_ctx={ctx_on}"
            data = _predict(client, home, away, **overrides)
            rows.append(
                _extract_row(
                    home=home,
                    away=away,
                    scenario=f"city_sensitivity_{label}",
                    data=data,
                    meta=meta,
                    extra={**overrides, "venue_city": city},
                )
            )
    return rows


def _md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        cells = []
        for col in columns:
            val = row.get(col, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            cells.append(str(val).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_markdown(
    path: Path,
    *,
    core_rows: list[dict[str, Any]],
    altitude_rows: list[dict[str, Any]],
    city_rows: list[dict[str, Any]],
) -> None:
    scenario_a = [r for r in core_rows if r["scenario"] == "A_goliath_on_alt0_ctx_off"]
    lines = [
        "# Stable Goliath / Underdog / Scoreline Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Scenario A — Goliath ON (baseline)",
        "",
        _md_table(
            scenario_a,
            [
                "fixture",
                "final_home_xg",
                "final_away_xg",
                "fusion_blowout_t",
                "fusion_delta_favorite_xg",
                "primary_score",
                "underdog_p_scores",
                "btts_probability",
                "suspicious_flags",
            ],
        ),
        "",
        "## Goliath ON vs OFF (scenario A vs D)",
        "",
    ]
    for home, away in FIXTURES:
        on = next(
            r
            for r in core_rows
            if r["fixture"] == f"{home} vs {away}" and r["scenario"] == "A_goliath_on_alt0_ctx_off"
        )
        off = next(
            r
            for r in core_rows
            if r["fixture"] == f"{home} vs {away}" and r["scenario"] == "D_goliath_off_alt0_ctx_off"
        )
        lines.append(
            f"- **{home} vs {away}**: OFF {off['final_home_xg']}-{off['final_away_xg']} → "
            f"ON {on['final_home_xg']}-{on['final_away_xg']} "
            f"(t={on.get('fusion_blowout_t')}, Δfav={on.get('fusion_delta_favorite_xg')}) "
            f"primary {on['primary_score']}"
        )
    lines.extend(["", "## Altitude probes (Argentina vs Cape Verde)", ""])
    lines.append(
        _md_table(
            altitude_rows,
            [
                "probe_label",
                "altitude_input",
                "resolved_altitude_m",
                "altitude_source",
                "final_home_xg",
                "final_away_xg",
                "fusion_delta_favorite_xg",
            ],
        )
    )
    lines.extend(["", "## City sensitivity summary (Argentina vs Cape Verde)", ""])
    compact = []
    for r in city_rows:
        compact.append(
            {
                "venue_city": r.get("venue_city"),
                "use_match_context": r.get("use_match_context"),
                "auto_stadium_altitude": r.get("auto_stadium_altitude"),
                "final_home_xg": r["final_home_xg"],
                "final_away_xg": r["final_away_xg"],
                "primary_score": r["primary_score"],
            }
        )
    lines.append(_md_table(compact, list(compact[0].keys()) if compact else []))
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stable Goliath/underdog/scoreline audit")
    parser.add_argument("--json-out", type=Path, default=REPORTS / "stable_goliath_underdog_scoreline_audit.json")
    parser.add_argument("--md-out", type=Path, default=REPORTS / "stable_goliath_underdog_scoreline_audit.md")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip exhaustive city matrix (faster; core + altitude probes only)",
    )
    args = parser.parse_args()

    client = TestClient(api_main.app)
    core_rows = run_core_audit(client)
    altitude_rows = run_altitude_probe(client)
    city_rows: list[dict[str, Any]] = []
    if not args.quick:
        city_rows = run_city_sensitivity(client)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stable_commit": "cff4c30",
        "core_rows": core_rows,
        "altitude_probes": altitude_rows,
        "city_sensitivity": city_rows,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(args.md_out, core_rows=core_rows, altitude_rows=altitude_rows, city_rows=city_rows)
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    print(f"Core rows: {len(core_rows)}")


if __name__ == "__main__":
    main()
