"""NR3+FCC served settings integration tests."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api.main import app
from core.live_nr3_fcc_shadow_runner import NR3_FCC_SERVED_MODEL_VERSION

client = TestClient(app)

FRANCE_SWEDEN = {
    "home_team": "France",
    "away_team": "Sweden",
    "neutral_ground": True,
    "include_diagnostics": True,
}


@pytest.fixture(autouse=True)
def _default_flags(monkeypatch):
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: False)
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", False)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: False)


@pytest.fixture
def production_model_activation(monkeypatch):
    monkeypatch.setattr(config, "MODEL_ACTIVATION_ENABLED", True)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True)


def _predict(payload: dict) -> dict:
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _enable_served(monkeypatch) -> None:
    monkeypatch.setattr(config, "NR3_FCC_SERVED_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_served_enabled", lambda: True)


def test_baseline_parity_served_off(monkeypatch, production_model_activation):
    data = _predict(FRANCE_SWEDEN)
    assert data["home_xg"] == 2.85
    assert data["away_xg"] == 0.77
    assert data["probabilities_1x2"]["home_win"] == 74.0
    assert data["model_diagnostics"]["model_version"] == "v2.2.0-fifa-points-anchor"


def test_nr3_served_still_works(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    data = _predict(FRANCE_SWEDEN)
    assert data["model_diagnostics"]["model_version"] == NR3_FCC_SERVED_MODEL_VERSION
    assert data["home_xg"] != 2.85


def test_avg_goals_affects_nr3_served(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    low = _predict({**FRANCE_SWEDEN, "avg_goals": 2.6})
    high = _predict({**FRANCE_SWEDEN, "avg_goals": 2.8})
    assert low["home_xg"] != high["home_xg"] or low["away_xg"] != high["away_xg"]


def test_rho_affects_nr3_draw(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    mild = _predict({**FRANCE_SWEDEN, "rho": -0.05})
    strong = _predict({**FRANCE_SWEDEN, "rho": -0.15})
    assert mild["probabilities_1x2"]["draw"] != strong["probabilities_1x2"]["draw"]


def test_alpha_affects_nr3_top_scores(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    low_a = _predict({**FRANCE_SWEDEN, "alpha": 0.05})
    high_a = _predict({**FRANCE_SWEDEN, "alpha": 0.35})
    assert low_a["top_scores"] != high_a["top_scores"]


def test_top_n_affects_nr3_top_scores_length(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    t3 = _predict({**FRANCE_SWEDEN, "top_n": 3})
    t5 = _predict({**FRANCE_SWEDEN, "top_n": 5})
    assert len(t3["top_scores"]) == 3
    assert len(t5["top_scores"]) == 5


def test_goliath_affects_nr3_served(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    off = _predict({**FRANCE_SWEDEN, "fusion_blowout_enabled": False})
    on = _predict({**FRANCE_SWEDEN, "fusion_blowout_enabled": True})
    assert off["home_xg"] != on["home_xg"]
    assert on["home_xg"] > off["home_xg"]


def test_odds_affect_nr3_when_mocked(monkeypatch, production_model_activation):
    from core.odds_ensemble import BookmakerOddsLine, OddsLookupResult, OddsMarketFetch

    _enable_served(monkeypatch)
    market = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    line = BookmakerOddsLine(
        id="mock",
        display_name="Mock",
        region="eu",
        home_decimal_odds=1.8,
        draw_decimal_odds=4.0,
        away_decimal_odds=5.0,
        implied_1x2_percent=market,
    )
    fetch = OddsMarketFetch(
        sport_key="soccer",
        bookmakers=[line],
        consensus_1x2_percent=market,
    )
    lookup = OddsLookupResult(
        fetch=fetch,
        odds_key_configured=True,
        status="ok",
    )

    with patch("api.main._odds_client.lookup_match_market", return_value=lookup):
        off = _predict({**FRANCE_SWEDEN, "odds_affect_prediction": False})
        on = _predict({**FRANCE_SWEDEN, "odds_affect_prediction": True})

    assert off["probabilities_1x2"] != on["probabilities_1x2"]


def test_context_xg_delta_affects_nr3_when_mocked(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    ctx_off = SimpleNamespace(
        home_power_mult=1.0,
        away_power_mult=1.0,
        xg_total_delta=0.0,
        notes=[],
    )
    ctx_on = SimpleNamespace(
        home_power_mult=1.0,
        away_power_mult=1.0,
        xg_total_delta=0.35,
        notes=["mock weather"],
    )

    with patch("api.main.compute_context_adjustments", return_value=ctx_off):
        off = _predict({**FRANCE_SWEDEN, "use_match_context": True})
    with patch("api.main.compute_context_adjustments", return_value=ctx_on):
        on = _predict({**FRANCE_SWEDEN, "use_match_context": True})

    assert off["home_xg"] != on["home_xg"]


def test_context_disabled_skips_xg_delta(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    ctx_on = SimpleNamespace(
        home_power_mult=1.0,
        away_power_mult=1.0,
        xg_total_delta=0.35,
        notes=[],
    )
    with patch("api.main.compute_context_adjustments", return_value=ctx_on):
        with_ctx = _predict({**FRANCE_SWEDEN, "use_match_context": True})
        without_ctx = _predict({**FRANCE_SWEDEN, "use_match_context": False})
    assert with_ctx["home_xg"] != without_ctx["home_xg"]


def test_altitude_affects_nr3_via_power(monkeypatch, production_model_activation):
    _enable_served(monkeypatch)
    payload = {
        "home_team": "Mexico",
        "away_team": "Ecuador",
        "neutral_ground": False,
        "include_diagnostics": True,
    }

    def _apply_mod(power, *, altitude=0, star_absent=False):
        if altitude >= 1200:
            return power * 0.92
        return power

    with patch(
        "api.main._power_evaluator.apply_environmental_modifiers",
        side_effect=_apply_mod,
    ):
        low = _predict({**payload, "altitude": 0, "auto_stadium_altitude": False})
        high = _predict({**payload, "altitude": 2200, "auto_stadium_altitude": False})

    assert low["home_xg"] != high["home_xg"]


def test_failure_fallback(monkeypatch, caplog, production_model_activation):
    import logging

    caplog.set_level(logging.WARNING)
    baseline = _predict(FRANCE_SWEDEN)
    _enable_served(monkeypatch)
    with patch(
        "core.live_nr3_fcc_shadow_runner.run_live_nr3_fcc_shadow_sidecar",
        side_effect=RuntimeError("boom"),
    ):
        data = _predict(FRANCE_SWEDEN)
    assert data["home_xg"] == baseline["home_xg"]
    assert "nr3_fcc_served_failed_fallback" in caplog.text


def test_shadow_independence(monkeypatch, production_model_activation):
    baseline = _predict(FRANCE_SWEDEN)
    monkeypatch.setattr(config, "NR3_FCC_SHADOW_ENABLED", True)
    monkeypatch.setattr(config, "nr3_fcc_shadow_enabled", lambda: True)
    shadow = _predict(FRANCE_SWEDEN)
    assert shadow["home_xg"] == baseline["home_xg"]


def test_startup_import_served_true(monkeypatch):
    monkeypatch.setenv("NR3_FCC_SERVED_ENABLED", "true")
    importlib.reload(config)
    import api.main as main_module

    importlib.reload(main_module)
    assert main_module.app is not None


BELGIUM_SENEGAL = {
    "home_team": "Belgium",
    "away_team": "Senegal",
    "neutral_ground": True,
    "include_diagnostics": True,
    "use_match_context": False,
    "odds_affect_prediction": False,
    "auto_stadium_altitude": False,
    "altitude": 0,
    "avg_goals": 2.6,
}


def _decomp(data: dict) -> dict:
    diag = data.get("model_diagnostics") or {}
    decomp = diag.get("nr3_xg_decomposition")
    assert decomp is not None, "expected nr3_xg_decomposition"
    return decomp


def test_nr3_decomposition_present_when_diagnostics_on(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict(BELGIUM_SENEGAL)
    decomp = _decomp(data)
    assert decomp["active_model"] == NR3_FCC_SERVED_MODEL_VERSION
    assert decomp["final"]["home_xg"] == data["home_xg"]
    assert decomp["final"]["away_xg"] == data["away_xg"]


def test_nr3_decomposition_no_diagnostics_when_flag_off(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    payload = {**BELGIUM_SENEGAL, "include_diagnostics": False}
    data = _predict(payload)
    diag = data.get("model_diagnostics") or {}
    assert diag.get("nr3_xg_decomposition") is None


def test_goliath_off_vs_on_fusion_adjustment_status(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    off = _predict({**BELGIUM_SENEGAL, "fusion_blowout_enabled": False})
    on = _predict({**BELGIUM_SENEGAL, "fusion_blowout_enabled": True})
    off_fusion = next(
        a for a in _decomp(off)["adjustments"] if a["name"] == "fusion_blowout"
    )
    on_fusion = next(
        a for a in _decomp(on)["adjustments"] if a["name"] == "fusion_blowout"
    )
    assert off_fusion["status"] == "disabled"
    assert on_fusion["status"] in ("applied", "skipped")
    assert on["home_xg"] > off["home_xg"]


def test_legacy_reference_marked_comparison_only(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    data = _predict(BELGIUM_SENEGAL)
    legacy = _decomp(data)["legacy_reference"]
    assert legacy["label"] == "ייחוס מודל ישן / Maher"
    assert "להשוואה בלבד" in legacy["note"]
    assert legacy["home_xg"] == data["base_home_xg"]


def test_prediction_unchanged_without_diagnostics_flag(
    monkeypatch, production_model_activation
):
    _enable_served(monkeypatch)
    base_payload = {**BELGIUM_SENEGAL, "include_diagnostics": False}
    with_diag = _predict({**BELGIUM_SENEGAL, "include_diagnostics": True})
    without_diag = _predict(base_payload)
    assert with_diag["home_xg"] == without_diag["home_xg"]
    assert with_diag["away_xg"] == without_diag["away_xg"]
    assert with_diag["probabilities_1x2"] == without_diag["probabilities_1x2"]
