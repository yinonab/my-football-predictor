"""Tests for multiplicative de-vig utilities."""

from core.market_devig import devig_three_way, devig_two_way, multiplicative_devig


def test_h2h_three_way_devig_sums_to_100() -> None:
    outcomes, overround = devig_three_way(1.57, 3.90, 6.00)
    assert len(outcomes) == 3
    assert overround > 100.0
    total_fair = sum(o.fair_probability for o in outcomes)
    assert abs(total_fair - 100.0) < 0.05
    by_name = {o.name: o for o in outcomes}
    assert abs(by_name["home"].fair_probability - 60.08) < 0.1


def test_totals_two_way_devig() -> None:
    outcomes, overround = devig_two_way("over", 1.73, "under", 2.10)
    assert len(outcomes) == 2
    assert overround > 100.0
    assert abs(sum(o.fair_probability for o in outcomes) - 100.0) < 0.05


def test_spreads_two_way_devig() -> None:
    outcomes, _ = devig_two_way("home", 2.00, "away", 1.85)
    assert {o.name for o in outcomes} == {"home", "away"}
    assert abs(sum(o.fair_probability for o in outcomes) - 100.0) < 0.05


def test_btts_two_way_devig() -> None:
    outcomes, _ = devig_two_way("yes", 1.67, "no", 2.10)
    assert {o.name for o in outcomes} == {"yes", "no"}
    yes = next(o for o in outcomes if o.name == "yes")
    assert yes.raw_implied > 50.0


def test_multiplicative_devig_rejects_invalid_odds() -> None:
    outcomes, overround = multiplicative_devig([("a", 1.0), ("b", 0.5)])
    assert outcomes == []
    assert overround == 0.0
