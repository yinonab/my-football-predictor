"""Phase 4R — Recent form data source + coverage audit (offline by default)."""

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

from core.recent_form_sources_audit import (  # noqa: E402
    audit_alias_probes,
    audit_team_coverage,
    api_football_capability_notes,
    build_source_inventory,
    football_data_api_capability_notes,
    load_tagged_matches,
    summarize_coverage,
)

REPORTS = BACKEND / "reports"


def _write_md(
    path: Path,
    inventory,
    coverage_rows,
    summary,
    alias_probes,
    fd_notes,
    af_notes,
) -> None:
    lines = [
        "# Recent Form Sources Audit (Phase 4R)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Offline audit — no live API required. Reports are gitignored.",
        "",
        "## Executive summary",
        "",
        f"- WC 2026 registry teams: **{summary['total_teams']}**",
        f"- High confidence (8–10 real-dated matches): **{summary['by_bucket']['high']}**",
        f"- Medium: **{summary['by_bucket']['medium']}**",
        f"- Low: **{summary['by_bucket']['low']}**",
        f"- Unavailable (0–2): **{summary['by_bucket']['unavailable']}**",
        f"- Teams with no data: **{', '.join(summary['no_data_teams']) or 'none'}**",
        "",
        "### Recommendation",
        "",
        _recommendation_text(summary),
        "",
        "## Data source inventory",
        "",
        "| Source | Matches | Teams | Dates | Role | Notes |",
        "|--------|---------|-------|-------|------|-------|",
    ]
    for row in inventory:
        lines.append(
            f"| {row.source_id} | {row.match_count} | {row.team_count} | "
            f"{row.date_type} | {row.recommended_use} | {row.notes or row.reliability} |"
        )

    lines.extend(
        [
            "",
            "## External API capability (offline notes)",
            "",
            "### football-data.org",
            "",
            "```json",
            json.dumps(fd_notes, indent=2),
            "```",
            "",
            "### API-Football (optional)",
            "",
            "```json",
            json.dumps(af_notes, indent=2),
            "```",
            "",
            "## Team alias probes",
            "",
            "| Probe | Resolved | Via NT_REGISTRY_ALIASES |",
            "|-------|----------|-------------------------|",
        ]
    )
    for probe in alias_probes:
        ok = "yes" if probe["ok"] else "**no**"
        lines.append(
            f"| {probe['probe_name']} | {ok} | {probe['via_nt_registry_aliases'] or '-'} |"
        )

    lines.extend(["", "## Per-team coverage (last 10 window)", ""])
    lines.append(
        "| Team | Usable | Real dates | Synthetic | Latest | Bucket | Sources |"
    )
    lines.append("|------|--------|------------|-----------|--------|--------|---------|")
    for row in coverage_rows:
        sources = ", ".join(f"{k}:{v}" for k, v in sorted(row.source_breakdown.items()))
        lines.append(
            f"| {row.english_name} | {row.usable_matches} | {row.real_date_matches} | "
            f"{row.synthetic_date_matches} | {row.latest_match_date or '-'} | "
            f"{row.confidence_bucket} | {sources or '-'} |"
        )

    lines.extend(["", "## Worst covered", ""])
    for item in summary["worst_covered"]:
        lines.append(f"- {item['team']}: {item['matches']} matches ({item['bucket']})")

    lines.extend(["", "## Best covered", ""])
    for item in summary["best_covered"]:
        lines.append(
            f"- {item['team']}: {item['matches']} matches, "
            f"{item['real_dates']} real-dated ({item['bucket']})"
        )

    lines.extend(["", "## Proposed schemas", "", _schema_section()])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _recommendation_text(summary: dict) -> str:
    high = summary["by_bucket"]["high"]
    unavail = summary["by_bucket"]["unavailable"]
    if high >= 30:
        return (
            "Static qualifiers + optional API cache may support 4R.1 store; "
            "still add API-backed cache (4R.2) for true last-10 recency."
        )
    if unavail >= 10:
        return (
            "Coverage is weak for many teams. Proceed to 4R.1 with diagnostics-only "
            "integration; prioritize 4R.2 API-backed cache before active gate influence."
        )
    return (
        "Proceed to **Phase 4R.1** (normalized offline store + diagnostics). "
        "Plan **4R.2** API-backed cache — static data alone is not enough for high-confidence last-10."
    )


