"""Unified odds lookup — OddsPapi primary, The Odds API fallback."""

from __future__ import annotations

import config
from core.oddspapi_client import OddsPapiClient
from core.odds_ensemble import OddsClient, OddsLookupResult


class UnifiedOddsClient:
    """Route market requests to configured odds providers."""

    def __init__(
        self,
        *,
        oddspapi: OddsPapiClient | None = None,
        the_odds_api: OddsClient | None = None,
    ) -> None:
        self._oddspapi = oddspapi or OddsPapiClient()
        self._the_odds_api = the_odds_api or OddsClient()

    @property
    def is_available(self) -> bool:
        return self._oddspapi.is_available or self._the_odds_api.is_available

    def lookup_match_market(
        self,
        home_team: str,
        away_team: str,
    ) -> OddsLookupResult:
        mode = config.ODDS_PROVIDER.strip().lower()
        notes: list[str] = []

        if mode in ("auto", "oddspapi"):
            result = self._oddspapi.lookup_match_market(home_team, away_team)
            if result.status == "ok" and result.fetch is not None:
                return result
            if mode == "oddspapi":
                return result
            notes.extend(result.notes)

        if mode in ("auto", "the_odds_api", "the-odds-api"):
            fallback = self._the_odds_api.lookup_match_market(home_team, away_team)
            if fallback.status == "ok":
                if notes:
                    fallback.notes = notes + [
                        "Fell back to The Odds API for this matchup"
                    ] + list(fallback.notes)
                return fallback
            if notes:
                fallback.notes = notes + list(fallback.notes)
            return fallback

        return OddsLookupResult(
            status="not_configured",
            notes=["ODDS_PROVIDER not configured (use auto|oddspapi|the_odds_api)"],
            odds_key_configured=False,
        )

    def fetch_match_market(self, home_team: str, away_team: str):
        return self.lookup_match_market(home_team, away_team).fetch

    def fetch_match_odds(self, home_team: str, away_team: str):
        fetch = self.fetch_match_market(home_team, away_team)
        if fetch is None:
            return None
        return fetch.legacy_consensus_percent()


def create_odds_client() -> UnifiedOddsClient:
    return UnifiedOddsClient()
