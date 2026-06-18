"""Phase 3C — Local candidate enablement QA helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from core.external_rating_snapshots import list_production_team_names

WARNING_LARGE_CANDIDATE_SHIFT = "LARGE_CANDIDATE_SHIFT"
WARNING_FAVORITE_DIRECTION_REVERSED = "FAVORITE_DIRECTION_REVERSED"
WARNING_BALANCED_MATCH_SHIFT = "BALANCED_MATCH_SHIFT"
WARNING_UNEXPECTED_FALLBACK = "UNEXPECTED_FALLBACK"

QA_MATCHUPS_PATH = Path(__file__).resolve().parent.parent / "data" / "activation_qa_matchups.json"


@dataclass(frozen=True)
class QAMatchup:
    category: str
    category_label: str
    home: str
    away: str


@dataclass
class QAMatchupAnalysis:
    category: str
    category_label: str
    home: str
    away: str
    baseline_home_win: float
    active_home_win: float
    delta_home_win: float
    baseline_draw: float
    active_draw: float
    baseline_away_win: float
    active_away_win: float
    baseline_xg: float
    active_xg: float
    baseline_top_scores: str
    active_top_scores: str
    fallback: bool
    warnings: list[str] = field(default_factory=list)
    shift_class: str = "no_change"
    model_version_active: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "category_label": self.category_label,
            "home": self.home,
            "away": self.away,
            "baseline_home_win": self.baseline_home_win,
            "active_home_win": self.active_home_win,
            "delta_home_win": self.delta_home_win,
            "baseline_draw": self.baseline_draw,
            "active_draw": self.active_draw,
            "baseline_away_win": self.baseline_away_win,
            "active_away_win": self.active_away_win,
            "baseline_xg": self.baseline_xg,
            "active_xg": self.active_xg,
            "baseline_top_scores": self.baseline_top_scores,
            "active_top_scores": self.active_top_scores,
            "fallback": self.fallback,
            "warnings": ",".join(self.warnings) if self.warnings else "",
            "shift_class": self.shift_class,
            "model_version_active": self.model_version_active,
        }


@dataclass
class QAReportSummary:
    total_matchups: int
    fallback_count: int
    large_shift_count: int
    balanced_shift_count: int
    direction_reversal_count: int
    avg_abs_home_win_delta: float
    max_abs_home_win_delta: float
    top_largest_shifts: list[QAMatchupAnalysis] = field(default_factory=list)
    skipped_matchups: list[dict[str, str]] = field(default_factory=list)

    def recommendation(self) -> str:
        if self.fallback_count > 0:
            return "hold"
        if (
            self.balanced_shift_count > 0
            or self.direction_reversal_count > 0
            or self.large_shift_count > 0
        ):
            return "needs_review"
        return "proceed"


def classify_home_win_shift(delta_home_win: float) -> str:
    abs_delta = abs(delta_home_win)
    if abs_delta < 1.0:
        return "no_change"
    if abs_delta < 3.0:
        return "small_shift"
    if abs_delta <= 7.0:
        return "medium_shift"
    return "large_shift"


def favorite_direction_reversed(
    baseline_probs: dict[str, float],
    active_probs: dict[str, float],
) -> bool:
    base_home = baseline_probs["home_win"]
    base_away = baseline_probs["away_win"]
    active_home = active_probs["home_win"]
    active_away = active_probs["away_win"]
    if base_home == base_away:
        return False
    base_fav_home = base_home > base_away
    active_fav_home = active_home > active_away
    return base_fav_home != active_fav_home


def balanced_match_shift_warning(
    baseline_probs: dict[str, float],
    active_probs: dict[str, float],
    *,
    balanced_max_prob: float | None = None,
    max_shift_pp: float | None = None,
) -> bool:
    balanced_max = balanced_max_prob or config.BALANCED_MATCH_MAX_BASE_PROB
    shift_limit = max_shift_pp or config.BALANCED_MATCH_MAX_SHIFT_PP
    if max(baseline_probs.values()) >= balanced_max:
        return False
    for key in ("home_win", "draw", "away_win"):
        if abs(active_probs[key] - baseline_probs[key]) > shift_limit:
            return True
    return False


def format_top_scores(scores: list[str] | list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in scores[:3]:
        if isinstance(item, dict):
            parts.append(f"{item.get('score', '?')}:{item.get('probability', 0):.1f}")
        else:
            parts.append(str(item))
    return ", ".join(parts)


def collect_qa_warnings(
    *,
    baseline_probs: dict[str, float],
    active_probs: dict[str, float],
    delta_home_win: float,
    fallback: bool,
    large_shift_pp: float = 7.0,
) -> list[str]:
    warnings: list[str] = []
    if fallback:
        warnings.append(WARNING_UNEXPECTED_FALLBACK)
    if abs(delta_home_win) > large_shift_pp:
        warnings.append(WARNING_LARGE_CANDIDATE_SHIFT)
    if favorite_direction_reversed(baseline_probs, active_probs):
        warnings.append(WARNING_FAVORITE_DIRECTION_REVERSED)
    if balanced_match_shift_warning(baseline_probs, active_probs, max_shift_pp=large_shift_pp):
        warnings.append(WARNING_BALANCED_MATCH_SHIFT)
    return warnings


def load_activation_qa_matchups(
    path: Path | None = None,
) -> tuple[list[QAMatchup], list[dict[str, str]]]:
    target = path or QA_MATCHUPS_PATH
    with target.open(encoding="utf-8") as fh:
        doc = json.load(fh)
    production = set(list_production_team_names())
    skipped: list[dict[str, str]] = list(doc.get("skipped") or [])
    seen: set[tuple[str, str]] = set()
    matchups: list[QAMatchup] = []
    for block in doc.get("categories") or []:
        cat_id = str(block.get("id", "unknown"))
        cat_label = str(block.get("label", cat_id))
        for item in block.get("matchups") or []:
            home = str(item.get("home", "")).strip()
            away = str(item.get("away", "")).strip()
            if not home or not away:
                continue
            if home not in production or away not in production:
                skipped.append(
                    {
                        "home": home,
                        "away": away,
                        "reason": "team not in production FIFA_ELO_2026 list",
                    }
                )
                continue
            key = (home, away)
            if key in seen:
                continue
            seen.add(key)
            matchups.append(
                QAMatchup(category=cat_id, category_label=cat_label, home=home, away=away)
            )
    return matchups, skipped


def analyze_prediction_result(
    matchup: QAMatchup,
    prediction: dict[str, Any],
    *,
    large_shift_pp: float = 7.0,
) -> QAMatchupAnalysis:
    base = prediction["baseline"]
    active = prediction["active"]
    diag = prediction.get("model_diagnostics") or {}
    base_probs = base["probabilities_1x2"]
    active_probs = active["probabilities_1x2"]
    delta_h = round(active_probs["home_win"] - base_probs["home_win"], 2)
    fallback = bool(diag.get("fallback_to_baseline"))
    warnings = collect_qa_warnings(
        baseline_probs=base_probs,
        active_probs=active_probs,
        delta_home_win=delta_h,
        fallback=fallback,
        large_shift_pp=large_shift_pp,
    )
    return QAMatchupAnalysis(
        category=matchup.category,
        category_label=matchup.category_label,
        home=matchup.home,
        away=matchup.away,
        baseline_home_win=base_probs["home_win"],
        active_home_win=active_probs["home_win"],
        delta_home_win=delta_h,
        baseline_draw=base_probs["draw"],
        active_draw=active_probs["draw"],
        baseline_away_win=base_probs["away_win"],
        active_away_win=active_probs["away_win"],
        baseline_xg=base["home_xg"],
        active_xg=active["home_xg"],
        baseline_top_scores=format_top_scores(base.get("top_scores") or []),
        active_top_scores=format_top_scores(active.get("top_scores") or []),
        fallback=fallback,
        warnings=warnings,
        shift_class=classify_home_win_shift(delta_h),
        model_version_active=str(diag.get("model_version", "")),
    )


def summarize_qa_analyses(
    analyses: list[QAMatchupAnalysis],
    *,
    skipped: list[dict[str, str]] | None = None,
) -> QAReportSummary:
    if not analyses:
        return QAReportSummary(
            total_matchups=0,
            fallback_count=0,
            large_shift_count=0,
            balanced_shift_count=0,
            direction_reversal_count=0,
            avg_abs_home_win_delta=0.0,
            max_abs_home_win_delta=0.0,
            skipped_matchups=skipped or [],
        )
    abs_deltas = [abs(a.delta_home_win) for a in analyses]
    sorted_by_shift = sorted(analyses, key=lambda a: abs(a.delta_home_win), reverse=True)
    return QAReportSummary(
        total_matchups=len(analyses),
        fallback_count=sum(1 for a in analyses if a.fallback),
        large_shift_count=sum(1 for a in analyses if a.shift_class == "large_shift"),
        balanced_shift_count=sum(
            1 for a in analyses if WARNING_BALANCED_MATCH_SHIFT in a.warnings
        ),
        direction_reversal_count=sum(
            1 for a in analyses if WARNING_FAVORITE_DIRECTION_REVERSED in a.warnings
        ),
        avg_abs_home_win_delta=round(sum(abs_deltas) / len(abs_deltas), 2),
        max_abs_home_win_delta=round(max(abs_deltas), 2),
        top_largest_shifts=sorted_by_shift[:10],
        skipped_matchups=skipped or [],
    )


def format_qa_summary_text(summary: QAReportSummary) -> str:
    lines = [
        "Activation QA summary",
        f"  total matchups: {summary.total_matchups}",
        f"  fallback count: {summary.fallback_count}",
        f"  large shift count: {summary.large_shift_count}",
        f"  balanced shift count: {summary.balanced_shift_count}",
        f"  direction reversal count: {summary.direction_reversal_count}",
        f"  average |delta home win|: {summary.avg_abs_home_win_delta:.2f}pp",
        f"  max |delta home win|: {summary.max_abs_home_win_delta:.2f}pp",
        f"  recommendation: {summary.recommendation()}",
    ]
    if summary.skipped_matchups:
        lines.append(f"  skipped matchups: {len(summary.skipped_matchups)}")
    lines.append("\nTop 10 largest |delta home win|:")
    for idx, row in enumerate(summary.top_largest_shifts, start=1):
        warn = f" [{','.join(row.warnings)}]" if row.warnings else ""
        lines.append(
            f"  {idx:2d}. {row.home} vs {row.away}: {row.delta_home_win:+.1f}pp "
            f"({row.baseline_home_win:.1f} -> {row.active_home_win:.1f}){warn}"
        )
    return "\n".join(lines)


def format_qa_markdown(
    analyses: list[QAMatchupAnalysis],
    summary: QAReportSummary,
) -> str:
    lines = [
        "# Activation QA Report (Phase 3C)",
        "",
        "## Summary",
        "",
        f"- Total matchups: {summary.total_matchups}",
        f"- Fallback count: {summary.fallback_count}",
        f"- Large shift count: {summary.large_shift_count}",
        f"- Balanced shift count: {summary.balanced_shift_count}",
        f"- Direction reversal count: {summary.direction_reversal_count}",
        f"- Average |delta home win|: {summary.avg_abs_home_win_delta:.2f}pp",
        f"- Max |delta home win|: {summary.max_abs_home_win_delta:.2f}pp",
        f"- **Recommendation:** `{summary.recommendation()}`",
        "",
        "## Top 10 largest shifts",
        "",
        "| # | Matchup | Delta H | Baseline H | Active H | Warnings |",
        "|---|---------|---------|------------|----------|----------|",
    ]
    for idx, row in enumerate(summary.top_largest_shifts, start=1):
        warn = ", ".join(row.warnings) if row.warnings else "-"
        lines.append(
            f"| {idx} | {row.home} vs {row.away} | {row.delta_home_win:+.1f}pp | "
            f"{row.baseline_home_win:.1f}% | {row.active_home_win:.1f}% | {warn} |"
        )
    lines.extend(["", "## All matchups", ""])
    for row in analyses:
        lines.append(
            f"- **{row.category_label}** — {row.home} vs {row.away}: "
            f"{row.delta_home_win:+.1f}pp H ({row.shift_class})"
            + (f" — {', '.join(row.warnings)}" if row.warnings else "")
        )
    if summary.skipped_matchups:
        lines.extend(["", "## Skipped", ""])
        for item in summary.skipped_matchups:
            lines.append(
                f"- {item.get('home', '?')} vs {item.get('away', '?')}: "
                f"{item.get('reason', 'skipped')}"
            )
    return "\n".join(lines) + "\n"
