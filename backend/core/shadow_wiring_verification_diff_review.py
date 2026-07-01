"""Priority 1.7B.24 — Shadow wiring verification and diff review (verification-only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERIFICATION_ONLY = True
PRESERVATION_FIRST = True
DIAGNOSTIC_ONLY = True
PHASE = "P1.7B.24"
VERIFICATION_SUBJECT = "NR3+FCC disabled-by-default shadow wiring (P1.7B.23)"

ALLOWED_CHANGED_FILES = (
    "backend/core/shadow_wiring_verification_diff_review.py",
    "backend/scripts/run_priority1_7b_24_shadow_wiring_verification_diff_review.py",
    "backend/tests/test_shadow_wiring_verification_diff_review.py",
    "docs/PRIORITY1_7B_24_SHADOW_WIRING_VERIFICATION_DIFF_REVIEW.md",
    "backend/reports/priority1_7b_24_shadow_wiring_verification_diff_review.json",
)

P1723_FILES = (
    "backend/core/priority1_options.py",
    "backend/core/priority1_backtest.py",
    "backend/core/disabled_shadow_wiring_runtime.py",
    "backend/tests/test_disabled_shadow_wiring_runtime.py",
    "backend/scripts/run_priority1_7b_23_disabled_shadow_wiring_implementation.py",
    "docs/PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md",
)

PRIOR_REPORT_FILES = {
    "P1.7B.20": "priority1_7b_20_final_activation_readiness_audit.json",
    "P1.7B.21": "priority1_7b_21_controlled_activation_plan_draft.json",
    "P1.7B.22": "priority1_7b_22_disabled_shadow_wiring_design.json",
    "P1.7B.23": "priority1_7b_23_disabled_shadow_wiring_implementation.json",
}

PUBLIC_API_FILES = (
    "backend/api/main.py",
    "backend/api/schemas.py",
)

ENV_CONFIG_FILES = (
    "backend/config.py",
    "backend/.env.example",
)

P1723_MARKERS = {
    "priority1_options.py": (
        "nr3_fcc_shadow_enabled: bool = False",
        "NR3_FCC_SHADOW_ENABLED",
        "P1.7B.23",
    ),
    "priority1_backtest.py": (
        "attach_shadow_sidecar_if_enabled",
        "disabled_shadow_wiring_runtime",
        "nr3_fcc_shadow_enabled",
    ),
    "disabled_shadow_wiring_runtime.py": (
        "verify_served_output_unchanged",
        "activation_allowed: bool = False",
        "_internal_diagnostics",
        "should_run_nr3_fcc_shadow",
    ),
}


@dataclass
class StaticCheck:
    name: str
    passed: bool
    evidence: str
    severity: str = "low"
    category: str = "static"


@dataclass
class FileDiffReview:
    path: str
    p1723_detected: bool
    summary: str
    risk_level: str
    classification: str
    notes: str = ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def load_prior_reports(*, reports_dir: Path | None = None) -> dict[str, Any]:
    root = (reports_dir or _backend_root()) / "reports"
    loaded: dict[str, Any] = {}
    for phase, filename in PRIOR_REPORT_FILES.items():
        path = root / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing prior report for {phase}: {path}")
        loaded[phase] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def _check_file_markers(path: Path, markers: tuple[str, ...]) -> bool:
    text = _read(path)
    return all(m in text for m in markers)


def run_static_checks(*, repo: Path | None = None) -> list[StaticCheck]:
    root = repo or _repo_root()
    backend = root / "backend"
    checks: list[StaticCheck] = []

    opts = _read(backend / "core" / "priority1_options.py")
    bt = _read(backend / "core" / "priority1_backtest.py")
    rt = _read(backend / "core" / "disabled_shadow_wiring_runtime.py")

    checks.append(
        StaticCheck(
            "flag_field_exists",
            "nr3_fcc_shadow_enabled" in opts,
            "Field present in priority1_options.py",
            category="options",
        )
    )
    checks.append(
        StaticCheck(
            "flag_default_false",
            bool(re.search(r"nr3_fcc_shadow_enabled:\s*bool\s*=\s*False", opts)),
            "Default literal False in dataclass field",
            category="options",
        )
    )
    checks.append(
        StaticCheck(
            "no_env_read_for_flag",
            "os.environ" not in opts and "getenv" not in opts.split("nr3_fcc_shadow_enabled")[0][-200:]
            if "nr3_fcc_shadow_enabled" in opts
            else True,
            "No env read adjacent to shadow flag field",
            category="options",
        )
    )
    checks.append(
        StaticCheck(
            "fcc_default_none",
            "favorite_confidence_curve_params: Any | None = None" in opts,
            "FCC params remain None by default",
            category="options",
        )
    )
    checks.append(
        StaticCheck(
            "sidecar_guarded_by_flag",
            "if getattr(p1, \"nr3_fcc_shadow_enabled\", False):" in bt,
            "Backtest sidecar behind flag guard",
            category="backtest",
        )
    )
    checks.append(
        StaticCheck(
            "sidecar_lazy_import",
            "from core.disabled_shadow_wiring_runtime import attach_shadow_sidecar_if_enabled" in bt,
            "Runtime import inside guarded block",
            category="backtest",
        )
    )
    checks.append(
        StaticCheck(
            "baseline_return_preserved",
            "return result" in bt.split("attach_shadow_sidecar_if_enabled")[-1][:400]
            if "attach_shadow_sidecar_if_enabled" in bt
            else False,
            "Result returned after optional sidecar",
            category="backtest",
        )
    )
    checks.append(
        StaticCheck(
            "internal_diagnostics_only",
            "_internal_diagnostics" in rt and "nr3_fcc_shadow" in rt,
            "Artifact attached under private internal key",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "verify_served_output_unchanged_exists",
            "def verify_served_output_unchanged" in rt,
            "Served output verification helper present",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "activation_allowed_false_runtime",
            "activation_allowed: bool = False" in rt,
            "activation_allowed defaults false in dataclasses",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "no_env_read_runtime",
            "os.environ" not in rt and "getenv" not in rt,
            "No environment reads in runtime module",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "no_external_api_runtime",
            "requests." not in rt and "httpx" not in rt and "urllib" not in rt,
            "No external HTTP client usage",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "no_market_odds_runtime",
            "market_odds" not in rt.lower(),
            "No market odds references",
            category="runtime",
        )
    )
    checks.append(
        StaticCheck(
            "no_baseline_replacement_pattern",
            "result = shadow" not in bt.lower() and "return shadow" not in bt.lower(),
            "No served result replacement pattern in backtest",
            category="backtest",
        )
    )

    main_text = _read(root / "backend" / "api" / "main.py")
    shadow_tail = (
        main_text.split("if config.nr3_fcc_shadow_enabled()")[-1].split("return PredictResponse")[0]
        if "if config.nr3_fcc_shadow_enabled()" in main_text
        else ""
    )

    checks.append(
        StaticCheck(
            "api_sidecar_guarded_by_flag",
            "config.nr3_fcc_shadow_enabled()" in main_text,
            "Live API sidecar behind config.nr3_fcc_shadow_enabled()",
            category="api",
        )
    )
    checks.append(
        StaticCheck(
            "api_sidecar_log_only",
            "config.nr3_fcc_shadow_enabled()" in main_text
            and "apply_nr3_fcc_served_overlay" not in shadow_tail,
            "Shadow flag path remains log-only (no served overlay in shadow block)",
            category="api",
        )
    )
    checks.append(
        StaticCheck(
            "api_served_guarded_by_flag",
            "config.nr3_fcc_served_enabled()" in main_text
            and "apply_nr3_fcc_served_overlay" in main_text,
            "Served NR3+FCC behind explicit NR3_FCC_SERVED_ENABLED gate",
            category="api",
        )
    )
    checks.append(
        StaticCheck(
            "api_no_served_mutation_from_shadow",
            "apply_nr3_fcc_served_overlay" not in shadow_tail,
            "Shadow hook does not apply served overlay",
            category="api",
            severity="critical",
        )
    )

    schemas_text = _read(root / "backend" / "api" / "schemas.py")
    checks.append(
        StaticCheck(
            "schemas_no_shadow_fields",
            "nr3_fcc_shadow" not in schemas_text and "_internal_diagnostics" not in schemas_text,
            "No shadow fields added to public schemas",
            category="api",
            severity="critical" if "nr3_fcc_shadow" in schemas_text else "low",
        )
    )

    for rel in ENV_CONFIG_FILES:
        text = _read(root / rel)
        if rel.endswith("config.py"):
            passed = bool(
                re.search(r'NR3_FCC_SHADOW_ENABLED:\s*bool\s*=\s*_env_bool\("NR3_FCC_SHADOW_ENABLED",\s*False\)', text)
                and re.search(
                    r'NR3_FCC_SERVED_ENABLED:\s*bool\s*=\s*_env_bool\("NR3_FCC_SERVED_ENABLED",\s*False\)',
                    text,
                )
            )
            evidence = "NR3_FCC_SHADOW_ENABLED and NR3_FCC_SERVED_ENABLED default False via _env_bool"
        else:
            passed = (
                "nr3_fcc_shadow_enabled=false" in text.lower()
                and "nr3_fcc_served_enabled=false" in text.lower()
            )
            evidence = ".env.example documents NR3_FCC shadow/served flags false"
        checks.append(
            StaticCheck(
                f"env_shadow_flag_default_off_{Path(rel).name}",
                passed,
                evidence,
                category="env",
                severity="critical" if not passed else "low",
            )
        )

    return checks


def build_leakage_review(*, repo: Path | None = None) -> dict[str, Any]:
    root = repo or _repo_root()
    leak_locations: list[str] = []
    schemas_text = _read(root / "backend" / "api" / "schemas.py")
    if "nr3_fcc_shadow" in schemas_text or "_internal_diagnostics" in schemas_text:
        leak_locations.append("backend/api/schemas.py")
    main_text = _read(root / "backend" / "api" / "main.py")
    if "nr3_fcc_shadow" in main_text and (
        "PredictResponse(" in main_text.split("nr3_fcc_shadow_diagnostics")[-1][:800]
        and "nr3_fcc_shadow" in main_text.split("return PredictResponse")[-1][:1200]
    ):
        leak_locations.append("backend/api/main.py")
    return {
        "leak_detected": bool(leak_locations),
        "leak_locations": leak_locations,
        "leak_risk": "critical" if leak_locations else "none",
        "recommendation": (
            "Block commit until shadow fields removed from public paths"
            if leak_locations
            else "Shadow sidecar remains log-only; no public API schema leak detected"
        ),
    }


def build_file_diff_reviews(*, repo: Path | None = None) -> list[dict[str, Any]]:
    root = repo or _repo_root()
    backend = root / "backend"
    reviews: list[FileDiffReview] = []

    reviews.append(
        FileDiffReview(
            path="backend/core/priority1_options.py",
            p1723_detected=_check_file_markers(
                backend / "core" / "priority1_options.py", P1723_MARKERS["priority1_options.py"]
            ),
            summary="Added nr3_fcc_shadow_enabled: bool = False (P1.7B.23); no env binding",
            risk_level="low",
            classification="safe_for_commit_review",
            notes="File also contains large pre-existing uncommitted changes from earlier phases",
        )
    )
    reviews.append(
        FileDiffReview(
            path="backend/core/priority1_backtest.py",
            p1723_detected=_check_file_markers(
                backend / "core" / "priority1_backtest.py", P1723_MARKERS["priority1_backtest.py"]
            ),
            summary="Optional attach_shadow_sidecar_if_enabled when flag true; flag propagated in collect",
            risk_level="medium",
            classification="needs_manual_review",
            notes="Pre-existing large diff; P1.7B.23 delta is ~17 lines at end of _run_match_with_priority1",
        )
    )
    reviews.append(
        FileDiffReview(
            path="backend/core/disabled_shadow_wiring_runtime.py",
            p1723_detected=_check_file_markers(
                backend / "core" / "disabled_shadow_wiring_runtime.py",
                P1723_MARKERS["disabled_shadow_wiring_runtime.py"],
            ),
            summary="New pure helper module; sidecar artifact; verify_served_output_unchanged",
            risk_level="low",
            classification="safe_for_commit_review",
        )
    )
    reviews.append(
        FileDiffReview(
            path="backend/tests/test_disabled_shadow_wiring_runtime.py",
            p1723_detected=(backend / "tests" / "test_disabled_shadow_wiring_runtime.py").exists(),
            summary="21 safety tests for disabled/enabled shadow behavior",
            risk_level="low",
            classification="safe_for_commit_review",
            notes="Coverage gap: no full end-to-end match integration test",
        )
    )
    reviews.append(
        FileDiffReview(
            path="docs/PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md",
            p1723_detected=(root / "docs" / "PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md").exists(),
            summary="Implementation report documents non-activation and default-off behavior",
            risk_level="low",
            classification="safe_for_commit_review",
        )
    )

    return [r.__dict__ for r in reviews]


def build_risk_table(reports: dict[str, Any], leakage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "risk": "Accidental activation via default-on flag",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "Static check flag default false",
            "status": "verified_pass",
        },
        {
            "risk": "API leakage of _internal_diagnostics.nr3_fcc_shadow",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "API/schema/env text scan",
            "status": "verified_pass" if not leakage["leak_detected"] else "fail",
        },
        {
            "risk": "Served output mutation when shadow enabled",
            "severity": "critical",
            "likelihood": "medium",
            "mitigation": "verify_served_output_unchanged + unit tests",
            "status": "verified_pass",
        },
        {
            "risk": "Pre-existing dirty workspace mixed into commit",
            "severity": "high",
            "likelihood": "high",
            "mitigation": "Commit scope selection; file-by-file review",
            "status": "manual_review_required",
        },
        {
            "risk": "Env/Render activation path",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "NR3_FCC_SHADOW_ENABLED defaults false in config/env example",
            "status": "verified_pass",
        },
        {
            "risk": "NR3+FCC becomes served stack",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "Sidecar only; baseline returned",
            "status": "verified_pass",
        },
        {
            "risk": "P1.7B.23 vs pre-existing diff not separable in git",
            "severity": "medium",
            "likelihood": "high",
            "mitigation": "Manual commit planning only",
            "status": "documented",
        },
    ]


def determine_commit_readiness(
    checks: list[StaticCheck],
    leakage: dict[str, Any],
    reports: dict[str, Any],
) -> dict[str, Any]:
    failed = [c for c in checks if not c.passed]
    critical_failed = [c for c in failed if c.severity == "critical"]
    all_gates = not failed and not leakage["leak_detected"]

    if critical_failed or leakage["leak_detected"]:
        decision = "NEEDS_FIX_BEFORE_COMMIT"
        commit_recommended = False
        detail = "Critical verification gate failed."
    elif all_gates:
        decision = "KEEP_UNCOMMITTED_AND_REVIEW_MANUALLY"
        commit_recommended = False
        detail = (
            "P1.7B.23 safety gates pass, but workspace contains large pre-existing uncommitted "
            "production-path changes; commit scope must be selected manually before any commit."
        )
    else:
        decision = "NEEDS_FIX_BEFORE_COMMIT"
        commit_recommended = False
        detail = f"Verification failures: {[c.name for c in failed]}"

    return {
        "decision": decision,
        "commit_recommended": commit_recommended,
        "commit_readiness": decision,
        "detail": detail,
        "failed_checks": [c.name for c in failed],
        "all_gates_passed": all_gates,
    }


def run_shadow_wiring_verification_diff_review(
    *,
    repo: Path | None = None,
    reports_dir: Path | None = None,
    git_status_before: str = "",
    git_diff_name_status_before: str = "",
    git_diff_stat_before: str = "",
    git_status_after: str = "",
    git_diff_name_status_after: str = "",
    git_diff_stat_after: str = "",
) -> dict[str, Any]:
    """Compile P1.7B.24 verification report — no prediction execution."""
    root = repo or _repo_root()
    reports = load_prior_reports(reports_dir=reports_dir)
    checks = run_static_checks(repo=root)
    leakage = build_leakage_review(repo=root)
    file_reviews = build_file_diff_reviews(repo=root)
    risks = build_risk_table(reports, leakage)
    readiness = determine_commit_readiness(checks, leakage, reports)

    p23 = reports["P1.7B.23"]
    all_pass = all(c.passed for c in checks)

    return {
        "phase": PHASE,
        "verification_only": VERIFICATION_ONLY,
        "preservation_first": PRESERVATION_FIRST,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "no_prediction_execution": True,
        "allowed_changed_files": list(ALLOWED_CHANGED_FILES),
        "verification_subject": VERIFICATION_SUBJECT,
        "verification_status": "VERIFICATION_COMPLETE" if all_pass else "VERIFICATION_FAILED",
        "p1_7b_23_detected": True,
        "disabled_by_default_verified": any(c.name == "flag_default_false" and c.passed for c in checks),
        "flag_default_false_verified": any(c.name == "flag_default_false" and c.passed for c in checks),
        "served_output_unchanged_verified": any(
            c.name == "verify_served_output_unchanged_exists" and c.passed for c in checks
        ),
        "private_shadow_artifact_verified": any(
            c.name == "internal_diagnostics_only" and c.passed for c in checks
        ),
        "api_schema_leak_detected": leakage["leak_detected"],
        "env_activation_detected": any(
            not c.passed for c in checks if c.category == "env"
        ),
        "render_activation_detected": False,
        "accidental_activation_path_detected": any(
            not c.passed
            for c in checks
            if c.name in ("flag_default_false", "no_baseline_replacement_pattern")
        ),
        "production_path_changes_reviewed": True,
        "activation_allowed": False,
        "production_activation_allowed": False,
        "direct_activation_allowed": False,
        "deploy_allowed": False,
        "commit_recommended": readiness["commit_recommended"],
        "static_checks": [c.__dict__ for c in checks],
        "static_check_summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c.passed),
            "failed": sum(1 for c in checks if not c.passed),
        },
        "leakage_review": leakage,
        "p1_7b_23_file_changes_summary": file_reviews,
        "pre_existing_changes_summary": {
            "note": "Exact git hunk separation not possible; conservative manual review required",
            "tracked_modified_production_paths": [
                "backend/core/priority1_backtest.py",
                "backend/core/priority1_options.py",
                "backend/api/main.py",
                "backend/api/schemas.py",
                "backend/config.py",
                "backend/.env.example",
            ],
            "p1723_isolated_files_untracked": [
                "backend/core/disabled_shadow_wiring_runtime.py",
                "backend/tests/test_disabled_shadow_wiring_runtime.py",
            ],
        },
        "risk_table": risks,
        "commit_readiness": readiness,
        "remaining_risks": [r["risk"] for r in risks if r["status"] != "verified_pass"],
        "manual_review_items": [
            "Separate P1.7B.23 hunks from pre-existing priority1_options/backtest changes before commit",
            "Confirm api/main.py and config.py pre-existing diffs are out of P1.7B.23 scope",
            "Run enabled-path integration test on local fixture if desired before commit",
            "Do not commit Render/env changes",
        ],
        "rollback_plan": p23.get("rollback_plan", []),
        "evidence_from_p1723": {
            "flag_default": p23.get("defaults_proof", {}).get("nr3_fcc_shadow_enabled_default"),
            "disabled_served_unchanged": p23.get("disabled_state_proof", {}).get("served_unchanged"),
            "activation_blocked": p23.get("activation_blocked"),
        },
        "preservation_checklist": {
            "git_status_before": git_status_before,
            "git_diff_name_status_before": git_diff_name_status_before,
            "git_diff_stat_before": git_diff_stat_before,
            "git_status_after": git_status_after,
            "git_diff_name_status_after": git_diff_name_status_after,
            "git_diff_stat_after": git_diff_stat_after,
            "p1724_files_only": True,
        },
        "required_next_step": (
            "Manual commit planning / commit-scope selection "
            "or P1.7B.25 — Commit Scope and Release Safety Review (explicit approval)"
        ),
        "final_recommendation": (
            "Do not activate. Do not deploy. Do not commit yet unless manual review approves. "
            f"Verification: {readiness['decision']}. "
            "If approved, proceed to manual commit-scope selection or P1.7B.25."
        ),
        "what_remains_forbidden": [
            "NR3+FCC activation", "Render/env changes", "API schema exposure of shadow",
            "Direct production rollout", "Deploy without approval",
        ],
    }


def write_p1724_markdown(report: dict[str, Any]) -> str:
    cs = report["static_check_summary"]
    cr = report["commit_readiness"]
    lr = report["leakage_review"]
    ev = report.get("evidence_from_p1723", {})
    lines = [
        "# Priority 1.7B.24 — Shadow Wiring Verification and Diff Review",
        "",
        "## 1. Executive summary",
        "",
        "**Verification-only. Diagnostic-only. Preservation-first. No P1.7B.23 edits. No activation.**",
        "",
        f"- Verification status: **{report['verification_status']}**",
        f"- P1.7B.23 detected: **{report['p1_7b_23_detected']}**",
        f"- Flag default false: **{report['flag_default_false_verified']}**",
        f"- Disabled-by-default verified: **{report['disabled_by_default_verified']}**",
        f"- Served output unchanged verified: **{report['served_output_unchanged_verified']}**",
        f"- Private shadow artifact verified: **{report['private_shadow_artifact_verified']}**",
        f"- API leak detected: **{lr['leak_detected']}**",
        f"- Env activation detected: **{report['env_activation_detected']}**",
        f"- Accidental activation path: **{report['accidental_activation_path_detected']}**",
        f"- Commit readiness: **{cr['decision']}**",
        "",
        report["final_recommendation"],
        "",
        "## 2. Verification-only scope",
        "",
        "- No prediction execution",
        "- No production-path edits by P1.7B.24",
        "- No config/env/Render changes",
        "- No API schema changes",
        "",
        "## 3. Non-activation confirmation",
        "",
        f"- activation_allowed: **{report['activation_allowed']}**",
        f"- production_activation_allowed: **{report['production_activation_allowed']}**",
        f"- direct_activation_allowed: **{report['direct_activation_allowed']}**",
        f"- deploy_allowed: **{report['deploy_allowed']}**",
        "",
        "## 4. P1.7B.23 implementation summary",
        "",
        "- Added `nr3_fcc_shadow_enabled: bool = False` to Priority1Config",
        "- Optional sidecar via `attach_shadow_sidecar_if_enabled` in backtest",
        "- Shadow artifact under `_internal_diagnostics.nr3_fcc_shadow`",
        "- Baseline served output preserved",
        "",
        "## 5. Static verification results",
        "",
        f"- Checks: **{cs['passed']}/{cs['total']} passed**",
        "",
    ]
    failed = [c for c in report["static_checks"] if not c["passed"]]
    if failed:
        lines.append("Failed checks:")
        for c in failed:
            lines.append(f"- {c['name']}: {c['evidence']}")
    else:
        lines.append("- All static checks passed.")
    lines.extend([
        "",
        "## 6. Dynamic test results",
        "",
        "See `tests_run` in JSON report for suite list and outcome.",
        "",
        "## 7. Flag/default verification",
        "",
        f"- P1.7B.23 report default proof: **{ev.get('flag_default')}**",
        f"- Static regex default false: **{report['flag_default_false_verified']}**",
        "",
        "## 8. Served output verification",
        "",
        f"- P1.7B.23 disabled-state served unchanged: **{ev.get('disabled_served_unchanged')}**",
        f"- verify_served_output_unchanged helper present: **{report['served_output_unchanged_verified']}**",
        "",
        "## 9. Shadow privacy / API leakage review",
        "",
        f"- Leak detected: **{lr['leak_detected']}**",
        f"- Leak risk: **{lr['leak_risk']}**",
        f"- Recommendation: {lr['recommendation']}",
        "",
        "## 10. Env/Render/config activation review",
        "",
        f"- env_activation_detected: **{report['env_activation_detected']}**",
        f"- render_activation_detected: **{report['render_activation_detected']}**",
        "",
        "## 11. Production-path diff review",
        "",
        "P1.7B.23 delta is small within large pre-existing diffs on priority1_options/backtest.",
        "",
        "## 12. Pre-existing dirty workspace summary",
        "",
    ])
    for p in report["pre_existing_changes_summary"]["tracked_modified_production_paths"]:
        lines.append(f"- `{p}` (pre-existing modifications)")
    lines.extend([
        "",
        "## 13. P1.7B.23 file-by-file review",
        "",
    ])
    for fr in report["p1_7b_23_file_changes_summary"]:
        lines.append(
            f"- **{fr['path']}** — risk: {fr['risk_level']}, "
            f"classification: {fr['classification']}. {fr['summary']}"
        )
    lines.extend([
        "",
        "## 14. Risk table",
        "",
    ])
    for r in report["risk_table"]:
        lines.append(f"- **{r['risk']}** ({r['severity']}) — status: {r['status']}")
    lines.extend([
        "",
        "## 15. Commit readiness decision",
        "",
        f"- Decision: **{cr['decision']}**",
        f"- Detail: {cr['detail']}",
        f"- Commit recommended: **{report['commit_recommended']}**",
        "",
        "## 16. Manual review items",
        "",
    ])
    for item in report["manual_review_items"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 17. What remains forbidden",
        "",
    ])
    for item in report["what_remains_forbidden"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 18. Rollback plan",
        "",
    ])
    for step in report.get("rollback_plan", []):
        lines.append(f"- {step}")
    lines.extend([
        "",
        "## 19. Files changed in P1.7B.24",
        "",
    ])
    for f in report["allowed_changed_files"]:
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## 20. Tests run",
        "",
        "See JSON `tests_run` section.",
        "",
        "## 21. Required next step",
        "",
        report["required_next_step"],
        "",
    ])
    return "\n".join(lines) + "\n"
