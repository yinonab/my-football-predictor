#!/usr/bin/env python3
"""Local QA report — baseline vs simulated active FIFA-points candidate (Phase 3C)."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.activation_qa import (
    WARNING_BALANCED_MATCH_SHIFT,
    WARNING_FAVORITE_DIRECTION_REVERSED,
    WARNING_LARGE_CANDIDATE_SHIFT,
    analyze_prediction_result,
    format_qa_markdown,
    format_qa_summary_text,
    load_activation_qa_matchups,
    summarize_qa_analyses,
)
from core.active_model_activation import run_prediction_with_active_candidate
from core.opponent_maher import build_opponent_index
from core.team_ratings import build_all_matches
from data.database import FIFA_ELO_2026, LiveDataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Activation QA report for WC 2026 matchups.")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--only-large-shifts", action="store_true")
    parser.add_argument("--large-shift-pp", type=float, default=7.0)
    parser.add_argument("--only-fallbacks", action="store_true")
    parser.add_argument(
        "--sort",
        choices=["abs_delta", "category", "home"],
        default="abs_delta",
    )
    return parser.parse_args()


def _sort_analyses(analyses: list, sort_key: str) -> list:
    if sort_key == "category":
        return sorted(analyses, key=lambda a: (a.category, a.home, a.away))
    if sort_key == "home":
        return sorted(analyses, key=lambda a: (a.home, a.away))
    return sorted(analyses, key=lambda a: abs(a.delta_home_win), reverse=True)


def _filter_analyses(analyses: list, args: argparse.Namespace) -> list:
    rows = analyses
    if args.only_fallbacks:
        rows = [a for a in rows if a.fallback]
    if args.only_large_shifts:
        rows = [
            a
            for a in rows
            if abs(a.delta_home_win) > args.large_shift_pp
            or WARNING_LARGE_CANDIDATE_SHIFT in a.warnings
        ]
    return rows


def main() -> None:
    args = parse_args()
    matchups, skipped = load_activation_qa_matchups()
    dm = LiveDataManager()
    opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    analyses = []
    for matchup in matchups:
        home_key, _ = dm.resolve_team(matchup.home)
        away_key, _ = dm.resolve_team(matchup.away)
        out = run_prediction_with_active_candidate(
            home_key,
            away_key,
            data_manager=dm,
            opponent_index=opp_idx,
            force_enable=True,
        )
        analyses.append(
            analyze_prediction_result(
                matchup,
                out,
                large_shift_pp=args.large_shift_pp,
            )
        )

    summary = summarize_qa_analyses(analyses, skipped=skipped)
    display_rows = _sort_analyses(_filter_analyses(analyses, args), args.sort)

    header = (
        "category | home | away | baseline_H | active_H | delta_H | shift | "
        "fallback | warnings | model_version"
    )
    print("Activation QA report\n")
    print(format_qa_summary_text(summary))
    print(f"\n{header}")
    print("-" * len(header))
    for row in display_rows:
        warn = ",".join(row.warnings) if row.warnings else "-"
        print(
            f"{row.category} | {row.home} | {row.away} | "
            f"{row.baseline_home_win:5.1f} | {row.active_home_win:5.1f} | "
            f"{row.delta_home_win:+5.1f} | {row.shift_class} | {row.fallback} | "
            f"{warn} | {row.model_version_active}"
        )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(analyses[0].to_row().keys()))
            writer.writeheader()
            for row in _sort_analyses(analyses, args.sort):
                writer.writerow(row.to_row())
        print(f"\nWrote {args.csv}")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(
            format_qa_markdown(analyses, summary),
            encoding="utf-8",
        )
        print(f"Wrote {args.markdown}")

    if summary.fallback_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