def _schema_section() -> str:
    return """### Normalized match record

```text
date, team, opponent, goals_for, goals_against, competition,
source, source_priority, source_confidence, date_confidence,
is_home, is_neutral, opponent_power_proxy, opponent_strength_confidence, raw_source_id
```

### Cache file (`backend/data/cache/recent_form_cache.json`)

```json
{
  "schema_version": 1,
  "last_updated_utc": "ISO-8601",
  "sources": { "football-data.org": { "last_success_utc": "...", "status": "ok" } },
  "teams": {
    "Sweden": {
      "team": "Sweden",
      "normalized_team": "Sweden (שבדיה)",
      "last_updated_utc": "...",
      "source_priority": "api_cache_fresh",
      "source_confidence": "high",
      "matches": [ { "...": "..." } ]
    }
  }
}
```

### Source priority

1. Fresh API cache → 2. Stale API cache → 3. Real-dated static → 4. Synthetic static → 5. Unavailable

### Feature flags (proposed defaults)

| Flag | Default | Notes |
|------|---------|-------|
| RECENT_FORM_API_ENABLED | true if env key present | No key → static only |
| RECENT_FORM_LAZY_REFRESH_ENABLED | false | Phase 4R.3 |
| RECENT_FORM_AFFECTS_SCORELINE | false | Until QA after 4R.4 |
| RECENT_FORM_CACHE_TTL_HOURS | 24 | |
| RECENT_FORM_REFRESH_TIMEOUT_SECONDS | 3 | |
"""


def _write_csv(path: Path, coverage_rows) -> None:
    fieldnames = [
        "english_name",
        "registry_key",
        "usable_matches",
        "real_date_matches",
        "synthetic_date_matches",
        "matches_with_goals",
        "latest_match_date",
        "confidence_bucket",
        "only_synthetic_dates",
        "source_breakdown",
        "alias_resolution_ok",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in coverage_rows:
            writer.writerow(
                {
                    "english_name": row.english_name,
                    "registry_key": row.registry_key,
                    "usable_matches": row.usable_matches,
                    "real_date_matches": row.real_date_matches,
                    "synthetic_date_matches": row.synthetic_date_matches,
                    "matches_with_goals": row.matches_with_goals,
                    "latest_match_date": row.latest_match_date or "",
                    "confidence_bucket": row.confidence_bucket,
                    "only_synthetic_dates": row.only_synthetic_dates,
                    "source_breakdown": json.dumps(row.source_breakdown, ensure_ascii=False),
                    "alias_resolution_ok": row.alias_resolution_ok,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4R recent form sources audit")
    parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    tagged = load_tagged_matches()
    inventory = build_source_inventory()
    coverage = audit_team_coverage(tagged)
    summary = summarize_coverage(coverage)
    alias_probes = audit_alias_probes()
    fd_notes = football_data_api_capability_notes()
    af_notes = api_football_capability_notes()

    md_path = REPORTS / "recent_form_sources_audit.md"
    csv_path = REPORTS / "recent_form_sources_audit.csv"
    _write_md(md_path, inventory, coverage, summary, alias_probes, fd_notes, af_notes)
    _write_csv(csv_path, coverage)

    print(f"Wrote {md_path}")
    print(f"Wrote {csv_path}")
    print(f"Tagged matches: {len(tagged)}")
    print(
        "Coverage buckets: "
        f"high={summary['by_bucket']['high']} "
        f"medium={summary['by_bucket']['medium']} "
        f"low={summary['by_bucket']['low']} "
        f"unavailable={summary['by_bucket']['unavailable']}"
    )
    if summary["no_data_teams"]:
        print(f"No data: {', '.join(summary['no_data_teams'])}")


if __name__ == "__main__":
    main()
