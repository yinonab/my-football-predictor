#!/usr/bin/env python3
"""Smoke test activation rollback — enabled then disabled (Phase 3E)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.release_readiness import ROLLBACK_SAMPLE_MATCHUP, run_activation_rollback_smoke


def main() -> int:
    home, away = ROLLBACK_SAMPLE_MATCHUP
    result = run_activation_rollback_smoke(home, away)
    details = result.details

    print("Activation rollback smoke (Phase 3E)\n")
    print(f"matchup: {details.get('matchup')}")
    print(f"enabled model_version: {details.get('enabled_model_version')}")
    print(f"disabled model_version: {details.get('disabled_model_version')}")
    print(f"expected active: {config.ACTIVE_MODEL_VERSION}")
    print(f"expected baseline: {config.BASELINE_MODEL_VERSION}")

    if result.passed:
        print("\nPASS — rollback immediate; no persisted active state")
        return 0

    print("\nFAILURES:")
    for err in result.errors:
        print(f"  - {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
