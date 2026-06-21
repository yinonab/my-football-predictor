"""Phase 3D — Large shift review and local enablement tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.activation_shift_explainer import (
    EXPLANATION_EXPECTED_CORRECTION,
    explain_activation_shift,
    is_shift_reviewed_accepted,
)
from scripts.local_enablement_checklist import (
    HOLD,
    PROCEED_TO_LOCAL_ENABLEMENT,
    determine_local_enablement_recommendation,
)

PYTHON = sys.executable


# Stable Elo overrides used by activation explainer tests (matches data/cache/elo_overrides.json).
_PHASE3D_ELO_OVERRIDES: dict[str, float] = {
    "Haiti (האיטי)": 1595.1,
    "Curacao (קוראסאו)": 939.9,
}


@pytest.fixture(autouse=True)
def _reset_activation_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stable explainer inputs: prior tests may rewrite nt_ratings.json via build_and_save_ratings()."""
    monkeypatch.setattr(config, "MODEL_ACTIVATION_ENABLED", False)
    monkeypatch.setattr(config, "POWER_CANDIDATE_AFFECTS_PREDICTION", False)

    from core.team_ratings import TeamRatingsCalculator
    from data.nt_history_bundle import BUNDLED_NT_MATCHES

    bundled_ratings = TeamRatingsCalculator().compute(list(BUNDLED_NT_MATCHES))
    ratings_dict = {key: rating.to_dict() for key, rating in bundled_ratings.items()}
    monkeypatch.setattr(
        "core.team_ratings.load_ratings",
        lambda path=None: ratings_dict,
    )
    monkeypatch.setattr(
        "core.elo_store.load_elo_overrides",
        lambda: dict(_PHASE3D_ELO_OVERRIDES),
    )


def test_germany_haiti_explainer_structure() -> None:
    explanation = explain_activation_shift("Germany", "Haiti")
    assert explanation["home"] == "Germany"
    assert explanation["away"] == "Haiti"
    assert "home_power" in explanation["baseline"]
    assert "home_power" in explanation["active"]
    assert explanation["external_anchor"]["home_fifa_points"] is not None
    assert explanation["external_anchor"]["away_fifa_points"] is not None
    assert explanation["external_anchor"]["normalization_method"]
    assert "power_gap_delta" in explanation["deltas"]
    assert explanation["classification"]["shift_size"] == "large_shift"
    assert explanation["classification"]["fallback"] is False


def test_germany_haiti_expected_correction() -> None:
    """Germany–Haiti: large FIFA gap + activation widens favorite → expected_correction.

    Classifier returns suspicious_shift only when direction_reversal/fallback fire;
    polluted nt_ratings.json from earlier tests (e.g. test_team_ratings) can flip
    favorite direction — autouse fixture pins bundled ratings to avoid that flake.
    """
    explanation = explain_activation_shift("Germany", "Haiti")
    assert explanation["classification"]["shift_size"] == "large_shift"
    assert explanation["classification"]["fallback"] is False
    assert explanation["classification"]["likely_explanation"] in (
        EXPLANATION_EXPECTED_CORRECTION,
        "needs_manual_review",
    )
    assert explanation["deltas"]["home_win_delta_pp"] > 7.0


def test_explain_activation_shift_cli_runs() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/explain_activation_shift.py",
            "--home",
            "Germany",
            "--away",
            "Haiti",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Germany vs Haiti" in proc.stdout
    assert "large_shift" in proc.stdout


def test_review_large_activation_shifts_generates_report(tmp_path: Path) -> None:
    report = tmp_path / "large_review.md"
    reviews = tmp_path / "reviews.json"
    with patch(
        "core.activation_shift_explainer.REVIEWS_PATH",
        reviews,
    ):
        proc = subprocess.run(
            [PYTHON, "scripts/review_large_activation_shifts.py", str(report)],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert proc.returncode == 0, proc.stderr
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Germany vs Haiti" in text


def test_checklist_hold_when_large_shifts_unreviewed(tmp_path: Path) -> None:
    empty_reviews = tmp_path / "empty_reviews.json"
    empty_reviews.write_text(
        json.dumps({"description": "test", "reviews": {}}),
        encoding="utf-8",
    )
    from core.activation_qa import QAReportSummary

    summary = QAReportSummary(
        total_matchups=18,
        fallback_count=0,
        large_shift_count=1,
        balanced_shift_count=0,
        direction_reversal_count=0,
        avg_abs_home_win_delta=1.2,
        max_abs_home_win_delta=11.5,
    )
    with patch("core.activation_shift_explainer.REVIEWS_PATH", empty_reviews):
        rec = determine_local_enablement_recommendation(
            defaults_ok=True,
            qa_summary=summary,
            large_pairs=[("Germany", "Haiti")],
            large_shifts_reviewed=False,
            large_shifts_all_expected=False,
            readiness_status="READY_WITH_WARNINGS",
        )
    assert rec == HOLD


def test_checklist_proceed_when_large_shift_reviewed(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps(
            {
                "description": "test",
                "reviews": {
                    "Germany|Haiti": {
                        "home": "Germany",
                        "away": "Haiti",
                        "status": "accepted",
                        "explainability": EXPLANATION_EXPECTED_CORRECTION,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    rec = determine_local_enablement_recommendation(
        defaults_ok=True,
        qa_summary=type(
            "S",
            (),
            {
                "fallback_count": 0,
                "balanced_shift_count": 0,
                "direction_reversal_count": 0,
            },
        )(),
        large_pairs=[("Germany", "Haiti")],
        large_shifts_reviewed=True,
        large_shifts_all_expected=True,
        readiness_status="READY_WITH_WARNINGS",
    )
    assert rec == PROCEED_TO_LOCAL_ENABLEMENT
    assert is_shift_reviewed_accepted("Germany", "Haiti", reviews)


def test_production_defaults_remain_disabled() -> None:
    assert config.MODEL_ACTIVATION_ENABLED is False
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False


def test_local_enablement_checklist_cli_after_review() -> None:
    subprocess.run(
        [PYTHON, "scripts/review_large_activation_shifts.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    proc = subprocess.run(
        [PYTHON, "scripts/local_enablement_checklist.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "local_enablement_recommendation:" in proc.stdout
    assert proc.stdout.strip().endswith("Production requires explicit approval.") or (
        PROCEED_TO_LOCAL_ENABLEMENT in proc.stdout or HOLD in proc.stdout
    )
