"""Optional cloud backup for cache files (survives Render free redeploys).

Uses a private GitHub Gist when GITHUB_GIST_TOKEN is set.
Set GITHUB_GIST_ID after the first gist is created (logged on startup).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
SYNCED_FILES = (
    "elo_overrides.json",
    "wc2026_live_matches.json",
    "nt_history_fetched.json",
)
GITHUB_API = "https://api.github.com"


def is_configured() -> bool:
    return bool(os.getenv("GITHUB_GIST_TOKEN", "").strip())


def _token() -> str:
    return os.getenv("GITHUB_GIST_TOKEN", "").strip()


def _gist_id() -> str:
    return os.getenv("GITHUB_GIST_ID", "").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_gist() -> str | None:
    gist_id = _gist_id()
    if gist_id:
        return gist_id
    if not is_configured():
        return None

    files = {name: {"content": "{}"} for name in SYNCED_FILES}
    try:
        response = requests.post(
            f"{GITHUB_API}/gists",
            headers=_headers(),
            json={
                "description": "Football Predictor WC 2026 cache",
                "public": False,
                "files": files,
            },
            timeout=20,
        )
        response.raise_for_status()
        gist_id = str(response.json()["id"])
        logger.warning(
            "Created GitHub Gist %s — add GITHUB_GIST_ID=%s to Render Environment",
            gist_id,
            gist_id,
        )
        return gist_id
    except Exception as exc:
        logger.warning("Failed to create gist: %s", exc)
        return None


def _fetch_gist(gist_id: str) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{GITHUB_API}/gists/{gist_id}",
            headers=_headers(),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("Gist fetch failed: %s", exc)
        return None


def pull_all() -> int:
    """Download synced cache files from gist. Returns files restored."""
    if not is_configured():
        return 0
    gist_id = _gist_id() or _ensure_gist()
    if not gist_id:
        return 0

    gist = _fetch_gist(gist_id)
    if not gist:
        return 0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    restored = 0
    for name in SYNCED_FILES:
        file_obj = (gist.get("files") or {}).get(name)
        if not file_obj:
            continue
        content = file_obj.get("content")
        if not content or not content.strip():
            continue
        target = CACHE_DIR / name
        try:
            json.loads(content)
            target.write_text(content, encoding="utf-8")
            restored += 1
        except json.JSONDecodeError:
            logger.warning("Skipping invalid gist file %s", name)
    if restored:
        logger.info("Restored %d cache file(s) from GitHub Gist", restored)
    return restored


def push_file(path: Path) -> bool:
    """Upload one cache file to gist."""
    if not is_configured() or not path.exists():
        return False
    gist_id = _gist_id() or _ensure_gist()
    if not gist_id:
        return False

    content = path.read_text(encoding="utf-8")
    try:
        response = requests.patch(
            f"{GITHUB_API}/gists/{gist_id}",
            headers=_headers(),
            json={"files": {path.name: {"content": content}}},
            timeout=20,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Gist push failed for %s: %s", path.name, exc)
        return False


def push_all() -> int:
    """Upload all present synced cache files."""
    pushed = 0
    for name in SYNCED_FILES:
        path = CACHE_DIR / name
        if path.exists() and push_file(path):
            pushed += 1
    return pushed
