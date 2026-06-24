"""Compare /api/predict outputs before vs after local fusion cache refresh."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from fastapi.testclient import TestClient

from core.recent_form_fusion import FUSION_CACHE_PATH

BACKUP_PATH = FUSION_CACHE_PATH.with_suffix(".json.before_refresh")

AUDIT_MATCHUPS: list[tuple[str, str, str]] = [
    ("Germany", "Netherlands", "balanced"),
    ("Brazil", "Haiti", "favorite_underdog"),
    ("Spain", "Cape Verde", "wc_group_low_data"),
    ("Scotland", "Haiti", "wc_group_underdog"),
    ("New Zealand", "Egypt", "low_data"),
    ("Brazil", "Morocco", "wc_group"),
    ("Curacao", "Netherlands", "heavy_underdog"),
    ("DR Congo", "France", "heavy_underdog"),
]


def _score_label(row: dict | None) -> str:
    if not row:
        return ""
    return f"{row.get('home_goals')}-{row.get('away_goals')}"


def _predict(client: TestClient, home: str, away: str) -> dict:
    resp = client.post(
        "/api/predict",
        json={"home_team": home, "away_team": away, "neutral_ground": True},
    )
    resp.raise_for_status()
    return resp.json()


def _snapshot(data: dict) -> dict:
    probs = data.get("probabilities_1x2") or {}
    sd = data.get("scoreline_decision") or {}
    gate = sd.get("underdog_goal_gate") or {}
    rf = sd.get("recent_form_shadow") or gate.get("recent_form") or {}
    return {
        "prob_home": round(float(probs.get("home_win", 0)), 4),
        "prob_draw": round(float(probs.get("draw", 0)), 4),
        "prob_away": round(float(probs.get("away_win", 0)), 4),
        "home_xg": data.get("home_xg"),
        "away_xg": data.get("away_xg"),
        "primary_score": _score_label(sd.get("primary_predicted_score")),
        "gate_level": gate.get("level"),
        "recent_form_confidence": rf.get("recent_form_confidence"),
        "last_10_scored_rate": rf.get("last_10_scored_rate"),
        "source_mix": rf.get("source_mix") or {},
        "coverage_quality": rf.get("coverage_quality"),
    }


def _make_client() -> TestClient:
    os.environ.setdefault("RECENT_FORM_SHADOW_ENABLED", "true")
    os.environ.setdefault("RECENT_FORM_ACTIVE_EXPERIMENT_ENABLED", "true")
    os.environ.setdefault("RECENT_FORM_AFFECTS_SCORELINE", "true")
    import importlib

    import api.main as api_main

    importlib.reload(api_main)
    return TestClient(api_main.app)


def _swap_fusion_cache(cache_path: Path | None) -> tuple[dict | None, bool]:
    """Replace fusion cache with optional payload; returns (previous_payload, had_previous)."""
    previous: dict | None = None
    had_previous = FUSION_CACHE_PATH.exists()
    if had_previous:
        previous = json.loads(FUSION_CACHE_PATH.read_text(encoding="utf-8"))
    if cache_path is not None and cache_path.exists():
        FUSION_CACHE_PATH.write_text(
            cache_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    elif had_previous:
        FUSION_CACHE_PATH.unlink(missing_ok=True)
    return previous, had_previous


def _restore_fusion_cache(previous: dict | None, *, had_previous: bool) -> None:
    if had_previous and previous is not None:
        FUSION_CACHE_PATH.write_text(
            json.dumps(previous, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif FUSION_CACHE_PATH.exists():
        FUSION_CACHE_PATH.unlink(missing_ok=True)


def _snapshots_for_cache(cache_path: Path | None) -> dict[str, dict]:
    previous, had_previous = _swap_fusion_cache(cache_path)
    try:
        client = _make_client()
        out: dict[str, dict] = {}
        for home, away, _label in AUDIT_MATCHUPS:
            key = f"{home} vs {away}"
            out[key] = _snapshot(_predict(client, home, away))
        return out
    finally:
        _restore_fusion_cache(previous, had_previous=had_previous)


def run_diff(*, before_cache: Path | None = None) -> list[dict]:
    before_path = before_cache or (BACKUP_PATH if BACKUP_PATH.exists() else None)
    before_rows = _snapshots_for_cache(before_path)
    after_rows = _snapshots_for_cache(FUSION_CACHE_PATH if FUSION_CACHE_PATH.exists() else None)

    rows: list[dict] = []
    unexpected_prob_changes: list[str] = []

    for home, away, label in AUDIT_MATCHUPS:
        key = f"{home} vs {away}"
        before = before_rows[key]
        after = after_rows[key]
        prob_changed = (
            before["prob_home"] != after["prob_home"]
            or before["prob_draw"] != after["prob_draw"]
            or before["prob_away"] != after["prob_away"]
        )
        xg_changed = before["home_xg"] != after["home_xg"] or before["away_xg"] != after["away_xg"]
        score_changed = before["primary_score"] != after["primary_score"]
        if prob_changed or xg_changed:
            unexpected_prob_changes.append(key)
        rows.append(
            {
                "match": key,
                "category": label,
                "prob_home_before": before["prob_home"],
                "prob_home_after": after["prob_home"],
                "prob_draw_before": before["prob_draw"],
                "prob_draw_after": after["prob_draw"],
                "prob_away_before": before["prob_away"],
                "prob_away_after": after["prob_away"],
                "home_xg_before": before["home_xg"],
                "home_xg_after": after["home_xg"],
                "away_xg_before": before["away_xg"],
                "away_xg_after": after["away_xg"],
                "primary_before": before["primary_score"],
                "primary_after": after["primary_score"],
                "gate_before": before["gate_level"],
                "gate_after": after["gate_level"],
                "rf_conf_before": before["recent_form_confidence"],
                "rf_conf_after": after["recent_form_confidence"],
                "scored_rate_before": before["last_10_scored_rate"],
                "scored_rate_after": after["last_10_scored_rate"],
                "prob_or_xg_changed": prob_changed or xg_changed,
                "scoreline_changed": score_changed,
            }
        )

    if unexpected_prob_changes:
        print("WARNING: unexpected 1X2/xG changes detected:")
        for item in unexpected_prob_changes:
            print(f"  - {item}")

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Prediction diff before/after fusion cache")
    parser.add_argument("--before-cache", type=str, default="")
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    before_path = Path(args.before_cache) if args.before_cache else None
    rows = run_diff(before_cache=before_path)
    print(f"{'Match':<28} {'1X2 d':<6} {'xG d':<6} {'Score':<12} RF conf")
    print("-" * 80)
    for row in rows:
        prob_delta = "yes" if row["prob_or_xg_changed"] else "no"
        xg_delta = (
            "yes"
            if row["home_xg_before"] != row["home_xg_after"]
            or row["away_xg_before"] != row["away_xg_after"]
            else "no"
        )
        score = f"{row['primary_before']} -> {row['primary_after']}"
        rf = f"{row['rf_conf_before']} -> {row['rf_conf_after']}"
        print(f"{row['match']:<28} {prob_delta:<6} {xg_delta:<6} {score:<12} {rf}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
