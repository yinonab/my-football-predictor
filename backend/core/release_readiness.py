"""Phase 3E — Local/staging activation smoke helpers and release readiness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import config
from core.active_model_activation import SAMPLE_PRODUCTION_MATCHUPS

MODEL_DIAGNOSTICS_CONTRACT_FIELDS: tuple[str, ...] = (
    "model_version",
    "baseline_model_version",
    "activation_enabled",
    "active_candidate",
    "active_external_rating_mode",
    "active_external_rating_strategy",
    "fallback_to_baseline",
    "fallback_reasons",
    "candidate_metrics_source",
    "candidate_gate_status",
)

RELEASE_READY_FOR_STAGING = "READY_FOR_STAGING_ENABLEMENT"
RELEASE_HOLD = "HOLD"
RELEASE_NOT_READY = "NOT_READY"

PROB_SUM_TOLERANCE = 0.5
ROLLBACK_SAMPLE_MATCHUP: tuple[str, str] = ("Brazil", "Morocco")


@dataclass
class SmokeCheckResult:
    name: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "errors": self.errors,
            "details": self.details,
        }


def _client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


def _predict_payload(home: str, away: str) -> dict[str, Any]:
    return {"home_team": home, "away_team": away, "neutral_ground": True}


def _validate_model_diagnostics_contract(md: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in MODEL_DIAGNOSTICS_CONTRACT_FIELDS:
        if key not in md:
            errors.append(f"missing field: {key}")
    if not isinstance(md.get("fallback_reasons"), list):
        errors.append("fallback_reasons must be a list")
    return errors


def _validate_prediction_body(body: dict[str, Any], *, enabled: bool) -> list[str]:
    errors: list[str] = []
    md = body.get("model_diagnostics") or {}
    errors.extend(_validate_model_diagnostics_contract(md))

    if enabled:
        if md.get("model_version") != config.ACTIVE_MODEL_VERSION:
            errors.append(f"model_version={md.get('model_version')}")
        if md.get("fallback_to_baseline"):
            errors.append(f"fallback_to_baseline=true reasons={md.get('fallback_reasons')}")
        if not md.get("activation_enabled"):
            errors.append("activation_enabled=false")
    else:
        if md.get("model_version") != config.BASELINE_MODEL_VERSION:
            errors.append(f"model_version={md.get('model_version')}")
        if md.get("activation_enabled"):
            errors.append("activation_enabled=true while disabled")

    probs = body.get("probabilities_1x2") or {}
    total = float(probs.get("home_win", 0)) + float(probs.get("draw", 0)) + float(probs.get("away_win", 0))
    if abs(total - 100.0) > PROB_SUM_TOLERANCE:
        errors.append(f"prob_sum={total}")

    if body.get("home_xg") is None or body.get("away_xg") is None:
        errors.append("missing xG")
    if not body.get("top_scores"):
        errors.append("missing top_scores")

    return errors


def run_local_activation_enabled_smoke(
    matchups: list[tuple[str, str]] | None = None,
) -> SmokeCheckResult:
    pairs = matchups or list(SAMPLE_PRODUCTION_MATCHUPS)
    client = _client()
    errors: list[str] = []
    checked = 0

    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        for home, away in pairs:
            response = client.post("/api/predict", json=_predict_payload(home, away))
            if response.status_code != 200:
                errors.append(f"{home} vs {away}: HTTP {response.status_code}")
                continue
            body = response.json()
            row_errors = _validate_prediction_body(body, enabled=True)
            for err in row_errors:
                errors.append(f"{home} vs {away}: {err}")
            checked += 1

    return SmokeCheckResult(
        name="local_activation_enabled_smoke",
        passed=len(errors) == 0,
        errors=errors,
        details={"matchups_checked": checked, "matchups_total": len(pairs)},
    )


def run_activation_rollback_smoke(
    home: str = ROLLBACK_SAMPLE_MATCHUP[0],
    away: str = ROLLBACK_SAMPLE_MATCHUP[1],
) -> SmokeCheckResult:
    client = _client()
    errors: list[str] = []
    enabled_body: dict[str, Any] | None = None
    disabled_first: dict[str, Any] | None = None
    disabled_second: dict[str, Any] | None = None

    with (
        patch.object(config, "MODEL_ACTIVATION_ENABLED", True),
        patch.object(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", True),
    ):
        enabled_resp = client.post("/api/predict", json=_predict_payload(home, away))
        if enabled_resp.status_code != 200:
            errors.append(f"enabled HTTP {enabled_resp.status_code}")
        else:
            enabled_body = enabled_resp.json()
            errors.extend(
                f"enabled: {e}"
                for e in _validate_prediction_body(enabled_body, enabled=True)
            )

    disabled_resp = client.post("/api/predict", json=_predict_payload(home, away))
    if disabled_resp.status_code != 200:
        errors.append(f"disabled HTTP {disabled_resp.status_code}")
    else:
        disabled_first = disabled_resp.json()
        errors.extend(
            f"disabled_first: {e}"
            for e in _validate_prediction_body(disabled_first, enabled=False)
        )

    disabled_resp2 = client.post("/api/predict", json=_predict_payload(home, away))
    if disabled_resp2.status_code != 200:
        errors.append(f"disabled_second HTTP {disabled_resp2.status_code}")
    else:
        disabled_second = disabled_resp2.json()
        errors.extend(
            f"disabled_second: {e}"
            for e in _validate_prediction_body(disabled_second, enabled=False)
        )

    if enabled_body and disabled_first:
        enabled_md = enabled_body.get("model_diagnostics") or {}
        disabled_md = disabled_first.get("model_diagnostics") or {}
        if enabled_md.get("model_version") == disabled_md.get("model_version"):
            errors.append("enabled and disabled returned same model_version")
        if disabled_second:
            d2_md = disabled_second.get("model_diagnostics") or {}
            if d2_md.get("model_version") != config.BASELINE_MODEL_VERSION:
                errors.append("second disabled request did not stay on baseline")
            if disabled_first["probabilities_1x2"] != disabled_second["probabilities_1x2"]:
                errors.append("disabled predictions not stable across consecutive calls")

    return SmokeCheckResult(
        name="activation_rollback_smoke",
        passed=len(errors) == 0,
        errors=errors,
        details={
            "matchup": f"{home} vs {away}",
            "enabled_model_version": (
                (enabled_body or {}).get("model_diagnostics", {}).get("model_version")
            ),
            "disabled_model_version": (
                (disabled_first or {}).get("model_diagnostics", {}).get("model_version")
            ),
        },
    )


def production_defaults_disabled() -> tuple[bool, list[str]]:
    issues: list[str] = []
    if config.MODEL_ACTIVATION_ENABLED:
        issues.append("MODEL_ACTIVATION_ENABLED is true")
    if config.POWER_CANDIDATE_AFFECTS_PREDICTION:
        issues.append("POWER_CANDIDATE_AFFECTS_PREDICTION is true")
    return len(issues) == 0, issues


def determine_release_status(
    *,
    defaults_ok: bool,
    readiness_status: str,
    local_enablement_recommendation: str,
    qa_fallback_count: int,
    qa_large_shift_count: int,
    large_shifts_reviewed: bool,
    enabled_smoke_passed: bool,
    rollback_smoke_passed: bool,
) -> str:
    if not defaults_ok:
        return RELEASE_NOT_READY
    if qa_fallback_count > 0:
        return RELEASE_NOT_READY
    if not enabled_smoke_passed or not rollback_smoke_passed:
        return RELEASE_NOT_READY
    if readiness_status == "NOT_READY":
        return RELEASE_NOT_READY
    if qa_large_shift_count > 0 and not large_shifts_reviewed:
        return RELEASE_HOLD
    if enabled_smoke_passed and rollback_smoke_passed:
        if readiness_status in ("READY_WITH_WARNINGS", "READY_FOR_LOCAL_ENABLEMENT"):
            return RELEASE_READY_FOR_STAGING
        if local_enablement_recommendation in (
            "PROCEED_TO_LOCAL_ENABLEMENT",
            "PROCEED_TO_STAGING_WITH_APPROVAL",
        ):
            return RELEASE_READY_FOR_STAGING
    if local_enablement_recommendation == "HOLD":
        return RELEASE_HOLD
    return RELEASE_NOT_READY


def format_release_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release readiness report (Phase 3E)",
        "",
        f"**Status:** `{report.get('release_status', RELEASE_HOLD)}`",
        "",
        "> Staging/local enablement readiness only — not production deployment approval.",
        "",
        "## Summary",
        "",
        f"- Production defaults disabled: {report.get('defaults_ok')}",
        f"- Readiness status: {report.get('readiness_status')}",
        f"- Local enablement recommendation: {report.get('local_enablement_recommendation')}",
        f"- QA fallback count: {report.get('qa_fallback_count')}",
        f"- Large shifts reviewed: {report.get('large_shifts_reviewed')}",
        f"- Enabled smoke: {'PASS' if report.get('enabled_smoke_passed') else 'FAIL'}",
        f"- Rollback smoke: {'PASS' if report.get('rollback_smoke_passed') else 'FAIL'}",
        "",
        "## Enabled smoke",
        "",
    ]
    enabled = report.get("enabled_smoke") or {}
    lines.append(f"- Matchups checked: {enabled.get('details', {}).get('matchups_checked', 0)}")
    if enabled.get("errors"):
        lines.append("- Errors:")
        for err in enabled["errors"]:
            lines.append(f"  - {err}")
    else:
        lines.append("- No errors")

    lines.extend(["", "## Rollback smoke", ""])
    rollback = report.get("rollback_smoke") or {}
    details = rollback.get("details") or {}
    lines.append(f"- Matchup: {details.get('matchup', '-')}")
    lines.append(f"- Enabled model: {details.get('enabled_model_version')}")
    lines.append(f"- Disabled model: {details.get('disabled_model_version')}")
    if rollback.get("errors"):
        lines.append("- Errors:")
        for err in rollback["errors"]:
            lines.append(f"  - {err}")
    else:
        lines.append("- No errors")

    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python scripts/smoke_local_activation_enabled.py",
            "python scripts/smoke_activation_rollback.py",
            "python scripts/local_enablement_checklist.py",
            "python scripts/check_activation_readiness.py",
            "python -m pytest tests/ -q",
            "```",
            "",
        ]
    )
    return "\n".join(lines)
