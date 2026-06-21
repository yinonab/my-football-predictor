"""Shared pytest fixtures — isolate developer-local gitignored caches from tests."""

from __future__ import annotations

from pathlib import Path

import pytest

_FUSION_TEST_MODULES = frozenset(
    {
        "test_recent_form_fusion_phase4r3",
    }
)


@pytest.fixture(autouse=True)
def isolate_local_fusion_cache_from_tests(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Prevent accidental reads of backend/data/cache/recent_form_fusion_cache.json during tests."""
    module_name = request.module.__name__.split(".")[-1] if request.module else ""
    if module_name in _FUSION_TEST_MODULES:
        return
    missing = Path(__file__).resolve().parent / "_no_local_fusion_cache.json"
    monkeypatch.setattr("core.recent_form_fusion.FUSION_CACHE_PATH", missing)
