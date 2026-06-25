"""OddsPapi client and weighted consensus tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.odds_consensus import weighted_consensus_from_lines
from core.odds_ensemble import BookmakerOddsLine
from core.oddspapi_client import OddsPapiClient, _outcome_label_cache, _tournament_cache
from core.odds_provider import UnifiedOddsClient


@pytest.fixture(autouse=True)
def _clear_oddspapi_caches() -> None:
    _tournament_cache.clear()
    _outcome_label_cache.clear()


def _line(
    book: str,
    home: float,
    draw: float,
    away: float,
) -> BookmakerOddsLine:
  implied = {
      "home_win": 100.0 / home,
      "draw": 100.0 / draw,
      "away_win": 100.0 / away,
  }
  total = sum(implied.values())
  implied = {k: round(v / total * 100.0, 2) for k, v in implied.items()}
  return BookmakerOddsLine(
      id=book,
      display_name=book,
      region="",
      home_decimal_odds=home,
      draw_decimal_odds=draw,
      away_decimal_odds=away,
      implied_1x2_percent=implied,
      source_key="oddspapi",
  )


def test_weighted_consensus_favors_sharp_books() -> None:
    soft = _line("smallbook", 4.0, 3.8, 1.9)
    sharp = _line("pinnacle", 5.5, 4.2, 1.55)
    plain = weighted_consensus_from_lines([soft, sharp])
    assert plain is not None
    # Sharp book has stronger away (Germany) — weighted away should exceed simple avg.
    simple_away = (soft.implied_1x2_percent["away_win"] + sharp.implied_1x2_percent["away_win"]) / 2
    assert plain["away_win"] > simple_away


def test_oddspapi_parses_fixture_and_swaps_home_away() -> None:
    fixture_path = BACKEND_ROOT / "tests" / "fixtures" / "oddspapi_wc_odds_sample.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    client = OddsPapiClient(api_key="test")

    with patch.object(client, "_load_tournament_odds", return_value=(fixtures, None)):
        result = client.lookup_match_market("Germany (גרמניה)", "Ecuador (אקוודור)")

    assert result.status == "ok"
    assert result.fetch is not None
    assert len(result.fetch.bookmakers) == 2
    assert result.fetch.consensus_1x2_percent is not None
    assert result.fetch.consensus_1x2_percent["home_win"] > 55


def test_unified_provider_prefers_oddspapi_then_fallback() -> None:
    from unittest.mock import MagicMock

    from core.odds_ensemble import OddsLookupResult, OddsMarketFetch

    oddspapi_fetch = OddsMarketFetch(
        sport_key="oddspapi:wc:16",
        bookmakers=[],
        consensus_1x2_percent={"home_win": 60.0, "draw": 22.0, "away_win": 18.0},
    )
    oddspapi_ok = OddsLookupResult(
        fetch=oddspapi_fetch,
        status="ok",
        odds_key_configured=True,
    )

    oddspapi = MagicMock()
    oddspapi.is_available = True
    oddspapi.lookup_match_market.return_value = oddspapi_ok

    the_odds = MagicMock()
    the_odds.lookup_match_market.return_value = OddsLookupResult(
        status="no_odds_for_matchup",
        odds_key_configured=True,
    )

    with patch("core.odds_provider.config.ODDS_PROVIDER", "auto"):
        client = UnifiedOddsClient(oddspapi=oddspapi, the_odds_api=the_odds)
        result = client.lookup_match_market("Germany", "Ecuador")

    assert result.status == "ok"
    assert result.fetch is not None
    assert result.fetch.sport_key.startswith("oddspapi")
    the_odds.lookup_match_market.assert_not_called()
