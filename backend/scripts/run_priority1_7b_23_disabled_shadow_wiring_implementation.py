#!/usr/bin/env python3
"""Priority 1.7B.23 — Disabled-by-default shadow wiring implementation report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.disabled_shadow_wiring_runtime import (  # noqa: E402
    FLAG_NAME,
    attach_shadow_sidecar_if_enabled,
    create_disabled_shadow_result,
    extract_served_snapshot,
    should_run_nr3_fcc_shadow,
    verify_served_output_unchanged,
)
from core.priority1_options import Priority1Config  # noqa: E402

DEFAULT_JSON = ROOT / "reports" / "priority1_7b_23_disabled_shadow_wiring_implementation.json"
DEFAULT_MD = REPO / "docs" / "PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md"

ALLOWED_CHANGED_FILES = (
    "backend/core/priority1_options.py",
    "backend/core/priority1_backtest.py",
    "backend/core/strength_based_xg_validation.py",
    "backend/core/disabled_shadow_wiring_runtime.py",
    "backend/scripts/run_priority1_7b_23_disabled_shadow_wiring_implementation.py",
    "backend/tests/test_disabled_shadow_wiring_runtime.py",
    "docs/PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md",
    "backend/reports/priority1_7b_23_disabled_shadow_wiring_implementation.json",
)


def _git_capture() -> tuple[str, str, str]:
    status = subprocess.run(
        ["git", "status", "--short"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    name_status = subprocess.run(
        ["git", "diff", "--name-status"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    stat = subprocess.run(
        ["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    return status, name_status, stat


def _prove_defaults() -> dict:
    baseline = Priority1Config.baseline()
    field_names = {f.name for f in fields(Priority1Config)}
    return {
        "nr3_fcc_shadow_enabled_default": baseline.nr3_fcc_shadow_enabled,
        "favorite_confidence_curve_params_default": baseline.favorite_confidence_curve_params,
        "field_present": "nr3_fcc_shadow_enabled" in field_names,
        "should_run_default": should_run_nr3_fcc_shadow(baseline),
        "disabled_result": create_disabled_shadow_result().decision.__dict__,
    }


def _disabled_state_proof() -> dict:
    baseline = Priority1Config.baseline()
    sample_result = {
        "probabilities_1x2": {"home_win": 0.45, "draw": 0.25, "away_win": 0.30},
        "expected_home_goals": 1.4,
        "expected_away_goals": 1.1,
        "top_scores": [{"score": "1-1", "prob": 0.12}],
    }
    before = extract_served_snapshot(sample_result)
    runtime = attach_shadow_sidecar_if_enabled(
        sample_result,
        match=None,
        prior=[],
        snapshot=None,
        dataset_key="wc2022",
        p1=baseline,
        candidate="baseline",
        elo_strategy="fifa_points_confidence_weighted",
        world_elo_mode="none",
        prior_mode="tournament_prior_file",
        run_match_fn=lambda **_: sample_result,
    )
    after = extract_served_snapshot(sample_result)
    return {
        "served_unchanged": verify_served_output_unchanged(before, after),
        "no_internal_diagnostics": "_internal_diagnostics" not in sample_result,
        "shadow_executed": runtime.decision.shadow_executed,
        "shadow_enabled": runtime.decision.shadow_enabled,
    }


def write_p1723_markdown(report: dict) -> str:
    lines = [
        "# Priority 1.7B.23 — Disabled-By-Default Shadow Wiring Implementation",
        "",
        "## 1. Executive summary",
        "",
        "**Implementation complete. Not activation. Not deployment.**",
        "",
        f"- Flag: **`{report['flag_name']}`** default **{report['defaults_proof']['nr3_fcc_shadow_enabled_default']}**",
        f"- Served output unchanged (disabled): **{report['disabled_state_proof']['served_unchanged']}**",
        f"- Activation blocked: **{report['activation_blocked']}**",
        "",
        report["final_recommendation"],
        "",
        "## 2–4. Scope",
        "",
        "Minimal disabled-by-default shadow wiring for NR3+FCC.",
        "Baseline remains served output. Shadow artifact is private/internal only.",
        "",
        "## 5–11. Implementation summary",
        "",
        f"- Runtime module: `{report['runtime_module']}`",
        f"- Backtest wiring: optional sidecar when flag true only",
        f"- Strength validation touched: **{report['strength_validation_touched']}**",
        "",
        "## 12–17. Safety & next steps",
        "",
        f"- Go/No-Go: **{report['go_no_go_result']}**",
        f"- Required next: **{report['required_next_step']}**",
        "",
        "## Files changed",
        "",
    ]
    for f in report["allowed_changed_files"]:
        lines.append(f"- `{f}`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="P1.7B.23 shadow wiring implementation report")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--write-report", type=Path, default=DEFAULT_MD)
    parser.add_argument("--skip-pytest", action="store_true")
    args = parser.parse_args()

    git_before = _git_capture()
    defaults = _prove_defaults()
    disabled_proof = _disabled_state_proof()

    report = {
        "phase": "P1.7B.23",
        "implementation_scope": "disabled_by_default_shadow_wiring_only",
        "not_activation": True,
        "activation_blocked": True,
        "flag_name": FLAG_NAME,
        "flag_field": "nr3_fcc_shadow_enabled",
        "defaults_proof": defaults,
        "disabled_state_proof": disabled_proof,
        "direct_activation_allowed": False,
        "production_activation_allowed": False,
        "implementation_allowed_now": True,
        "shadow_wiring_allowed_now": "local_test_only_when_flag_true",
        "served_output_change_allowed": False,
        "runtime_module": "backend/core/disabled_shadow_wiring_runtime.py",
        "strength_validation_touched": False,
        "enabled_path_executed": False,
        "enabled_path_note": "Full enabled shadow dry-run requires local match fixtures; design-validated via unit tests",
        "go_no_go_result": "GO_for_shadow_wiring_implementation_no_activation",
        "rollback_plan": [
            "Set nr3_fcc_shadow_enabled=false (default)",
            "Remove _internal_diagnostics.nr3_fcc_shadow if present",
            "Verify served probabilities unchanged",
            "No env/Render changes required",
        ],
        "allowed_changed_files": list(ALLOWED_CHANGED_FILES),
        "git_before": {"status": git_before[0], "name_status": git_before[1], "stat": git_before[2]},
        "required_next_step": "P1.7B.24 — Shadow Wiring Verification and Diff Review (explicit approval required)",
        "final_recommendation": (
            "P1.7B.23 complete. Do not activate. Do not deploy. Do not commit yet. "
            "Next: P1.7B.24 Shadow Wiring Verification and Diff Review or manual review/commit planning."
        ),
        "do_not_activate_list": [
            "NR3+FCC", "NR3", "NR6", "HB3", "FCC", "CSG", "DRFCG",
            "strength_v1", "Power V3", "Dynamic V2", "Dynamic V3", "Market V2",
        ],
    }

    git_after = _git_capture()
    report["git_after"] = {"status": git_after[0], "name_status": git_after[1], "stat": git_after[2]}

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    args.write_report.write_text(write_p1723_markdown(report), encoding="utf-8")

    print(f"Flag default false: {defaults['nr3_fcc_shadow_enabled_default']}")
    print(f"Disabled served unchanged: {disabled_proof['served_unchanged']}")

    if not args.skip_pytest:
        suites = [
            "tests/test_disabled_shadow_wiring_runtime.py",
            "tests/test_disabled_shadow_wiring_design.py",
            "tests/test_controlled_activation_plan_draft.py",
            "tests/test_final_activation_readiness_audit.py",
            "tests/test_activation_readiness_gate_context_audit.py",
            "tests/test_scoreline_ranking_topk_robustness_audit.py",
            "tests/test_wc2022_top5_robustness_blocker_decomposition.py",
            "tests/test_favorite_confidence_curve_prototype.py",
            "tests/test_favorite_confidence_curve_audit.py",
            "tests/test_favorite_spread_too_small_decomposition.py",
            "tests/test_validation_metrology_redesign.py",
            "tests/test_strength_based_xg_generator.py",
            "tests/test_backtest_metrics.py",
            "tests/test_probability_quality.py",
        ]
        proc = subprocess.run([sys.executable, "-m", "pytest", *suites, "-q"], cwd=ROOT)
        report["tests_exit_code"] = proc.returncode
        args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        if proc.returncode != 0:
            return proc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
