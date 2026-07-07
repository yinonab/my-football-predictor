"""Persist Elo overrides across server restarts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "elo_overrides.json"

# When set (e.g. by calibration audit scripts), skip local overrides for FIFA/production parity.
_PRODUCTION_PARITY_BASELINES = frozenset({"production", "fifa"})


def audit_elo_baseline_production_parity() -> bool:
    """True when AUDIT_ELO_BASELINE requests FIFA baseline (no local overrides)."""
    return os.getenv("AUDIT_ELO_BASELINE", "").strip().lower() in _PRODUCTION_PARITY_BASELINES


def load_elo_overrides() -> dict[str, float]:
    if audit_elo_baseline_production_parity():
        return {}
    if not STORE_PATH.exists():
        return {}
    try:
        payload = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in payload.get("teams", {}).items()}
    except Exception as exc:
        logger.warning("Failed to load elo overrides: %s", exc)
        return {}


def save_elo_overrides(overrides: dict[str, float]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"version": 1, "teams": overrides}
    STORE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        from core.cloud_persist import push_file

        push_file(STORE_PATH)
    except Exception:
        pass
