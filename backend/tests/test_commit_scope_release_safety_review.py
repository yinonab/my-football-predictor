"""Tests for P1.7B.25 commit scope and release safety review."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from core.commit_scope_release_safety_review import (
    ALLOWED_CHANGED_FILES,
    EXCLUDE_UNLESS_SEPARATELY_APPROVED,
    P1723_PARTIAL_FILES,
    P1723_SCOPE_FILES,
    P1724_SCOPE_FILES,
    REVIEW_ONLY,
    build_commit_groups,
    build_mixed_hunk_review,
    build_release_safety_gates,
    build_risk_table,
    classify_file,
    run_commit_scope_release_safety_review,
    write_p1725_markdown,
)


def test_review_only_flag():
    assert REVIEW_ONLY is True


def test_module_no_prediction_imports():
    src = Path(__file__).resolve().parents[1] / "core" / "commit_scope_release_safety_review.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden = {"core.priority1_backtest", "core.disabled_shadow_wiring_runtime", "config"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden


def test_activation_deploy_commit_defaults():
    report = run_commit_scope_release_safety_review()
    assert report["activation_allowed"] is False
    assert report["deploy_allowed"] is False
    assert report["commit_executed"] is False
    assert report["commit_recommended_now"] is False
    assert report["production_activation_allowed"] is False


def test_p1723_files_classified():
    for path in P1723_SCOPE_FILES:
        c = classify_file(path, tracked=False)
        assert c.bucket == "A_P1_7B_23"
        assert c.commit_readiness == "safe_for_commit_review"


def test_p1724_files_classified():
    for path in P1724_SCOPE_FILES:
        c = classify_file(path, tracked=False)
        assert c.bucket == "B_P1_7B_24"


def test_mixed_files_require_manual_review():
    for path in P1723_PARTIAL_FILES:
        c = classify_file(path, tracked=True)
        assert c.commit_readiness == "manual_review_required"


def test_api_main_excluded():
    c = classify_file("backend/api/main.py", tracked=True)
    assert c.commit_readiness == "exclude_for_now"
    assert c.path in EXCLUDE_UNLESS_SEPARATELY_APPROVED


def test_api_schemas_excluded():
    c = classify_file("backend/api/schemas.py", tracked=True)
    assert c.commit_readiness == "exclude_for_now"


def test_config_excluded():
    c = classify_file("backend/config.py", tracked=True)
    assert c.commit_readiness == "exclude_for_now"


def test_env_example_excluded():
    c = classify_file("backend/.env.example", tracked=True)
    assert c.commit_readiness == "exclude_for_now"


def test_hunk_review_options():
    review = build_mixed_hunk_review()
    opts = review["mixed_file_review"]["backend/core/priority1_options.py"]
    assert opts["manual_hunk_selection_required"] is True
    assert any("nr3_fcc_shadow" in h for h in opts["p1_7b23_hunks_summary"])


def test_hunk_review_backtest():
    review = build_mixed_hunk_review()
    bt = review["mixed_file_review"]["backend/core/priority1_backtest.py"]
    assert bt["manual_hunk_selection_required"] is True
    assert any("attach_shadow" in h for h in bt["p1_7b23_hunks_summary"])


def test_git_add_all_forbidden():
    report = run_commit_scope_release_safety_review()
    assert report["git_add_all_forbidden"] is True


def test_commit_groups_proposed_not_executed():
    groups = build_commit_groups()
    assert len(groups) >= 5
    assert all(g["include_now"] is False for g in groups)


def test_release_safety_gates_exist():
    gates = build_release_safety_gates()
    assert "commit_gates" in gates
    assert "deploy_gates" in gates
    assert "activation_gates" in gates
    assert any(g["gate"] == "no_activation" for g in gates["commit_gates"])


def test_risk_table_dirty_workspace():
    risks = build_risk_table()
    assert any("Dirty workspace" in r["risk"] for r in risks)


def test_risk_table_mixed_hunk():
    risks = build_risk_table()
    assert any("Mixed hunks in priority1_backtest" in r["risk"] for r in risks)
    assert any("Mixed hunks in priority1_options" in r["risk"] for r in risks)


def test_rollback_plan_exists():
    report = run_commit_scope_release_safety_review()
    assert len(report["rollback_plan"]) >= 3


def test_final_recommendation_not_activation():
    report = run_commit_scope_release_safety_review()
    assert "Do not activate" in report["final_recommendation"]


def test_final_recommendation_not_deploy():
    report = run_commit_scope_release_safety_review()
    assert "Do not deploy" in report["final_recommendation"]


def test_final_recommendation_not_commit_execution():
    report = run_commit_scope_release_safety_review()
    assert "Do not commit yet" in report["final_recommendation"]


def test_report_json_and_markdown(tmp_path):
    report = run_commit_scope_release_safety_review()
    md = write_p1725_markdown(report)
    assert "Commit Scope" in md
    out = tmp_path / "p25.json"
    out.write_text(json.dumps(report, default=str), encoding="utf-8")
    assert json.loads(out.read_text())["phase"] == "P1.7B.25"


def test_allowed_files_count():
    assert len(ALLOWED_CHANGED_FILES) == 5


def test_review_complete():
    report = run_commit_scope_release_safety_review()
    assert report["review_status"] == "REVIEW_COMPLETE"


def test_deploy_activation_blocked():
    report = run_commit_scope_release_safety_review()
    assert report["deploy_readiness_decision"] == "BLOCKED"
    assert report["activation_readiness_decision"] == "BLOCKED"
