"""Phase 4R.1 — Normalized recent form store coverage audit (offline)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.recent_form_sources_audit import classify_confidence_bucket  # noqa: E402
from core.recent_match_history import (  # noqa: E402
    build_normalized_recent_match_history,
    get_recent_match_coverage_summary,
)
from core.recent_scoring_form import get_recent_scoring_form  # noqa: E402
from data.database import FIFA_ELO_2026  # noqa: E402
from data.nt_match import registry_key_for_nt  # noqa: E402

REPORTS = BACKEND / "reports"
REGISTRY = set(FIFA_ELO_2026.keys())

EXAMPLE_TEAMS = (
    "Brazil (ברזיל)",
    "Haiti (האיטי)",
    "Netherlands (הולנד)",
    "Sweden (שבדיה)",
    "Tunisia (תוניסיה)",
    "Japan (יפן)",
    "Switzerland (שוויץ)",
    "Canada (קנדה)",
    "USA (ארצות הברית)",
    "Australia (אוסטרליה)",
)


def _audit_rows(history) -> list[dict]:
    coverage = get_recent_match_coverage_summary(history=history)
    rows: list[dict] = []
    for cov in coverage:
        form = get_recent_scoring_form(cov.team_registry_key, history=history)
        bucket = classify_confidence_bucket(
            cov.matches_found,
            cov.real_dated_matches,
            cov.synthetic_dated_matches,
        )
        rows.append(
            {
                "english_name": cov.english_name,
                "registry_key": cov.team_registry_key,
                "matches_found": cov.matches_found,
                "real_dated_matches": cov.real_dated_matches,
                "synthetic_dated_matches": cov.synthetic_dated_matches,
                "latest_match_date": cov.latest_match_date or "",
                "confidence_bucket": bucket,
                "recent_form_confidence": form.recent_form_confidence,
                "last_10_scored_rate": form.last_10_scored_rate,
                "last_10_goals_for_avg": form.last_10_goals_for_avg,
                "last_10_failed_to_score_rate": form.last_10_failed_to_score_rate,
                "recent_form_source": form.recent_form_source or "",
                "source_breakdown": json.dumps(cov.source_breakdown, ensure_ascii=False),
                "only_synthetic_dates": cov.only_synthetic_dates,
                "opponent_strength_proxy_available": cov.opponent_strength_proxy_available,
                "alias_ok": registry_key_for_nt(cov.english_name, REGISTRY) is not None,
                "reason_codes": "|".join(form.reason_codes or []),
            }
        )
    return rows


def _write_md(path: Path, rows: list[dict], examples: list[dict]) -> None:
    buckets = {"high": 0, "medium": 0, "low": 0, "unavailable": 0}
    for row in rows:
        buckets[row["confidence_bucket"]] += 1

    lines = [
        "# Recent Form Store Audit (Phase 4R.1)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Normalized offline store — no live API.",
        "",
        "## Summary",
        "",
        f"- Teams: **{len(rows)}**",
        f"- High: **{buckets['high']}** | Medium: **{buckets['medium']}** | "
        f"Low: **{buckets['low']}** | Unavailable: **{buckets['unavailable']}**",
        "",
        "## Example team metrics",
        "",
        "| Team | Matches | Conf | Scored rate | GF avg | Failed rate | Source |",
        "|------|---------|------|-------------|--------|-------------|--------|",
    ]
    for ex in examples:
        lines.append(
            f"| {ex['english_name']} | {ex['matches_found']} | {ex['recent_form_confidence']} | "
            f"{ex['last_10_scored_rate']} | {ex['last_10_goals_for_avg']} | "
            f"{ex['last_10_failed_to_score_rate']} | {ex['recent_form_source']} |"
        )

    lines.extend(["", "## All teams", ""])
    lines.append(
        "| Team | Found | Real | Synth | Latest | Bucket | Scored% | GF avg | Opp proxy |"
    )
    lines.append("|------|-------|------|-------|--------|--------|---------|--------|-----------|")
    for row in sorted(rows, key=lambda r: r["english_name"]):
        lines.append(
            f"| {row['english_name']} | {row['matches_found']} | {row['real_dated_matches']} | "
            f"{row['synthetic_dated_matches']} | {row['latest_match_date']} | "
            f"{row['confidence_bucket']} | {row['last_10_scored_rate']} | "
            f"{row['last_10_goals_for_avg']} | {row['opponent_strength_proxy_available']} |"
        )

    no_data = [r["english_name"] for r in rows if r["matches_found"] == 0]
    low_cov = [r["english_name"] for r in rows if r["confidence_bucket"] in {"low", "unavailable"}]
    synth_only = [r["english_name"] for r in rows if r["only_synthetic_dates"]]

    lines.extend(["", "## No data", "", ", ".join(no_data) or "none"])
    lines.extend(["", "## Low/unavailable coverage", "", ", ".join(low_cov) or "none"])
    lines.extend(["", "## Synthetic-only last-10", "", ", ".join(synth_only) or "none"])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4R.1 normalized store audit")
    parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    history = build_normalized_recent_match_history(include_optional_caches=False)
    rows = _audit_rows(history)
    examples = [r for r in rows if r["registry_key"] in EXAMPLE_TEAMS]

    md_path = REPORTS / "recent_form_store_audit.md"
    csv_path = REPORTS / "recent_form_store_audit.csv"
    _write_md(md_path, rows, examples)
    _write_csv(csv_path, rows)

    buckets = {}
    for row in rows:
        buckets[row["confidence_bucket"]] = buckets.get(row["confidence_bucket"], 0) + 1

    print(f"Wrote {md_path}")
    print(f"Wrote {csv_path}")
    print(f"Normalized rows: {len(history)}")
    print(f"Coverage buckets: {buckets}")
    for ex in examples:
        print(
            f"  {ex['english_name']}: matches={ex['matches_found']} "
            f"scored_rate={ex['last_10_scored_rate']} conf={ex['recent_form_confidence']}"
        )


if __name__ == "__main__":
    main()
