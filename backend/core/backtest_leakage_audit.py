"""Phase 2C — Backtest leakage / walk-forward risk audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data.tournament_data import DATASET_REGISTRY, dataset_documentation


@dataclass
class LeakageAuditReport:
    leakage_risk_level: str  # low | medium | high
    findings: list[str]
    recommendations: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_backtest_leakage(*, backend_root: Path | None = None) -> LeakageAuditReport:
    """Report whether shadow backtests may use future information."""
    root = backend_root or Path(__file__).resolve().parent.parent
    findings: list[str] = []
    recommendations: list[str] = []
    details: dict[str, Any] = {}

    nt_ratings = root / "data" / "cache" / "nt_ratings.json"
    global_ratings = root / "data" / "global_ratings.json"
    details["nt_ratings_exists"] = nt_ratings.exists()
    details["global_ratings_exists"] = global_ratings.exists()

    if nt_ratings.exists():
        findings.append(
            "nt_ratings.json is a global/static snapshot — if used for backtests, "
            "it may include match results after the tested game date."
        )
        recommendations.append(
            "Tournament backtests should use pre-tournament FIFA_ELO snapshots "
            "(wc2018.py, wc2022.py, etc.), not nt_ratings.json."
        )

    findings.append(
        "Production LiveDataManager uses current FIFA_ELO_2026 + optional Elo overrides — "
        "not match-date walk-forward Elo."
    )
    recommendations.append(
        "Treat NationalTeamBacktestRunner on LiveDataManager as high leakage risk; "
        "prefer TournamentSnapshotDataManager for historical evaluation."
    )

    findings.append(
        "Effective Elo world anchors read from global_ratings.json (manual/current World Elo) "
        "even when internal Elo is a pre-tournament snapshot — temporal mismatch."
    )
    recommendations.append(
        "World Elo anchoring in shadow backtests is diagnostic only; "
        "historical world Elo at match date is not available offline."
    )

    snapshot_datasets = [
        k for k, ds in DATASET_REGISTRY.items() if ds.rating_mode == "pre_tournament_snapshot"
    ]
    live_datasets = [
        k for k, ds in DATASET_REGISTRY.items() if ds.rating_mode == "live_snapshot"
    ]
    details["snapshot_datasets"] = snapshot_datasets
    details["live_snapshot_datasets"] = live_datasets
    details["dataset_mapping"] = dataset_documentation()

    findings.append(
        f"Tournament datasets {snapshot_datasets} use fixed pre-tournament Elo — "
        "static snapshot, not walk-forward within tournament."
    )
    findings.append(
        "Maher opponent-aware xG uses build_all_matches() history bundle — "
        "includes results from tournaments after the tested match (look-ahead in xG path)."
    )
    recommendations.append(
        "Current full-pipeline backtest is NOT walk-forward — README must warn before "
        "trusting absolute metric levels."
    )

    if live_datasets:
        findings.append(
            f"Dataset(s) {live_datasets} use FIFA_ELO_2026 live registry — "
            "ratings reflect post-qualification state, not pre-match."
        )

    findings.append(
        "Historical match results in bundled nt_history are included in opponent_index "
        "used to predict those same-era matches."
    )

    risk = "medium"
    if nt_ratings.exists() and live_datasets:
        risk = "high"
    elif not snapshot_datasets:
        risk = "high"
    else:
        risk = "medium"

    details["walk_forward"] = False
    details["static_snapshot_tournaments"] = True

    return LeakageAuditReport(
        leakage_risk_level=risk,
        findings=findings,
        recommendations=recommendations,
        details=details,
    )


def format_leakage_report(report: LeakageAuditReport) -> str:
    lines = [
        f"Leakage risk level: {report.leakage_risk_level.upper()}",
        "",
        "Findings:",
    ]
    for item in report.findings:
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Recommendations:")
    for item in report.recommendations:
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Dataset mapping:")
    for key, desc in report.details.get("dataset_mapping", {}).items():
        lines.append(f"  {key}: {desc}")
    return "\n".join(lines)
