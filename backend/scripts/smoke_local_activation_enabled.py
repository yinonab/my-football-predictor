#!/usr/bin/env python3
"""Smoke test simulated local activation enabled via TestClient (Phase 3E)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.active_model_activation import SAMPLE_PRODUCTION_MATCHUPS
from core.release_readiness import run_local_activation_enabled_smoke


def main() -> int:
    result = run_local_activation_enabled_smoke(SAMPLE_PRODUCTION_MATCHUPS)
    print("Local activation enabled smoke (Phase 3E)\n")
    print(f"matchups: {result.details.get('matchups_checked', 0)}")
    print(f"MODEL_ACTIVATION_ENABLED simulated: true")
    print(f"POWER_CANDIDATE_AFFECTS_PREDICTION simulated: true")
    print(f"expected model_version: {config.ACTIVE_MODEL_VERSION}")

    if result.passed:
        print("\nPASS — enabled smoke OK (no fallback, probs/xG/top_scores valid)")
        return 0

    print("\nFAILURES:")
    for err in result.errors:
        print(f"  - {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
