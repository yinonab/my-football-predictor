"""Persist Elo overrides across server restarts."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "elo_overrides.json"


def load_elo_overrides() -> dict[str, float]:
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
