"""AUDIT_ELO_BASELINE — production-parity mode for calibration audits."""

from __future__ import annotations

import json

import pytest

from core import elo_store


@pytest.fixture
def override_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "elo_overrides.json"
    path.write_text(
        json.dumps({"version": 1, "teams": {"Haiti (האיטי)": 1626.7}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(elo_store, "STORE_PATH", path)
    return path


def test_load_elo_overrides_reads_local_file(override_file, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDIT_ELO_BASELINE", raising=False)
    assert elo_store.load_elo_overrides() == {"Haiti (האיטי)": 1626.7}


def test_load_elo_overrides_production_baseline_ignores_file(
    override_file, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIT_ELO_BASELINE", "production")
    assert elo_store.load_elo_overrides() == {}
    assert json.loads(override_file.read_text(encoding="utf-8"))["teams"]["Haiti (האיטי)"] == 1626.7


def test_load_elo_overrides_fifa_alias(override_file, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_ELO_BASELINE", "fifa")
    assert elo_store.load_elo_overrides() == {}


def test_audit_elo_baseline_production_parity_false_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUDIT_ELO_BASELINE", raising=False)
    assert elo_store.audit_elo_baseline_production_parity() is False
