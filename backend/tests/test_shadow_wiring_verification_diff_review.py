"""Tests for P1.7B.24 shadow wiring verification and diff review."""

from __future__ import annotations

import json
from pathlib import Path

from core.shadow_wiring_verification_diff_review import (
    ALLOWED_CHANGED_FILES,
    DIAGNOSTIC_ONLY,
    PRESERVATION_FIRST,
    VERIFICATION_ONLY,
    build_leakage_review,
    load_prior_reports,
    run_shadow_wiring_verification_diff_review,
    run_static_checks,
    write_p1724_markdown,
)


def test_verification_only_flags():
    assert VERIFICATION_ONLY is True
    assert PRESERVATION_FIRST is True
    assert DIAGNOSTIC_ONLY is True


def test_module_no_prediction_imports():
    import ast

    src = Path(__file__).resolve().parents[1] / "core" / "shadow_wiring_verification_diff_review.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden_modules = {
        "core.priority1_backtest",
        "core.disabled_shadow_wiring_runtime",
        "core.strength_based_xg_generator",
        "config",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden_modules, node.module


def test_flag_default_false_detected():
    checks = run_static_checks()
    flag_check = next(c for c in checks if c.name == "flag_default_false")
    assert flag_check.passed is True


def test_env_activation_not_detected():
    report = run_shadow_wiring_verification_diff_review()
    assert report["env_activation_detected"] is False
    assert report["render_activation_detected"] is False


def test_api_leak_not_detected():
    leakage = build_leakage_review()
    assert leakage["leak_detected"] is False


def test_public_api_shadow_log_only_no_schema_leak():
    repo = Path(__file__).resolve().parents[2]
    schemas = (repo / "backend" / "api" / "schemas.py").read_text(encoding="utf-8", errors="replace")
    assert "nr3_fcc_shadow" not in schemas
    assert "_internal_diagnostics" not in schemas
    leakage = build_leakage_review(repo=repo)
    assert leakage["leak_detected"] is False


def test_config_env_shadow_flag_default_false():
    repo = Path(__file__).resolve().parents[2]
    cfg = (repo / "backend" / "config.py").read_text(encoding="utf-8", errors="replace")
    env = (repo / "backend" / ".env.example").read_text(encoding="utf-8", errors="replace")
    assert 'NR3_FCC_SHADOW_ENABLED", False)' in cfg
    assert "nr3_fcc_shadow_enabled=false" in env.lower()
    checks = run_static_checks(repo=repo)
    assert all(c.passed for c in checks if c.category == "env")


def test_runtime_helper_exists_on_disk():
    path = Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py"
    assert path.exists()


def test_activation_allowed_false_in_report():
    report = run_shadow_wiring_verification_diff_review()
    assert report["activation_allowed"] is False
    assert report["production_activation_allowed"] is False
    assert report["direct_activation_allowed"] is False


def test_deploy_allowed_false():
    report = run_shadow_wiring_verification_diff_review()
    assert report["deploy_allowed"] is False


def test_served_output_verification_detected():
    report = run_shadow_wiring_verification_diff_review()
    assert report["served_output_unchanged_verified"] is True


def test_sidecar_optional_detected():
    checks = run_static_checks()
    assert any(c.name == "sidecar_guarded_by_flag" and c.passed for c in checks)
    assert any(c.name == "api_sidecar_guarded_by_flag" and c.passed for c in checks)


def test_no_baseline_replacement():
    checks = run_static_checks()
    assert any(c.name == "no_baseline_replacement_pattern" and c.passed for c in checks)


def test_commit_readiness_requires_gates():
    report = run_shadow_wiring_verification_diff_review()
    assert report["commit_readiness"]["all_gates_passed"] is True
    assert report["commit_recommended"] is False


def test_final_recommendation_not_activation():
    report = run_shadow_wiring_verification_diff_review()
    assert "Do not activate" in report["final_recommendation"]
    assert "Do not commit yet" in report["final_recommendation"]


def test_p1723_detected():
    report = run_shadow_wiring_verification_diff_review()
    assert report["p1_7b_23_detected"] is True


def test_load_prior_reports():
    reports = load_prior_reports()
    assert "P1.7B.23" in reports


def test_markdown_and_json(tmp_path):
    report = run_shadow_wiring_verification_diff_review()
    md = write_p1724_markdown(report)
    assert "Verification and Diff Review" in md
    out = tmp_path / "p24.json"
    out.write_text(json.dumps(report, default=str), encoding="utf-8")
    assert json.loads(out.read_text())["phase"] == "P1.7B.24"


def test_allowed_files_count():
    assert len(ALLOWED_CHANGED_FILES) == 5


def test_disabled_runtime_no_env_read():
    rt = (Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "os.environ" not in rt
    assert "getenv" not in rt


def test_disabled_runtime_no_external_api():
    rt = (Path(__file__).resolve().parents[1] / "core" / "disabled_shadow_wiring_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "requests." not in rt
    assert "httpx" not in rt


def test_no_dataset_specific_logic_in_p1723_backtest():
    bt = (Path(__file__).resolve().parents[1] / "core" / "priority1_backtest.py").read_text(encoding="utf-8")
    shadow_block = bt.split("nr3_fcc_shadow_enabled")[0][-500:] + bt.split("nr3_fcc_shadow_enabled")[-1][:800]
    assert "wc2022" not in shadow_block.lower()
    assert "wc2018" not in shadow_block.lower()


def test_no_match_specific_logic_in_p1723_backtest():
    bt = (Path(__file__).resolve().parents[1] / "core" / "priority1_backtest.py").read_text(encoding="utf-8")
    idx = bt.find("nr3_fcc_shadow_enabled")
    block = bt[idx : idx + 600] if idx >= 0 else ""
    assert "germany" not in block.lower()
    assert "brazil" not in block.lower()


def test_no_scoreline_matrix_modification_in_p1723():
    bt = (Path(__file__).resolve().parents[1] / "core" / "priority1_backtest.py").read_text(encoding="utf-8")
    idx = bt.find("attach_shadow_sidecar_if_enabled")
    block = bt[idx : idx + 500] if idx >= 0 else ""
    assert "top5" not in block.lower()
    assert "scoreline_matrix" not in block.lower()


def test_private_shadow_artifact_verified():
    report = run_shadow_wiring_verification_diff_review()
    assert report["private_shadow_artifact_verified"] is True


def test_disabled_by_default_verified():
    report = run_shadow_wiring_verification_diff_review()
    assert report["disabled_by_default_verified"] is True


def test_accidental_activation_not_detected():
    report = run_shadow_wiring_verification_diff_review()
    assert report["accidental_activation_path_detected"] is False


def test_verification_complete():
    report = run_shadow_wiring_verification_diff_review()
    assert report["verification_status"] == "VERIFICATION_COMPLETE"
