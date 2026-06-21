"""Phase 4R.1 — normalized recent form store tests (offline)."""

from __future__ import annotations

from core.recent_match_history import (
    NormalizedRecentMatch,
    build_normalized_recent_match_history,
    get_team_recent_matches,
)
from core.recent_scoring_form import (
    RECENT_FORM_HIGH_CONFIDENCE,
    RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED,
    get_recent_scoring_form,
)
from core.recent_form_sources_audit import classify_confidence_bucket
from core.scoreline_decision import build_scoreline_decision
from core.underdog_goal_gate import compute_underdog_goal_gate
from data.database import FIFA_ELO_2026
from data.nt_match import registry_key_for_nt


def test_normalized_match_goals_per_team_side() -> None:
    history = build_normalized_recent_match_history(include_optional_caches=False)
    brazil_key = "Brazil (ברזיל)"
    rows = get_team_recent_matches(brazil_key, limit=5, history=history)
    assert rows
    for row in rows:
        assert row.team_registry_key == brazil_key
        assert row.goals_for >= 0
        assert row.goals_against >= 0
        assert row.source
        assert row.date_confidence in {"real", "synthetic", "unknown"}


def test_alias_democratic_republic_congo() -> None:
    key = registry_key_for_nt("Democratic Republic of the Congo", set(FIFA_ELO_2026.keys()))
    assert key == "DR Congo (קונגו)"


def test_alias_cote_divoire() -> None:
    key = registry_key_for_nt("Côte d'Ivoire", set(FIFA_ELO_2026.keys()))
    assert key == "Ivory Coast (חוף השנהב)"


def test_alias_bosnia_hyphen() -> None:
    key = registry_key_for_nt("Bosnia-Herzegovina", set(FIFA_ELO_2026.keys()))
    assert key == "Bosnia (בוסניה)"


def test_alias_ir_iran() -> None:
    key = registry_key_for_nt("IR Iran", set(FIFA_ELO_2026.keys()))
    assert key == "Iran (איראן)"


def test_alias_usa_still_works() -> None:
    key = registry_key_for_nt("United States", set(FIFA_ELO_2026.keys()))
    assert key == "USA (ארצות הברית)"


def test_dedupe_prefers_qualifier_over_synthetic() -> None:
    history = build_normalized_recent_match_history(include_optional_caches=False)
    # Brazil should have qualifier sources in breakdown when present
    form = get_recent_scoring_form("Brazil (ברזיל)", history=history)
    assert form.matches_found >= 3
    if "bundled_wc2026_qualifiers" in form.source_breakdown:
        assert form.source_breakdown["bundled_wc2026_qualifiers"] >= 1


def test_before_date_excludes_future_matches() -> None:
    injected = [
        NormalizedRecentMatch(
            date="2026-06-01",
            team="Brazil",
            opponent="France",
            goals_for=2,
            goals_against=1,
            competition="test",
            source="test",
            source_priority="static_real_dated",
            source_confidence="medium",
            date_confidence="real",
            is_home=None,
            is_neutral=True,
            team_registry_key="Brazil (ברזיל)",
            opponent_registry_key="France (צרפת)",
        ),
        NormalizedRecentMatch(
            date="2026-07-01",
            team="Brazil",
            opponent="Argentina",
            goals_for=1,
            goals_against=0,
            competition="test",
            source="test",
            source_priority="static_real_dated",
            source_confidence="medium",
            date_confidence="real",
            is_home=None,
            is_neutral=True,
            team_registry_key="Brazil (ברזיל)",
            opponent_registry_key="Argentina (ארגנטינה)",
        ),
    ]
    rows = get_team_recent_matches(
        "Brazil (ברזיל)",
        before_date="2026-06-15",
        limit=10,
        history=injected,
    )
    assert len(rows) == 1
    assert rows[0].date == "2026-06-01"


def test_scored_rate_metrics() -> None:
    injected = [
        NormalizedRecentMatch(
            date=f"2026-01-{i:02d}",
            team="Haiti",
            opponent="X",
            goals_for=1 if i % 2 else 0,
            goals_against=0,
            competition="test",
            source="test",
            source_priority="static_real_dated",
            source_confidence="medium",
            date_confidence="real",
            is_home=None,
            is_neutral=True,
            team_registry_key="Haiti (האיטי)",
        )
        for i in range(1, 8)
    ]
    form = get_recent_scoring_form("Haiti (האיטי)", matches=injected)
    assert form.recent_form_available is True
    assert form.scored_matches == 4
    assert form.failed_to_score_matches == 3
    assert form.last_10_scored_rate == round(4 / 7, 3)


def test_confidence_high_requires_real_dates() -> None:
    assert classify_confidence_bucket(10, 10, 0) == "high"
    assert classify_confidence_bucket(10, 5, 5) == "medium"


def test_confidence_unavailable() -> None:
    form = get_recent_scoring_form("Haiti (האיטי)", matches=[])
    assert form.recent_form_confidence == "unavailable"


def test_opponent_strength_proxy_reason_code() -> None:
    history = build_normalized_recent_match_history(include_optional_caches=False)
    form = get_recent_scoring_form(
        "Netherlands (הולנד)",
        favorite_power=900.0,
        history=history,
    )
    if form.recent_form_available:
        assert (
            RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED in form.reason_codes
            or "RECENT_FORM_OPPONENT_STRENGTH_UNAVAILABLE" in form.reason_codes
        )


def test_gate_diagnostics_include_store_fields() -> None:
    from core.underdog_goal_gate import build_underdog_match_context

    ctx = build_underdog_match_context(
        favorite_outcome="home_win",
        probabilities_1x2={"home_win": 62.0, "draw": 22.0, "away_win": 16.0},
        home_team="Netherlands",
        away_team="Sweden",
        home_xg=1.9,
        away_xg=0.75,
        favorite_power=900.0,
        underdog_power=700.0,
        power_gap=200.0,
    )
    assert ctx is not None
    gate = compute_underdog_goal_gate(
        underdog_ctx=ctx,
        underdog_scores_probability=55.0,
        btts_probability=48.0,
    )
    payload = gate.to_dict()
    assert "recent_form_source_breakdown" in payload
    assert "recent_form_reason_codes" in payload


def test_scoreline_primary_unchanged_representative_gate() -> None:
    """Regression: primary selection policy unchanged (4Q.1)."""
    from core.math_engine import AdvancedDixonColesEngine

    engine = AdvancedDixonColesEngine(alpha=0.0)
    result = engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=5,
        home_xg_override=1.81,
        away_xg_override=0.79,
    )
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 60.5, "draw": 24.2, "away_win": 15.3},
        top_scores=result["top_scores"],
        all_scores=result["all_scores"],
        home_xg=1.81,
        away_xg=0.79,
        home_team="Netherlands",
        away_team="Sweden",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label in {"2-0", "1-0", "2-1"}
    assert decision.representative_score_method == "representative_v2_composite"
