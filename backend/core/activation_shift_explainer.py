"""Phase 3D — Large activation shift explanation and review helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config
from core.activation_qa import (
    balanced_match_shift_warning,
    classify_home_win_shift,
    collect_qa_warnings,
    favorite_direction_reversed,
)
from core.active_model_activation import (
    _team_snapshot_from_live,
    compute_active_candidate_powers,
    run_prediction_with_active_candidate,
)
from core.external_rating_mode import NORMALIZATION_METHOD, normalize_fifa_points_to_elo_like
from core.external_rating_snapshots import get_team_fifa_points
from core.global_ratings import english_name
from core.opponent_maher import build_opponent_index
from core.power_effective_elo import blend_weights_for_strategy
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

EXPLANATION_EXPECTED_CORRECTION = "expected_correction"
EXPLANATION_SUSPICIOUS = "suspicious_shift"
EXPLANATION_NEEDS_MANUAL_REVIEW = "needs_manual_review"

REVIEWS_PATH = Path(__file__).resolve().parent.parent / config.ACTIVATION_LARGE_SHIFT_REVIEWS_PATH


def _matchup_key(home: str, away: str) -> str:
    return f"{home.strip()}|{away.strip()}"


def _external_side_detail(
    team_en: str,
    team_key: str,
    *,
    dataset_key: str,
    strategy: str,
    data_manager: LiveDataManager,
) -> dict[str, Any]:
    fifa_points, fifa_ok = get_team_fifa_points(dataset_key, team_en)
    snap = _team_snapshot_from_live(team_key, team_en, data_manager)
    normalized = None
    norm_method = NORMALIZATION_METHOD
    confidence_weight = 0.0
    effective_blend = snap.internal_elo
    if fifa_ok and fifa_points is not None:
        norm = normalize_fifa_points_to_elo_like(float(fifa_points), dataset_key)
        normalized = norm.get("normalized_external_rating")
        norm_method = str(norm.get("normalization_method", NORMALIZATION_METHOD))
        if normalized is not None:
            wi, ww = blend_weights_for_strategy(
                strategy,
                internal_elo=snap.internal_elo,
                world_elo=float(normalized),
                rating_confidence=snap.rating_confidence,
                world_available=True,
            )
            confidence_weight = round(ww, 3)
            effective_blend = round(wi * snap.internal_elo + ww * float(normalized), 1)
    return {
        "fifa_points": float(fifa_points) if fifa_ok and fifa_points is not None else None,
        "normalized_external": normalized,
        "normalization_method": norm_method,
        "confidence_weight": confidence_weight,
        "internal_elo": snap.internal_elo,
        "effective_blend_elo": effective_blend,
    }


def classify_likely_explanation(
    *,
    shift_class: str,
    is_balanced_match: bool,
    direction_reversal: bool,
    fallback: bool,
    fifa_points_gap: float | None,
    power_gap_delta: float,
    home_win_delta_pp: float,
    baseline_home_win: float,
) -> str:
    if fallback:
        return EXPLANATION_SUSPICIOUS
    if direction_reversal:
        return EXPLANATION_SUSPICIOUS
    if shift_class == "large_shift":
        strong_fifa_gap = fifa_points_gap is not None and fifa_points_gap >= 250.0
        strengthens_favorite = power_gap_delta > 0 and home_win_delta_pp > 0
        if strong_fifa_gap and strengthens_favorite:
            return EXPLANATION_EXPECTED_CORRECTION
        if is_balanced_match and abs(home_win_delta_pp) > config.BALANCED_MATCH_MAX_SHIFT_PP:
            return EXPLANATION_SUSPICIOUS
        compressed_baseline = baseline_home_win < 72.0
        if compressed_baseline and strengthens_favorite:
            return EXPLANATION_EXPECTED_CORRECTION
        return EXPLANATION_NEEDS_MANUAL_REVIEW
    if is_balanced_match and abs(home_win_delta_pp) > config.BALANCED_MATCH_MAX_SHIFT_PP:
        return EXPLANATION_SUSPICIOUS
    return EXPLANATION_EXPECTED_CORRECTION


def explain_activation_shift(
    home: str,
    away: str,
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
) -> dict[str, Any]:
    dm = data_manager or LiveDataManager()
    opp = opponent_index or build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    home_key, _ = dm.resolve_team(home)
    away_key, _ = dm.resolve_team(away)
    home_en = english_name(home_key) or home
    away_en = english_name(away_key) or away
    dataset_key = config.PRODUCTION_FIFA_SNAPSHOT_DATASET
    strategy = config.ACTIVE_EXTERNAL_RATING_STRATEGY

    prediction = run_prediction_with_active_candidate(
        home_key,
        away_key,
        data_manager=dm,
        opponent_index=opp,
        force_enable=True,
    )
    base = prediction["baseline"]
    active = prediction["active"]
    diag = prediction.get("model_diagnostics") or {}
    base_probs = base["probabilities_1x2"]
    active_probs = active["probabilities_1x2"]
    delta_h = round(active_probs["home_win"] - base_probs["home_win"], 2)
    delta_d = round(active_probs["draw"] - base_probs["draw"], 2)
    delta_a = round(active_probs["away_win"] - base_probs["away_win"], 2)

    base_gap = round(base["home_power"] - base["away_power"], 2)
    active_gap = round(active["home_power"] - active["away_power"], 2)

    home_ext = _external_side_detail(
        home_en, home_key, dataset_key=dataset_key, strategy=strategy, data_manager=dm
    )
    away_ext = _external_side_detail(
        away_en, away_key, dataset_key=dataset_key, strategy=strategy, data_manager=dm
    )
    _, _, home_blend, away_blend, _ = compute_active_candidate_powers(
        home_key, away_key, data_manager=dm
    )

    fifa_gap = None
    if home_ext["fifa_points"] is not None and away_ext["fifa_points"] is not None:
        fifa_gap = abs(home_ext["fifa_points"] - away_ext["fifa_points"])

    fallback = bool(diag.get("fallback_to_baseline"))
    direction_reversal = favorite_direction_reversed(base_probs, active_probs)
    is_balanced = max(base_probs.values()) < config.BALANCED_MATCH_MAX_BASE_PROB
    shift_class = classify_home_win_shift(delta_h)
    likely = classify_likely_explanation(
        shift_class=shift_class,
        is_balanced_match=is_balanced,
        direction_reversal=direction_reversal,
        fallback=fallback,
        fifa_points_gap=fifa_gap,
        power_gap_delta=round(active_gap - base_gap, 2),
        home_win_delta_pp=delta_h,
        baseline_home_win=base_probs["home_win"],
    )

    return {
        "home": home_en,
        "away": away_en,
        "baseline": {
            "home_power": base["home_power"],
            "away_power": base["away_power"],
            "power_gap": base_gap,
            "home_xg": base["home_xg"],
            "away_xg": base["away_xg"],
            "probabilities_1x2": base_probs,
            "top_scores": list(base.get("top_scores") or []),
        },
        "active": {
            "home_power": active["home_power"],
            "away_power": active["away_power"],
            "power_gap": active_gap,
            "home_xg": active["home_xg"],
            "away_xg": active["away_xg"],
            "probabilities_1x2": active_probs,
            "top_scores": list(active.get("top_scores") or []),
        },
        "external_anchor": {
            "dataset": dataset_key,
            "strategy": strategy,
            "home_fifa_points": home_ext["fifa_points"],
            "away_fifa_points": away_ext["fifa_points"],
            "home_normalized_external": home_ext["normalized_external"],
            "away_normalized_external": away_ext["normalized_external"],
            "normalization_method": home_ext["normalization_method"],
            "home_confidence_weight": home_ext["confidence_weight"],
            "away_confidence_weight": away_ext["confidence_weight"],
            "confidence_weight": round(
                (home_ext["confidence_weight"] + away_ext["confidence_weight"]) / 2, 3
            ),
            "home_effective_blend_elo": home_blend,
            "away_effective_blend_elo": away_blend,
            "effective_rating_gap": round(home_blend - away_blend, 1),
            "fifa_points_gap": fifa_gap,
        },
        "deltas": {
            "power_gap_delta": round(active_gap - base_gap, 2),
            "home_xg_delta": round(active["home_xg"] - base["home_xg"], 3),
            "away_xg_delta": round(active["away_xg"] - base["away_xg"], 3),
            "xg_delta": round(active["home_xg"] - base["home_xg"], 3),
            "home_win_delta_pp": delta_h,
            "draw_delta_pp": delta_d,
            "away_win_delta_pp": delta_a,
        },
        "classification": {
            "shift_size": shift_class,
            "is_balanced_match": is_balanced,
            "direction_reversal": direction_reversal,
            "fallback": fallback,
            "warnings": collect_qa_warnings(
                baseline_probs=base_probs,
                active_probs=active_probs,
                delta_home_win=delta_h,
                fallback=fallback,
            ),
            "likely_explanation": likely,
        },
        "model_diagnostics": diag,
    }


def human_explanation_summary(explanation: dict[str, Any]) -> str:
    home = explanation["home"]
    away = explanation["away"]
    base = explanation["baseline"]
    active = explanation["active"]
    ext = explanation["external_anchor"]
    deltas = explanation["deltas"]
    cls = explanation["classification"]
    lines = [
        f"{home} vs {away} - activation shift explanation",
        "",
        "Summary",
        f"- Home win moved {deltas['home_win_delta_pp']:+.1f}pp "
        f"({base['probabilities_1x2']['home_win']:.1f}% -> "
        f"{active['probabilities_1x2']['home_win']:.1f}%)",
        f"- Shift class: {cls['shift_size']}",
        f"- Likely explanation: {cls['likely_explanation']}",
        f"- Fallback: {cls['fallback']}",
        "",
        "Why the candidate moved the prediction",
        f"- Baseline power gap (H-A): {base['power_gap']:.1f} -> active: {active['power_gap']:.1f} "
        f"(delta {deltas['power_gap_delta']:+.1f})",
        f"- Home xG: {base['home_xg']:.2f} -> {active['home_xg']:.2f} "
        f"(delta {deltas['home_xg_delta']:+.3f})",
        f"- Top scores baseline: {', '.join(base['top_scores'][:3]) or '-'}",
        f"- Top scores active: {', '.join(active['top_scores'][:3]) or '-'}",
        "",
        "External FIFA anchor",
        f"- {home} FIFA points: {ext['home_fifa_points']} "
        f"(normalized~{ext['home_normalized_external']}, weight={ext['home_confidence_weight']})",
        f"- {away} FIFA points: {ext['away_fifa_points']} "
        f"(normalized~{ext['away_normalized_external']}, weight={ext['away_confidence_weight']})",
        f"- FIFA points gap: {ext['fifa_points_gap']}",
        f"- Effective blend rating gap (H-A): {ext['effective_rating_gap']}",
        f"- Normalization: {ext['normalization_method']}",
        "",
        "Assessment",
    ]
    if cls["likely_explanation"] == EXPLANATION_EXPECTED_CORRECTION:
        lines.append(
            "- Looks like expected correction: FIFA anchor widens the favorite gap where "
            "baseline was relatively compressed for the external rating difference."
        )
    elif cls["likely_explanation"] == EXPLANATION_SUSPICIOUS:
        lines.append("- Suspicious: fallback, direction reversal, or balanced-match instability detected.")
    else:
        lines.append("- Needs manual review: large shift without a clear FIFA-gap correction pattern.")
    if cls["warnings"]:
        lines.append(f"- Warnings: {', '.join(cls['warnings'])}")
    return "\n".join(lines)


def format_explanation_markdown(explanation: dict[str, Any]) -> str:
    summary = human_explanation_summary(explanation)
    return "# Activation shift explanation\n\n```text\n" + summary + "\n```\n"


def load_large_shift_reviews(path: Path | None = None) -> dict[str, Any]:
    target = path or REVIEWS_PATH
    if not target.exists():
        return {"description": "Phase 3D large shift review records", "reviews": {}}
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_large_shift_reviews(doc: dict[str, Any], path: Path | None = None) -> Path:
    target = path or REVIEWS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target


def record_shift_review(
    explanation: dict[str, Any],
    *,
    status: str = "accepted",
    path: Path | None = None,
) -> dict[str, Any]:
    doc = load_large_shift_reviews(path)
    reviews = doc.setdefault("reviews", {})
    home = explanation["home"]
    away = explanation["away"]
    key = _matchup_key(home, away)
    reviews[key] = {
        "home": home,
        "away": away,
        "status": status,
        "explainability": explanation["classification"]["likely_explanation"],
        "home_win_delta_pp": explanation["deltas"]["home_win_delta_pp"],
        "shift_size": explanation["classification"]["shift_size"],
        "notes": human_explanation_summary(explanation).split("\n")[0],
    }
    save_large_shift_reviews(doc, path)
    return reviews[key]


def is_shift_reviewed_accepted(home: str, away: str, path: Path | None = None) -> bool:
    doc = load_large_shift_reviews(path)
    entry = (doc.get("reviews") or {}).get(_matchup_key(home, away))
    if not entry:
        return False
    return entry.get("status") == "accepted" and entry.get(
        "explainability"
    ) in (EXPLANATION_EXPECTED_CORRECTION, EXPLANATION_NEEDS_MANUAL_REVIEW)


def all_large_shifts_reviewed(
    large_shifts: list[tuple[str, str]],
    *,
    path: Path | None = None,
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for home, away in large_shifts:
        if not is_shift_reviewed_accepted(home, away, path):
            missing.append(f"{home} vs {away}")
    return len(missing) == 0, missing
