#!/usr/bin/env python3
"""Smoke test baseline vs simulated active candidate via local TestClient (Phase 3C)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.activation_qa import load_activation_qa_matchups


def _force_offline_external_services() -> None:
    """
    Smoke runs must not depend on API-Football / odds providers.
    Phase 4L fixture-state resolution adds per-predict API lookups; without this,
    a suspended key causes multi-minute hangs across QA matchups.
    """
    from api import main as api_main
    from core.fixture_state_resolver import FixtureStateResolver
    from core.match_context import MatchContextGatherer
    from core.odds_ensemble import OddsClient

    offline_api = MagicMock()
    offline_api.is_available = False
    api_main._api_client = offline_api
    api_main._fixture_state_resolver = FixtureStateResolver(offline_api)
    api_main._context_gatherer = MatchContextGatherer(offline_api)
    api_main._odds_client = OddsClient(api_key="")


def _client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


def _predict_payload(home: str, away: str) -> dict:
    return {"home_team": home, "away_team": away, "neutral_ground": True}


def main() -> int:
    _force_offline_external_services()
    matchups, skipped = load_activation_qa_matchups()
    client = _client()
    errors: list[str] = []

    print("Smoke predict — baseline (default flags)\n")
    for matchup in matchups:
        r = client.post("/api/predict", json=_predict_payload(matchup.home, matchup.away))
        if r.status_code != 200:
            errors.append(f"baseline {matchup.home} vs {matchup.away}: HTTP {r.status_code}")
            continue
        body = r.json()
        md = body.get("model_diagnostics") or {}
        if md.get("model_version") != config.BASELINE_MODEL_VERSION:
            errors.append(
                f"baseline version {matchup.home} vs {matchup.away}: {md.get('model_version')}"
            )
        probs = body["probabilities_1x2"]
        total = probs["home_win"] + probs["draw"] + probs["away_win"]
        if abs(total - 100.0) > 0.5:
            errors.append(f"baseline probs sum {matchup.home} vs {matchup.away}: {total}")
        if not body.get("top_scores"):
            errors.append(f"baseline missing top_scores: {matchup.home} vs {matchup.away}")

    print(f"baseline checked: {len(matchups)} matchups")

    print("\nSmoke predict — active candidate (simulated flags)\n")
    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        for matchup in matchups:
            r = client.post(
                "/api/predict",
                json=_predict_payload(matchup.home, matchup.away),
            )
            if r.status_code != 200:
                errors.append(f"active {matchup.home} vs {matchup.away}: HTTP {r.status_code}")
                continue
            body = r.json()
            md = body.get("model_diagnostics") or {}
            if md.get("model_version") != config.ACTIVE_MODEL_VERSION:
                errors.append(
                    f"active version {matchup.home} vs {matchup.away}: {md.get('model_version')}"
                )
            if md.get("fallback_to_baseline"):
                errors.append(
                    f"active fallback {matchup.home} vs {matchup.away}: {md.get('fallback_reasons')}"
                )
            if not md.get("activation_enabled"):
                errors.append(f"activation not enabled: {matchup.home} vs {matchup.away}")
            probs = body["probabilities_1x2"]
            total = probs["home_win"] + probs["draw"] + probs["away_win"]
            if abs(total - 100.0) > 0.5:
                errors.append(f"active probs sum {matchup.home} vs {matchup.away}: {total}")
            if not body.get("top_scores"):
                errors.append(f"active missing top_scores: {matchup.home} vs {matchup.away}")

    print(f"active checked: {len(matchups)} matchups")
    if skipped:
        print(f"skipped (from QA file): {len(skipped)}")

    if errors:
        print("\nFAILURES:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nPASS — all QA matchups OK (baseline + simulated active)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
