"""Phase 4R.1/4R.2/4R.3 — Normalized recent form store coverage audit (offline)."""

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

from core.football_data_recent_form import (  # noqa: E402
    cache_age_hours,
    load_recent_form_cache,
)
from core.recent_form_fusion import (  # noqa: E402
    cache_age_hours as fusion_cache_age_hours,
    fusion_match_to_normalized,
    get_fusion_cache_status,
    load_fusion_cache,
    load_fusion_cache_rows,
    summarize_sofascore_fusion_coverage,
)
from core.recent_form_sources_audit import classify_confidence_bucket  # noqa: E402
from core.recent_match_history import (  # noqa: E402
    NormalizedRecentMatch,
    _dedupe_rows,
    _sort_rows,
    build_normalized_recent_match_history,
    get_recent_form_cache_status,
    get_recent_match_coverage_summary,
)
from core.recent_scoring_form import get_recent_scoring_form  # noqa: E402
from data.database import FIFA_ELO_2026  # noqa: E402
from data.nt_match import registry_key_for_nt  # noqa: E402

REPORTS = BACKEND / "reports"
REGISTRY = set(FIFA_ELO_2026.keys())

FOCUS_TEAMS = (
    "New Zealand",
    "Haiti",
    "Curacao",
    "Cape Verde",
    "Ivory Coast",
    "Norway",
    "Sweden",
    "Netherlands",
    "Japan",
    "Canada",
    "Brazil",
    "Morocco",
)


def _provider_history_from_fusion(provider: str) -> list[NormalizedRecentMatch]:
    """Offline slice: one provider's candidates from fusion cache file."""
    payload, _ = load_fusion_cache()
    if not payload:
        return []
    rows: list[NormalizedRecentMatch] = []
    for entry in (payload.get("teams") or {}).values():
        if not isinstance(entry, dict):
            continue
        for raw in entry.get("candidates") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("provider") or "") != provider:
                continue
            try:
                rows.append(fusion_match_to_normalized(raw))
            except (KeyError, TypeError, ValueError):
                continue
    return _sort_rows(_dedupe_rows(rows))


def _bucket_counts(history) -> dict[str, int]:
    coverage = get_recent_match_coverage_summary(history=history)
    buckets = {"high": 0, "medium": 0, "low": 0, "unavailable": 0}
    for cov in coverage:
        bucket = classify_confidence_bucket(
            cov.matches_found,
            cov.real_dated_matches,
            cov.synthetic_dated_matches,
        )
        buckets[bucket] += 1
    return buckets


