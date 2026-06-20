"""Phase 4R — tests for recent form source audit helpers (offline)."""

from __future__ import annotations

from core.recent_form_sources_audit import (
    TaggedMatch,
    audit_alias_probes,
    audit_team_coverage,
    classify_confidence_bucket,
    load_tagged_matches,
    summarize_coverage,
)
from data.database import FIFA_ELO_2026
from data.nt_match import NationalTeamMatch


def test_classify_confidence_bucket_high() -> None:
    assert classify_confidence_bucket(10, 10, 0) == "high"


def test_classify_confidence_bucket_mixed_dates() -> None:
    assert classify_confidence_bucket(10, 5, 5) == "medium"


def test_classify_confidence_bucket_unavailable() -> None:
    assert classify_confidence_bucket(2, 2, 0) == "unavailable"


def test_load_tagged_matches_includes_bundled_layers() -> None:
    tagged = load_tagged_matches(include_optional_caches=False)
    source_ids = {tm.source_id for tm in tagged}
    assert "bundled_wc2018" in source_ids
    assert "bundled_wc2026_qualifiers" in source_ids
    assert len(tagged) >= 300


def test_qualifier_matches_tagged_real_dates() -> None:
    tagged = load_tagged_matches(include_optional_caches=False)
    qual = [tm for tm in tagged if tm.source_id == "bundled_wc2026_qualifiers"]
    assert qual
    assert all(tm.date_confidence == "real" for tm in qual)


def test_audit_team_coverage_finds_brazil_history() -> None:
    rows = audit_team_coverage(load_tagged_matches(include_optional_caches=False))
    brazil = next(r for r in rows if r.english_name == "Brazil")
    assert brazil.usable_matches >= 3
    assert brazil.confidence_bucket in {"low", "medium", "high", "unavailable"}


def test_haiti_qualifier_match_counted() -> None:
    """Haiti appears in qualifiers; should not be zero despite non-registry opponents."""
    rows = audit_team_coverage(load_tagged_matches(include_optional_caches=False))
    haiti = next(r for r in rows if r.english_name == "Haiti")
    assert haiti.usable_matches >= 1
    assert "bundled_wc2026_qualifiers" in haiti.source_breakdown


def test_alias_probe_usa_resolves() -> None:
    probes = audit_alias_probes()
    usa = next(p for p in probes if p["probe_name"] == "USA")
    assert usa["ok"] is True


def test_alias_probe_ir_iran_missing() -> None:
    probes = audit_alias_probes()
    ir = next(p for p in probes if p["probe_name"] == "IR Iran")
    assert ir["ok"] is True


def test_summarize_coverage_structure() -> None:
    rows = audit_team_coverage(load_tagged_matches(include_optional_caches=False))
    summary = summarize_coverage(rows)
    assert summary["total_teams"] == len(FIFA_ELO_2026)
    assert set(summary["by_bucket"]) == {"high", "medium", "low", "unavailable"}


def test_before_date_window_with_injected_matches() -> None:
    registry_key = "Brazil (ברזיל)"
    injected = [
        TaggedMatch(
            NationalTeamMatch(
                date="2026-06-01",
                home="Brazil",
                away="France",
                home_goals=2,
                away_goals=1,
                competition="test",
            ),
            "test",
            "real",
            "active_model",
        ),
        TaggedMatch(
            NationalTeamMatch(
                date="2026-06-15",
                home="Brazil",
                away="Argentina",
                home_goals=1,
                away_goals=1,
                competition="test",
            ),
            "test",
            "real",
            "active_model",
        ),
    ]
    rows = audit_team_coverage(injected, window=10)
    brazil = next(r for r in rows if r.registry_key == registry_key)
    assert brazil.usable_matches == 2
    assert brazil.latest_match_date == "2026-06-15"
