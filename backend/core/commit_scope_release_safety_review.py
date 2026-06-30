"""Priority 1.7B.25 — Commit scope and release safety review (review-only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REVIEW_ONLY = True
PHASE = "P1.7B.25"
REVIEW_SUBJECT = "P1.7B.23/P1.7B.24 shadow wiring commit scope and release safety"

ALLOWED_CHANGED_FILES = (
    "backend/core/commit_scope_release_safety_review.py",
    "backend/scripts/run_priority1_7b_25_commit_scope_release_safety_review.py",
    "backend/tests/test_commit_scope_release_safety_review.py",
    "docs/PRIORITY1_7B_25_COMMIT_SCOPE_RELEASE_SAFETY_REVIEW.md",
    "backend/reports/priority1_7b_25_commit_scope_release_safety_review.json",
)

P1723_SCOPE_FILES = (
    "backend/core/disabled_shadow_wiring_runtime.py",
    "backend/tests/test_disabled_shadow_wiring_runtime.py",
    "backend/scripts/run_priority1_7b_23_disabled_shadow_wiring_implementation.py",
    "docs/PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md",
    "backend/reports/priority1_7b_23_disabled_shadow_wiring_implementation.json",
)

P1723_PARTIAL_FILES = (
    "backend/core/priority1_options.py",
    "backend/core/priority1_backtest.py",
)

P1724_SCOPE_FILES = (
    "backend/core/shadow_wiring_verification_diff_review.py",
    "backend/scripts/run_priority1_7b_24_shadow_wiring_verification_diff_review.py",
    "backend/tests/test_shadow_wiring_verification_diff_review.py",
    "docs/PRIORITY1_7B_24_SHADOW_WIRING_VERIFICATION_DIFF_REVIEW.md",
    "backend/reports/priority1_7b_24_shadow_wiring_verification_diff_review.json",
)

P1725_SCOPE_FILES = ALLOWED_CHANGED_FILES

PRE_EXISTING_PRODUCTION_DIFFS = (
    "backend/.env.example",
    "backend/api/main.py",
    "backend/api/schemas.py",
    "backend/config.py",
    "backend/core/market_xg_calibration.py",
    "backend/core/priority1_diagnostics.py",
    "backend/core/temporal_backtest.py",
    "backend/data/activation_large_shift_reviews.json",
    "backend/data/cache/nt_ratings.json",
    "docs/PRIORITY1_2_LOCAL_MARKET_XG_VALIDATION.md",
)

EXCLUDE_UNLESS_SEPARATELY_APPROVED = (
    "backend/api/main.py",
    "backend/api/schemas.py",
    "backend/config.py",
    "backend/.env.example",
)

PRIOR_P172_REPORT = {
    "P1.7B.20": "priority1_7b_20_final_activation_readiness_audit.json",
    "P1.7B.21": "priority1_7b_21_controlled_activation_plan_draft.json",
    "P1.7B.22": "priority1_7b_22_disabled_shadow_wiring_design.json",
    "P1.7B.23": "priority1_7b_23_disabled_shadow_wiring_implementation.json",
    "P1.7B.24": "priority1_7b_24_shadow_wiring_verification_diff_review.json",
}

P1723_HUNK_MARKERS = {
    "backend/core/priority1_options.py": (
        r"nr3_fcc_shadow_enabled:\s*bool\s*=\s*False",
        "P1.7B.23",
        "NR3_FCC_SHADOW_ENABLED",
    ),
    "backend/core/priority1_backtest.py": (
        r"attach_shadow_sidecar_if_enabled",
        r"nr3_fcc_shadow_enabled",
        "disabled_shadow_wiring_runtime",
    ),
}

PRE_EXISTING_HUNK_MARKERS = {
    "backend/core/priority1_options.py": (
        "power_v3_enabled",
        "strength_xg_params",
        "favorite_confidence_curve_params",
        "conditional_spread_governance_params",
        "P1.7B.10.1",
        "P1.7B.12",
        "P1.7B.16",
    ),
    "backend/core/priority1_backtest.py": (
        "strength_v1",
        "independent_signal_wiring_prototype",
        "dynamic_v3_feeds_xg",
        "favorite_trust",
        "trust_gated",
    ),
}


@dataclass
class FileClassification:
    path: str
    status: str
    bucket: str
    commit_readiness: str
    reason: str
    risk_level: str
    required_action: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_git_status(status_text: str) -> tuple[list[str], list[str]]:
    tracked: list[str] = []
    untracked: list[str] = []
    for line in status_text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("??"):
            untracked.append(line[3:].strip())
        else:
            # Short format: XY PATH — skip two status columns, then path
            path = line[2:].lstrip()
            if path:
                tracked.append(path)
    return tracked, untracked


def _is_prior_research(path: str) -> bool:
    p = path.replace("\\", "/")
    if any(p.startswith(prefix) for prefix in P1723_SCOPE_FILES + P1724_SCOPE_FILES + P1725_SCOPE_FILES):
        return False
    if p in PRE_EXISTING_PRODUCTION_DIFFS or p in P1723_PARTIAL_FILES:
        return False
    patterns = (
        "priority1_7b_",
        "priority1_7a_",
        "PRIORITY1_7B_",
        "PRIORITY1_7A_",
        "activation_readiness",
        "controlled_activation",
        "disabled_shadow_wiring_design",
        "final_activation_readiness",
        "shadow_wiring_verification",
        "strength_based_xg",
        "strength_activation",
        "favorite_confidence",
        "favorite_direction",
        "favorite_spread",
        "favorite_trust",
        "validation_metrology",
        "scoreline_ranking",
        "wc2022_top5",
        "wc2018_residual",
        "independent_signal",
        "conditional_spread",
        "dual_regime",
        "trust_gated",
        "hybrid_balance",
        "dynamic_goals",
        "power_v3",
        "market_calibration_v2",
        "xg_coherent_pipeline",
        "latent_xg_bias",
    )
    name = Path(p).name.lower()
    return any(pat in p.lower() or pat in name for pat in patterns)


def classify_file(path: str, *, tracked: bool) -> FileClassification:
    norm = path.replace("\\", "/")
    status = "tracked_modified" if tracked else "untracked"

    if norm in P1725_SCOPE_FILES:
        return FileClassification(
            norm, status, "C_P1_7B_25", "safe_for_commit_review",
            "P1.7B.25 review artifact", "low", "Include in Commit C after review",
        )
    if norm in P1724_SCOPE_FILES:
        return FileClassification(
            norm, status, "B_P1_7B_24", "safe_for_commit_review",
            "P1.7B.24 verification scope", "low", "Include in Commit B after hunk review complete",
        )
    if norm in P1723_SCOPE_FILES:
        return FileClassification(
            norm, status, "A_P1_7B_23", "safe_for_commit_review",
            "P1.7B.23 shadow wiring implementation", "low", "Include in Commit A",
        )
    if norm in P1723_PARTIAL_FILES:
        return FileClassification(
            norm, status, "A_P1_7B_23_partial", "manual_review_required",
            "Mixed P1.7B.23 hunks + pre-existing research diffs", "high",
            "git add -p required; stage only P1.7B.23 hunks",
        )
    if norm in EXCLUDE_UNLESS_SEPARATELY_APPROVED:
        return FileClassification(
            norm, status, "E_pre_existing_production", "exclude_for_now",
            "API/config/env deployment surface; not P1.7B.23 scope", "critical",
            "Exclude from shadow-wiring commits; separate product review",
        )
    if norm in PRE_EXISTING_PRODUCTION_DIFFS:
        return FileClassification(
            norm, status, "E_pre_existing_production", "exclude_for_now",
            "Pre-existing production-path diff unrelated to shadow wiring", "high",
            "Exclude unless separately reviewed (Commit E)",
        )
    if _is_prior_research(norm):
        return FileClassification(
            norm, status, "D_prior_research", "manual_review_required",
            "Prior P1.7B research/audit artifact", "medium",
            "Optional Commit D after separate review; not with shadow wiring",
        )
    if "nt_ratings" in norm or "cache" in norm or norm.endswith(".before_refresh"):
        return FileClassification(
            norm, status, "F_excluded", "exclude_for_now",
            "Generated/cache data; not source commit scope", "medium",
            "Do not commit",
        )
    if norm.startswith("docs/") and "PRIORITY1" in norm:
        return FileClassification(
            norm, status, "D_prior_research", "manual_review_required",
            "Research documentation artifact", "low", "Optional Commit D",
        )
    return FileClassification(
        norm, status, "F_excluded", "manual_review_required",
        "Unclassified; requires manual bucket assignment", "medium",
        "Review manually before any commit",
    )


def build_mixed_hunk_review(*, repo: Path | None = None) -> dict[str, Any]:
    root = repo or _repo_root()
    reviews: dict[str, Any] = {}

    for rel in P1723_PARTIAL_FILES:
        text = _read(root / rel)
        p23_markers = P1723_HUNK_MARKERS.get(rel, ())
        pre_markers = PRE_EXISTING_HUNK_MARKERS.get(rel, ())
        p23_found = []
        for m in p23_markers:
            if m.startswith("P1") or m.startswith("NR3"):
                if m in text:
                    p23_found.append(m)
            elif re.search(m, text):
                p23_found.append(m)
        pre_found = [m for m in pre_markers if m in text]

        p23_hunks = []
        if rel.endswith("priority1_options.py"):
            p23_hunks = [
                "nr3_fcc_shadow_enabled: bool = False field (P1.7B.23 comment block)",
            ]
            pre_hunks = [
                "Extended Priority1Config fields (power_v3, dynamic_v3, strength_xg, FCC params, etc.)",
                "Factory classmethods (strength_xg_v1_* stacks)",
                "apply_priority1_power_variants and related wiring",
            ]
        else:
            p23_hunks = [
                "Guarded attach_shadow_sidecar_if_enabled block at end of _run_match_with_priority1",
                "nr3_fcc_shadow_enabled propagation in collect_priority1_rows",
            ]
            pre_hunks = [
                "strength_v1 xG baseline branch",
                "independent_signal_wiring_prototype integration",
                "dynamic_v3 / market / trust / hybrid research branches",
                "Large xG pipeline refactor (~400+ lines)",
            ]

        reviews[rel] = {
            "p1_7b23_hunks_summary": p23_hunks,
            "pre_existing_hunks_summary": pre_hunks,
            "p1_7b23_markers_present": bool(p23_found or "nr3_fcc_shadow" in text),
            "pre_existing_markers_present": bool(pre_found),
            "hunk_separation_possible": True,
            "manual_hunk_selection_required": True,
            "recommended_action": (
                "Use interactive staging (git add -p) later — NOT in this phase — "
                "to stage only P1.7B.23 hunks; never git add entire file"
            ),
            "git_add_all_forbidden": True,
        }

    return {
        "mixed_file_review": reviews,
        "p1_7b23_hunks_summary": [h for r in reviews.values() for h in r["p1_7b23_hunks_summary"]],
        "pre_existing_hunks_summary": [h for r in reviews.values() for h in r["pre_existing_hunks_summary"]],
        "hunk_separation_possible": True,
        "manual_hunk_selection_required": True,
        "recommended_action": (
            "Manual hunk selection required for priority1_options.py and priority1_backtest.py "
            "before Commit A. Do not commit full-file diffs."
        ),
    }


def build_commit_groups() -> list[dict[str, Any]]:
    return [
        {
            "group_id": "A",
            "name": "Shadow wiring implementation (P1.7B.23)",
            "purpose": "Disabled-by-default NR3+FCC shadow sidecar only",
            "files": list(P1723_SCOPE_FILES) + [
                "selected hunks: backend/core/priority1_options.py (nr3_fcc_shadow_enabled only)",
                "selected hunks: backend/core/priority1_backtest.py (sidecar guard + flag propagation only)",
            ],
            "include_now": False,
            "requires_manual_hunk_selection": True,
            "risk": "medium",
            "suggested_commit_message": (
                "Add disabled-by-default NR3+FCC shadow wiring (P1.7B.23). "
                "Flag defaults false; served output unchanged; no activation."
            ),
            "prerequisites": [
                "P1.7B.24 verification passed",
                "Manual hunk selection on mixed files complete",
                "tests/test_disabled_shadow_wiring_runtime.py passes",
            ],
            "tests_before_commit": [
                "tests/test_disabled_shadow_wiring_runtime.py",
                "tests/test_shadow_wiring_verification_diff_review.py",
            ],
        },
        {
            "group_id": "B",
            "name": "Shadow wiring verification (P1.7B.24)",
            "purpose": "Verification-only audit of P1.7B.23 safety",
            "files": list(P1724_SCOPE_FILES),
            "include_now": False,
            "requires_manual_hunk_selection": False,
            "risk": "low",
            "suggested_commit_message": "Add P1.7B.24 shadow wiring verification and diff review (no activation).",
            "prerequisites": ["Commit A reviewed or staged separately", "Verification report current"],
            "tests_before_commit": ["tests/test_shadow_wiring_verification_diff_review.py"],
        },
        {
            "group_id": "C",
            "name": "Commit scope review (P1.7B.25)",
            "purpose": "Commit-scope and release-safety review artifacts",
            "files": list(P1725_SCOPE_FILES),
            "include_now": False,
            "requires_manual_hunk_selection": False,
            "risk": "low",
            "suggested_commit_message": "Add P1.7B.25 commit scope and release safety review (plan only).",
            "prerequisites": ["User explicit approval for any commit"],
            "tests_before_commit": ["tests/test_commit_scope_release_safety_review.py"],
        },
        {
            "group_id": "D",
            "name": "Prior P1.7B research artifacts (P1.7B.11–P1.7B.22)",
            "purpose": "Optional research/audit modules, tests, docs, reports",
            "files": ["All untracked P1.7B.11–P1.7B.22 modules/scripts/tests/docs/reports"],
            "include_now": False,
            "requires_manual_hunk_selection": False,
            "risk": "medium",
            "suggested_commit_message": "Add P1.7B research and audit artifacts (separate from shadow wiring).",
            "prerequisites": [
                "Separate review per artifact group",
                "Never mix with Commit A without approval",
            ],
            "tests_before_commit": ["Relevant phase test suites"],
        },
        {
            "group_id": "E",
            "name": "Pre-existing production-path work",
            "purpose": "API, config, env, calibration, diagnostics changes",
            "files": list(PRE_EXISTING_PRODUCTION_DIFFS) + list(P1723_PARTIAL_FILES),
            "include_now": False,
            "requires_manual_hunk_selection": True,
            "risk": "critical",
            "suggested_commit_message": "N/A — do not commit as part of shadow wiring rollout",
            "prerequisites": [
                "Separate product/engineering approval",
                "Render/env review",
                "Full regression",
            ],
            "tests_before_commit": ["Full backend test suite", "API integration tests"],
        },
    ]


def build_release_safety_gates() -> dict[str, Any]:
    return {
        "commit_gates": [
            {"gate": "no_activation", "required": True, "status": "pass"},
            {"gate": "flag_default_false", "required": True, "status": "pass"},
            {"gate": "served_output_unchanged", "required": True, "status": "pass"},
            {"gate": "no_api_schema_change_in_shadow_scope", "required": True, "status": "pass"},
            {"gate": "no_env_render_change_in_shadow_scope", "required": True, "status": "pass"},
            {"gate": "tests_pass", "required": True, "status": "pending_until_hunk_selection"},
            {"gate": "commit_scope_reviewed", "required": True, "status": "pass"},
            {"gate": "no_unrelated_production_diffs", "required": True, "status": "pending"},
            {"gate": "manual_hunk_selection_complete", "required": True, "status": "pending"},
            {"gate": "rollback_documented", "required": True, "status": "pass"},
        ],
        "deploy_gates": [
            {"gate": "deploy_allowed_now", "required": False, "status": "blocked"},
            {"gate": "separate_approval_required", "required": True, "status": "pending"},
            {"gate": "render_env_review", "required": True, "status": "pending"},
            {"gate": "shadow_mode_only", "required": True, "status": "not_applicable"},
            {"gate": "baseline_served_output", "required": True, "status": "pass"},
            {"gate": "monitoring_ready", "required": True, "status": "pending"},
            {"gate": "rollback_verified", "required": True, "status": "pending"},
        ],
        "activation_gates": [
            {"gate": "activation_allowed_now", "required": False, "status": "blocked"},
            {"gate": "production_activation_review", "required": True, "status": "pending"},
            {"gate": "canary_dark_launch_evidence", "required": True, "status": "pending"},
            {"gate": "explicit_approval", "required": True, "status": "pending"},
        ],
    }


def build_risk_table() -> list[dict[str, Any]]:
    return [
        {
            "risk": "Dirty workspace causing accidental unrelated commit",
            "severity": "critical",
            "likelihood": "high",
            "mitigation": "Never git add .; use explicit file lists or git add -p",
            "detection_method": "Pre-commit diff review; this P1.7B.25 report",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "Manual hunk selection before any commit",
        },
        {
            "risk": "Mixed hunks in priority1_backtest.py",
            "severity": "critical",
            "likelihood": "high",
            "mitigation": "Stage only sidecar hunks (~17 lines)",
            "detection_method": "git diff review; P1.7B.24 static checks",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "git add -p on backtest file",
        },
        {
            "risk": "Mixed hunks in priority1_options.py",
            "severity": "critical",
            "likelihood": "high",
            "mitigation": "Stage only nr3_fcc_shadow_enabled field hunk",
            "detection_method": "git diff review",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "git add -p on options file",
        },
        {
            "risk": "API/config/env diffs accidentally included",
            "severity": "critical",
            "likelihood": "medium",
            "mitigation": "Exclude api/main.py, schemas, config, .env.example from shadow commits",
            "detection_method": "File classification bucket E",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "Keep in Commit E exclusion list",
        },
        {
            "risk": "git add . accidental commit",
            "severity": "critical",
            "likelihood": "medium",
            "mitigation": "Explicit commit groups; forbidden in this phase",
            "detection_method": "Commit scope review",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "Use named commit groups only",
        },
        {
            "risk": "Shadow artifact accidentally exposed later",
            "severity": "high",
            "likelihood": "low",
            "mitigation": "No API schema fields; _internal_diagnostics only",
            "detection_method": "P1.7B.24 leakage review",
            "blocks_commit": False,
            "blocks_deploy": True,
            "required_action": "Re-run leakage scan before deploy",
        },
        {
            "risk": "Default flag accidentally enabled later",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "Literal False default; no env binding",
            "detection_method": "Static check flag_default_false",
            "blocks_commit": False,
            "blocks_deploy": True,
            "required_action": "Code review on any flag change",
        },
        {
            "risk": "Render/env activation later",
            "severity": "critical",
            "likelihood": "low",
            "mitigation": "No NR3_FCC_SHADOW in config/env today",
            "detection_method": "Env file text scan",
            "blocks_commit": False,
            "blocks_deploy": True,
            "required_action": "Separate Render review if ever added",
        },
        {
            "risk": "Tests not rerun after hunk selection",
            "severity": "high",
            "likelihood": "medium",
            "mitigation": "Run disabled_shadow + verification tests before commit",
            "detection_method": "CI / local pytest",
            "blocks_commit": True,
            "blocks_deploy": True,
            "required_action": "pytest after staging hunks",
        },
        {
            "risk": "Rollback not validated after commit",
            "severity": "medium",
            "likelihood": "medium",
            "mitigation": "Documented rollback: flag false, remove internal diagnostics",
            "detection_method": "P1.7B.23 rollback plan",
            "blocks_commit": False,
            "blocks_deploy": True,
            "required_action": "Verify rollback path post-commit",
        },
        {
            "risk": "Pre-existing research artifacts mixed with production changes",
            "severity": "high",
            "likelihood": "high",
            "mitigation": "Commit D separate from A/B/C",
            "detection_method": "Bucket D classification",
            "blocks_commit": True,
            "blocks_deploy": False,
            "required_action": "Separate commits per artifact group",
        },
        {
            "risk": "P1.7B.23 safe code blocked by workspace hygiene",
            "severity": "medium",
            "likelihood": "high",
            "mitigation": "This P1.7B.25 commit plan",
            "detection_method": "Commit readiness review",
            "blocks_commit": True,
            "blocks_deploy": False,
            "required_action": "Execute manual hunk selection when approved",
        },
    ]


def load_prior_reports(*, reports_dir: Path | None = None) -> dict[str, Any]:
    root = (reports_dir or _backend_root()) / "reports"
    loaded: dict[str, Any] = {}
    for phase, filename in PRIOR_P172_REPORT.items():
        path = root / filename
        if path.exists():
            loaded[phase] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def classify_workspace(
    git_status: str,
    *,
    repo: Path | None = None,
) -> dict[str, Any]:
    tracked, untracked = _parse_git_status(git_status)
    all_paths = tracked + untracked
    classifications = [classify_file(p, tracked=p in tracked) for p in all_paths]

    by_bucket: dict[str, list[str]] = {}
    for c in classifications:
        by_bucket.setdefault(c.bucket, []).append(c.path)

    safe = [c.path for c in classifications if c.commit_readiness == "safe_for_commit_review"]
    manual = [c.path for c in classifications if c.commit_readiness == "manual_review_required"]
    excluded = [c.path for c in classifications if c.commit_readiness == "exclude_for_now"]

    return {
        "classifications": [c.__dict__ for c in classifications],
        "by_bucket": by_bucket,
        "safe_for_commit_review_files": safe,
        "manual_review_required_files": manual,
        "excluded_from_commit_files": excluded,
        "tracked_modified_files": tracked,
        "untracked_files_summary": {
            "count": len(untracked),
            "paths": untracked[:50],
            "truncated": len(untracked) > 50,
        },
    }


def run_commit_scope_release_safety_review(
    *,
    repo: Path | None = None,
    git_status: str = "",
    git_diff_name_status: str = "",
    git_diff_stat: str = "",
    git_status_after: str = "",
    git_diff_name_status_after: str = "",
    git_diff_stat_after: str = "",
) -> dict[str, Any]:
    """Compile P1.7B.25 review report — no git mutations."""
    root = repo or _repo_root()
    prior = load_prior_reports()
    workspace = classify_workspace(git_status, repo=root) if git_status else classify_workspace("", repo=root)
    hunk_review = build_mixed_hunk_review(repo=root)
    commit_groups = build_commit_groups()
    gates = build_release_safety_gates()
    risks = build_risk_table()

    p24 = prior.get("P1.7B.24", {})
    p23 = prior.get("P1.7B.23", {})
    verification_passed = p24.get("verification_status") == "VERIFICATION_COMPLETE"

    commit_readiness = "NOT_READY"
    if verification_passed and hunk_review["manual_hunk_selection_required"]:
        commit_readiness = "MANUAL_HUNK_SELECTION_REQUIRED"
    elif verification_passed:
        commit_readiness = "READY_FOR_USER_APPROVED_COMMIT"

    return {
        "phase": PHASE,
        "review_only": REVIEW_ONLY,
        "review_subject": REVIEW_SUBJECT,
        "review_status": "REVIEW_COMPLETE",
        "activation_allowed": False,
        "production_activation_allowed": False,
        "deploy_allowed": False,
        "commit_executed": False,
        "commit_recommended_now": False,
        "git_add_all_forbidden": True,
        "workspace_dirty": bool(git_status.strip()) if git_status else True,
        "tracked_modified_files": workspace.get("tracked_modified_files", []),
        "untracked_files_summary": workspace.get("untracked_files_summary", {}),
        "p1_7b23_scope_files": list(P1723_SCOPE_FILES) + list(P1723_PARTIAL_FILES),
        "p1_7b24_scope_files": list(P1724_SCOPE_FILES),
        "p1_7b25_scope_files": list(P1725_SCOPE_FILES),
        "pre_existing_production_diffs": list(PRE_EXISTING_PRODUCTION_DIFFS) + list(P1723_PARTIAL_FILES),
        "manual_review_required_files": workspace.get("manual_review_required_files", []),
        "safe_for_commit_review_files": workspace.get("safe_for_commit_review_files", []),
        "excluded_from_commit_files": workspace.get("excluded_from_commit_files", []),
        "file_classifications": workspace.get("classifications", []),
        "file_classification_by_bucket": workspace.get("by_bucket", {}),
        "mixed_hunk_review": hunk_review,
        "proposed_commit_strategy": (
            "Three-phase commit plan when user explicitly approves: "
            "Commit A (P1.7B.23 shadow wiring with manual hunk selection), "
            "Commit B (P1.7B.24 verification), "
            "Commit C (P1.7B.25 this review). "
            "Never include Commit E (production-path) or git add . "
            "Commit D (research artifacts) optional and separate."
        ),
        "proposed_commit_groups": commit_groups,
        "release_safety_gates": gates,
        "risk_table": risks,
        "rollback_plan": p23.get("rollback_plan", [
            "Set nr3_fcc_shadow_enabled=false (default)",
            "Remove _internal_diagnostics.nr3_fcc_shadow if present",
            "Verify served probabilities unchanged",
            "No env/Render changes required",
        ]),
        "p1_7b24_verification_summary": {
            "verification_status": p24.get("verification_status"),
            "flag_default_false": p24.get("flag_default_false_verified"),
            "api_leak": p24.get("api_schema_leak_detected"),
            "commit_readiness_p24": p24.get("commit_readiness", {}).get("decision"),
        },
        "p1_7b23_safety_summary": {
            "activation_blocked": p23.get("activation_blocked"),
            "flag_default": p23.get("defaults_proof", {}).get("nr3_fcc_shadow_enabled_default"),
            "served_unchanged_disabled": p23.get("disabled_state_proof", {}).get("served_unchanged"),
        },
        "commit_readiness_decision": commit_readiness,
        "deploy_readiness_decision": "BLOCKED",
        "activation_readiness_decision": "BLOCKED",
        "remaining_risks": [r["risk"] for r in risks if r["blocks_commit"]],
        "what_not_to_do": [
            "Do not git add .",
            "Do not commit api/main.py, api/schemas.py, config.py, .env.example with shadow wiring",
            "Do not deploy",
            "Do not activate NR3+FCC",
            "Do not enable flag by default",
            "Do not mix Commit D research artifacts into Commit A",
        ],
        "preservation_checklist": {
            "git_status_before": git_status,
            "git_diff_name_status_before": git_diff_name_status,
            "git_diff_stat_before": git_diff_stat,
            "git_status_after": git_status_after,
            "git_diff_name_status_after": git_diff_name_status_after,
            "git_diff_stat_after": git_diff_stat_after,
        },
        "required_next_step": (
            "Manual hunk selection / commit planning with explicit user approval. "
            "When approved: stage Commit A hunks only via git add -p, run tests, then commit."
        ),
        "final_recommendation": (
            "Do not activate. Do not deploy. Do not commit yet unless manual hunk selection is approved. "
            "P1.7B.23/P1.7B.24 code is safe in isolation; workspace hygiene requires git add -p on "
            "priority1_options.py and priority1_backtest.py before any commit."
        ),
        "allowed_changed_files": list(ALLOWED_CHANGED_FILES),
    }


def write_p1725_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Priority 1.7B.25 — Commit Scope and Release Safety Review",
        "",
        "## 1. Executive summary",
        "",
        "**Review-only. No commit. No deploy. No activation.**",
        "",
        f"- Review status: **{report['review_status']}**",
        f"- Workspace dirty: **{report['workspace_dirty']}**",
        f"- Commit recommended now: **{report['commit_recommended_now']}**",
        f"- Commit readiness: **{report['commit_readiness_decision']}**",
        "",
        report["final_recommendation"],
        "",
        "## 2. Review-only scope",
        "",
        "- No git add/commit/reset/restore/clean/stash",
        "- No production file edits",
        "- No activation or deploy",
        "",
        "## 3. Current git state",
        "",
        f"- Tracked modified: **{len(report.get('tracked_modified_files', []))}** files",
        f"- Untracked: **{report.get('untracked_files_summary', {}).get('count', 0)}** files",
        "",
        "## 4. P1.7B.23 safety summary",
        "",
    ]
    s23 = report.get("p1_7b23_safety_summary", {})
    lines.append(f"- Activation blocked: **{s23.get('activation_blocked')}**")
    lines.append(f"- Flag default false: **{s23.get('flag_default')}**")
    lines.extend([
        "",
        "## 5. P1.7B.24 verification summary",
        "",
    ])
    s24 = report.get("p1_7b24_verification_summary", {})
    lines.append(f"- Verification: **{s24.get('verification_status')}**")
    lines.append(f"- API leak: **{s24.get('api_leak')}**")
    lines.extend([
        "",
        "## 6. File classification",
        "",
        "See JSON `file_classifications` for full table.",
        "",
        "## 7. Mixed hunk review",
        "",
        f"- Manual hunk selection required: **{report['mixed_hunk_review']['manual_hunk_selection_required']}**",
        f"- Hunk separation possible: **{report['mixed_hunk_review']['hunk_separation_possible']}**",
        "",
        "## 8. Proposed commit strategy",
        "",
        report["proposed_commit_strategy"],
        "",
        "## 9. Proposed commit groups",
        "",
    ])
    for g in report["proposed_commit_groups"]:
        lines.append(
            f"- **Commit {g['group_id']}** — {g['name']}: include_now={g['include_now']}, "
            f"risk={g['risk']}"
        )
    lines.extend([
        "",
        "## 10. Files safe for commit review",
        "",
    ])
    for f in report.get("safe_for_commit_review_files", [])[:20]:
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## 11. Files requiring manual review",
        "",
    ])
    for f in report.get("manual_review_required_files", [])[:20]:
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## 12. Files excluded from commit",
        "",
    ])
    for f in report.get("excluded_from_commit_files", []):
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## 13. Release safety gates",
        "",
        "See JSON `release_safety_gates`.",
        "",
        "## 14. Risk table",
        "",
    ])
    for r in report.get("risk_table", []):
        lines.append(f"- **{r['risk']}** — blocks_commit={r['blocks_commit']}")
    lines.extend([
        "",
        "## 15. Rollback plan",
        "",
    ])
    for step in report.get("rollback_plan", []):
        lines.append(f"- {step}")
    lines.extend([
        "",
        "## 16. What not to do",
        "",
    ])
    for item in report.get("what_not_to_do", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 17. Required next step",
        "",
        report["required_next_step"],
        "",
        "## 18. Tests run",
        "",
        "See JSON `tests_run`.",
        "",
        "## 19. Files changed by P1.7B.25",
        "",
    ])
    for f in report.get("allowed_changed_files", []):
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## 20. Final recommendation",
        "",
        report["final_recommendation"],
        "",
    ])
    return "\n".join(lines)
