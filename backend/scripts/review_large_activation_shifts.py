#!/usr/bin/env python3
"""Review all large activation shifts from QA matchups (Phase 3D)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.activation_qa import (
    WARNING_LARGE_CANDIDATE_SHIFT,
    analyze_prediction_result,
    load_activation_qa_matchups,
)
from core.activation_shift_explainer import (
    EXPLANATION_EXPECTED_CORRECTION,
    EXPLANATION_SUSPICIOUS,
    explain_activation_shift,
    human_explanation_summary,
    record_shift_review,
)
from core.active_model_activation import run_prediction_with_active_candidate
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager

DEFAULT_REPORT = Path("reports/large_activation_shift_review.md")


def _find_large_shifts() -> list[tuple[str, str, object]]:
    matchups, _ = load_activation_qa_matchups()
    dm = LiveDataManager()
    opp = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))
    large: list[tuple[str, str, object]] = []
    for matchup in matchups:
        home_key, _ = dm.resolve_team(matchup.home)
        away_key, _ = dm.resolve_team(matchup.away)
        out = run_prediction_with_active_candidate(
            home_key,
            away_key,
            data_manager=dm,
            opponent_index=opp,
            force_enable=True,
        )
        row = analyze_prediction_result(matchup, out)
        if (
            row.shift_class == "large_shift"
            or WARNING_LARGE_CANDIDATE_SHIFT in row.warnings
        ):
            large.append((matchup.home, matchup.away, row))
    return large


def build_review_markdown(entries: list[dict]) -> str:
    lines = [
        "# Large activation shift review (Phase 3D)",
        "",
        f"Large shifts found: {len(entries)}",
        "",
    ]
    explainable = sum(1 for e in entries if e["explainable"])
    lines.append(f"- Explainable as expected correction: {explainable}/{len(entries)}")
    lines.append(f"- Needs attention: {len(entries) - explainable}")
    lines.append("")
    for idx, entry in enumerate(entries, start=1):
        lines.extend(
            [
                f"## {idx}. {entry['home']} vs {entry['away']}",
                "",
                f"- Home win delta: **{entry['delta_home_win']:+.1f}pp**",
                f"- Explainability: `{entry['likely_explanation']}`",
                f"- Review status: `{entry['review_status']}`",
                f"- Explainable: **{'yes' if entry['explainable'] else 'no'}**",
                "",
                "```text",
                entry["summary"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    report_path = DEFAULT_REPORT
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])

    large = _find_large_shifts()
    entries: list[dict] = []
    for home, away, row in large:
        explanation = explain_activation_shift(home, away)
        likely = explanation["classification"]["likely_explanation"]
        explainable = likely == EXPLANATION_EXPECTED_CORRECTION
        status = "accepted" if explainable else "needs_review"
        if likely != EXPLANATION_SUSPICIOUS:
            record_shift_review(explanation, status=status)
        entries.append(
            {
                "home": home,
                "away": away,
                "delta_home_win": row.delta_home_win,
                "likely_explanation": likely,
                "review_status": status,
                "explainable": explainable,
                "summary": human_explanation_summary(explanation),
            }
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_review_markdown(entries), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Large shifts reviewed: {len(entries)}")
    for entry in entries:
        flag = "OK" if entry["explainable"] else "REVIEW"
        print(
            f"  [{flag}] {entry['home']} vs {entry['away']}: "
            f"{entry['delta_home_win']:+.1f}pp ({entry['likely_explanation']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