def _audit_rows(history, *, label: str) -> list[dict]:
    coverage = get_recent_match_coverage_summary(history=history)
    rows: list[dict] = []
    for cov in coverage:
        form = get_recent_scoring_form(cov.team_registry_key, history=history)
        bucket = classify_confidence_bucket(
            cov.matches_found,
            cov.real_dated_matches,
            cov.synthetic_dated_matches,
        )
        fd_count = cov.source_breakdown.get("recent_form_cache_football_data", 0)
        fusion_count = cov.source_breakdown.get("recent_form_fusion_cache", 0)
        rows.append(
            {
                "audit_label": label,
                "english_name": cov.english_name,
                "registry_key": cov.team_registry_key,
                "matches_found": cov.matches_found,
                "real_dated_matches": cov.real_dated_matches,
                "synthetic_dated_matches": cov.synthetic_dated_matches,
                "football_data_matches": fd_count,
                "fusion_cache_matches": fusion_count,
                "api_football_matches": 0,
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


def _enrich_apif_counts(rows: list[dict], apif_history: list[NormalizedRecentMatch]) -> None:
    by_team: dict[str, int] = {}
    for row in apif_history:
        key = row.team_registry_key or row.team
        by_team[key] = by_team.get(key, 0) + 1
    for r in rows:
        if r["audit_label"] != "api_football_only":
            continue
        reg = r["registry_key"]
        r["api_football_matches"] = by_team.get(reg, 0)
        r["matches_found"] = by_team.get(reg, 0)


def _write_md(
    path: Path,
    rows: list[dict],
    *,
    bucket_matrix: dict[str, dict[str, int]],
    cache_meta: dict,
    fusion_meta: dict,
    improved: dict[str, list[str]],
    sofascore_summary: dict | None = None,
) -> None:
    lines = [
        "# Recent Form Store Audit (Phase 4R.3)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Cache status",
        "",
        f"- football-data cache found: **{cache_meta.get('cache_found', False)}**",
        f"- football-data rows: **{cache_meta.get('cache_row_count', 0)}**",
        f"- fusion cache found: **{fusion_meta.get('cache_found', False)}**",
        f"- fusion rows: **{fusion_meta.get('cache_row_count', 0)}**",
    ]
    if sofascore_summary:
        lines.extend(
            [
                "",
                "## Sofascore fusion coverage (offline)",
                "",
                f"- teams with `provider_ids.sofascore`: **{sofascore_summary.get('teams_with_sofascore_id', 0)}**",
                f"- sofascore candidate rows: **{sofascore_summary.get('sofascore_candidate_rows', 0)}**",
                f"- finished sofascore rows: **{sofascore_summary.get('finished_match_rows', 0)}**",
                f"- rows with has_xg: **{sofascore_summary.get('matches_with_has_xg', 0)}**",
                f"- source_mix sofascore_recent_form: **{sofascore_summary.get('source_mix_sofascore', 0)}**",
                f"- missing sofascore mappings: **{len(sofascore_summary.get('missing_sofascore_mappings') or [])}**",
            ]
        )

    lines.extend(["", "## Coverage buckets by mode", ""])
    headers = ["Bucket", "Static", "FD only", "API-F only", "Fused"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for bucket in ("high", "medium", "low", "unavailable"):
        cells = [bucket]
        for mode in ("static_only", "football_data_only", "api_football_only", "fused"):
            cells.append(str(bucket_matrix.get(mode, {}).get(bucket, 0)))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Improvements vs static-only", ""])
    for mode, teams in improved.items():
        lines.append(f"### {mode}")
        lines.append(", ".join(teams[:20]) or "none")
        lines.append("")

    lines.extend(["", "## Focus teams (fused)", ""])
    lines.append("| Team | Matches | Fusion | Bucket | Scored rate |")
    lines.append("|------|---------|--------|--------|-------------|")
    focus_set = set(FOCUS_TEAMS)
    for row in sorted(rows, key=lambda r: r["english_name"]):
        if row["english_name"] not in focus_set or row["audit_label"] != "fused":
            continue
        lines.append(
            f"| {row['english_name']} | {row['matches_found']} | {row['fusion_cache_matches']} | "
            f"{row['confidence_bucket']} | {row['last_10_scored_rate']} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4R.3 normalized store audit")
    parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    static_history = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_recent_form_cache=False,
        include_fusion_cache=False,
    )
    fd_history = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_recent_form_cache=True,
        include_fusion_cache=False,
    )
    apif_history = _provider_history_from_fusion("api_football_recent_form")
    fused_history = build_normalized_recent_match_history(
        include_optional_caches=False,
        include_recent_form_cache=False,
        include_fusion_cache=True,
    )

    histories = {
        "static_only": static_history,
        "football_data_only": fd_history,
        "api_football_only": apif_history,
        "fused": fused_history,
    }

    bucket_matrix = {label: _bucket_counts(h) for label, h in histories.items()}

    all_rows: list[dict] = []
    for label, history in histories.items():
        all_rows.extend(_audit_rows(history, label=label))

    _enrich_apif_counts(all_rows, apif_history)

    static_by_name = {r["english_name"]: r for r in all_rows if r["audit_label"] == "static_only"}
    improved: dict[str, list[str]] = {}
    for mode in ("football_data_only", "api_football_only", "fused"):
        improved[mode] = []
        for row in all_rows:
            if row["audit_label"] != mode:
                continue
            prev = static_by_name.get(row["english_name"], {})
            if row["matches_found"] > prev.get("matches_found", 0):
                improved[mode].append(row["english_name"])

    cache_meta = get_recent_form_cache_status()
    cache_payload, _ = load_recent_form_cache()
    if cache_payload:
        cache_meta["cache_age_hours"] = cache_age_hours(cache_payload)

    fusion_meta = get_fusion_cache_status()
    fusion_payload, _ = load_fusion_cache()
    fusion_rows, fusion_load_meta = load_fusion_cache_rows()
    fusion_meta.update(fusion_load_meta)
    if fusion_payload:
        fusion_meta["cache_age_hours"] = fusion_cache_age_hours(fusion_payload)

    sofascore_summary = summarize_sofascore_fusion_coverage(fusion_payload)

    md_path = REPORTS / "recent_form_store_audit.md"
    csv_path = REPORTS / "recent_form_store_audit.csv"
    _write_md(
        md_path,
        all_rows,
        bucket_matrix=bucket_matrix,
        cache_meta=cache_meta,
        fusion_meta=fusion_meta,
        improved=improved,
        sofascore_summary=sofascore_summary,
    )
    fused_rows = [r for r in all_rows if r["audit_label"] == "fused"]
    _write_csv(csv_path, fused_rows)

    print(f"Wrote {md_path}")
    print(f"Wrote {csv_path}")
    for mode, buckets in bucket_matrix.items():
        print(f"{mode} buckets: {buckets}")
    print(f"FD cache: found={cache_meta.get('cache_found')} rows={cache_meta.get('cache_row_count', 0)}")
    print(f"Fusion cache: found={fusion_meta.get('cache_found')} rows={fusion_meta.get('cache_row_count', 0)}")
    print(
        "Sofascore: "
        f"teams_with_id={sofascore_summary.get('teams_with_sofascore_id', 0)} "
        f"candidates={sofascore_summary.get('sofascore_candidate_rows', 0)} "
        f"has_xg={sofascore_summary.get('matches_with_has_xg', 0)}"
    )


if __name__ == "__main__":
    main()
