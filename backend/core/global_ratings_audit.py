"""Phase 1.5 audit helpers — team/matchup reporting without changing predictions."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import config
from core.global_ratings import (
    WARNING_FORM_INFLATED,
    WARNING_LOW_CONFIDENCE,
    WARNING_MISSING_EXTERNAL,
    WARNING_POWER_COMPRESSED,
    build_match_diagnostics,
    build_team_diagnostics,
    english_name,
)
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager

SAMPLE_MATCHUP_PAIRS: list[tuple[str, str]] = [
    ("Portugal (פורטוגל)", "DR Congo (קונגו)"),
    ("Spain (ספרד)", "Cape Verde (כף ורד)"),
    ("Argentina (ארגנטינה)", "France (צרפת)"),
    ("Brazil (ברזיל)", "Morocco (מרוקו)"),
    ("England (אנגליה)", "USA (ארצות הברית)"),
    ("Germany (גרמניה)", "Haiti (האיטי)"),
    ("Netherlands (הולנד)", "Japan (יפן)"),
]


@dataclass
class TeamAuditRow:
    team: str
    internal_elo: float
    world_elo: float
    internal_external_elo_delta: float
    composite_power: float
    raw_form: float
    opponent_adjusted_form: float
    form_inflation_delta: float
    rating_confidence: float
    missing_external_rating: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["warnings"] = ",".join(self.warnings) if self.warnings else ""
        return d


def team_level_warnings(diag) -> list[str]:
    warnings: list[str] = []
    if diag.external_source != "manual":
        warnings.append(WARNING_MISSING_EXTERNAL)
    if (
        diag.raw_form >= config.FORM_INFLATED_RAW_MIN
        and diag.opponent_adjusted_form
        < diag.raw_form * config.FORM_INFLATED_ADJ_RATIO
    ):
        warnings.append(WARNING_FORM_INFLATED)
    if diag.rating_confidence < config.LOW_RATING_CONFIDENCE_THRESHOLD:
        warnings.append(WARNING_LOW_CONFIDENCE)
    return warnings


def build_team_audit_row(
    registry_key: str,
    *,
    data_manager: LiveDataManager,
    power_eval: TeamPowerEvaluator,
) -> TeamAuditRow:
    data = data_manager.get_team_data(registry_key)
    internal_elo = float(data["elo"])
    raw_form = float(data.get("form", 0.5))
    diag = build_team_diagnostics(
        registry_key,
        internal_elo=internal_elo,
        raw_form=raw_form,
    )
    power = power_eval.calculate_composite_power(registry_key)
    form_delta = round(diag.raw_form - diag.opponent_adjusted_form, 3)
    return TeamAuditRow(
        team=english_name(registry_key),
        internal_elo=diag.internal_elo,
        world_elo=diag.world_elo,
        internal_external_elo_delta=diag.internal_external_elo_delta,
        composite_power=round(power, 2),
        raw_form=diag.raw_form,
        opponent_adjusted_form=diag.opponent_adjusted_form,
        form_inflation_delta=form_delta,
        rating_confidence=diag.rating_confidence,
        missing_external_rating=diag.external_source != "manual",
        warnings=team_level_warnings(diag),
    )


def audit_all_teams(
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
) -> list[TeamAuditRow]:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    rows = [
        build_team_audit_row(team, data_manager=dm, power_eval=pe)
        for team in dm.list_teams()
    ]
    return rows


def sort_team_rows(rows: list[TeamAuditRow], sort_key: str) -> list[TeamAuditRow]:
    if sort_key == "power_delta":
        return sorted(rows, key=lambda r: abs(r.internal_external_elo_delta), reverse=True)
    if sort_key == "form_inflation":
        return sorted(rows, key=lambda r: r.form_inflation_delta, reverse=True)
    if sort_key == "confidence":
        return sorted(rows, key=lambda r: r.rating_confidence)
    return rows


TEAM_AUDIT_COLUMNS = [
    "team",
    "internal_elo",
    "world_elo",
    "internal_external_elo_delta",
    "composite_power",
    "raw_form",
    "opponent_adjusted_form",
    "form_inflation_delta",
    "rating_confidence",
    "missing_external_rating",
    "warnings",
]


def format_team_audit_table(rows: list[TeamAuditRow]) -> str:
    header = (
        f"{'team':16} | {'int_elo':>7} | {'world':>7} | {'elo_d':>6} | "
        f"{'power':>7} | {'form':>5} | {'adj_f':>5} | {'f_inf':>5} | "
        f"{'conf':>4} | {'miss':>4} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        miss = "Y" if row.missing_external_rating else "N"
        warns = ",".join(row.warnings) if row.warnings else "-"
        lines.append(
            f"{row.team:16} | {row.internal_elo:7.1f} | {row.world_elo:7.1f} | "
            f"{row.internal_external_elo_delta:6.1f} | {row.composite_power:7.1f} | "
            f"{row.raw_form:5.2f} | {row.opponent_adjusted_form:5.2f} | "
            f"{row.form_inflation_delta:5.2f} | {row.rating_confidence:4.2f} | "
            f"{miss:>4} | {warns}"
        )
    return "\n".join(lines)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _neutral_predict(
    home_key: str,
    away_key: str,
    predict_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if predict_fn is not None:
        return predict_fn(home_key, away_key)
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    response = client.post(
        "/api/predict",
        json={
            "home_team": home_key,
            "away_team": away_key,
            "neutral_ground": True,
            "use_match_context": False,
            "top_n": 3,
        },
    )
    response.raise_for_status()
    return response.json()


@dataclass
class MatchupAuditRow:
    home: str
    away: str
    internal_elo_gap: float
    world_elo_gap: float
    power_gap: float
    global_strength_gap: float
    power_vs_elo_gap_delta: float
    power_vs_world_gap_delta: float
    raw_form_gap: float
    adjusted_form_gap: float
    home_confidence: float
    away_confidence: float
    warnings: str
    current_home_xg: float
    current_away_xg: float
    current_1x2_home: float
    current_1x2_draw: float
    current_1x2_away: float
    top_scores: str
    max_warning_severity: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MATCHUP_AUDIT_COLUMNS = [
    "home",
    "away",
    "internal_elo_gap",
    "world_elo_gap",
    "power_gap",
    "global_strength_gap",
    "power_vs_elo_gap_delta",
    "power_vs_world_gap_delta",
    "raw_form_gap",
    "adjusted_form_gap",
    "home_confidence",
    "away_confidence",
    "warnings",
    "max_warning_severity",
    "current_home_xg",
    "current_away_xg",
    "current_1x2_home",
    "current_1x2_draw",
    "current_1x2_away",
    "top_scores",
]


def _max_severity(warning_details: list[dict[str, Any]]) -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    best = ""
    best_rank = 0
    for item in warning_details:
        rank = order.get(item.get("severity", ""), 0)
        if rank > best_rank:
            best_rank = rank
            best = item["severity"]
    return best


def build_matchup_audit_row(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
    predict_fn: Callable[[str, str], dict[str, Any]] | None = None,
    include_prediction: bool = True,
) -> MatchupAuditRow:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    home_key, home_data = dm.resolve_team(home_input)
    away_key, away_data = dm.resolve_team(away_input)
    home_power = pe.calculate_composite_power(home_key)
    away_power = pe.calculate_composite_power(away_key)
    diag = build_match_diagnostics(
        home_key,
        away_key,
        home_power=home_power,
        away_power=away_power,
        home_internal_elo=float(home_data["elo"]),
        away_internal_elo=float(away_data["elo"]),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
    )
    g = diag.gaps
    pred: dict[str, Any] = {}
    warning_details_list: list[dict[str, Any]] = []
    if include_prediction:
        pred = _neutral_predict(home_key, away_key, predict_fn=predict_fn)
        warning_details_list = pred.get("global_rating_diagnostics", {}).get(
            "warning_details", []
        )
    else:
        warning_details_list = [w.to_dict() for w in diag.warning_details]
    max_sev = _max_severity(warning_details_list)

    top_scores = ""
    home_xg = away_xg = p_h = p_d = p_a = 0.0
    if include_prediction and pred:
        top_scores = "|".join(s["score"] for s in pred.get("top_scores", []))
        home_xg = float(pred.get("home_xg", 0))
        away_xg = float(pred.get("away_xg", 0))
        probs = pred.get("probabilities_1x2", {})
        p_h = float(probs.get("home_win", 0))
        p_d = float(probs.get("draw", 0))
        p_a = float(probs.get("away_win", 0))

    return MatchupAuditRow(
        home=english_name(home_key),
        away=english_name(away_key),
        internal_elo_gap=g.internal_elo_gap,
        world_elo_gap=g.world_elo_gap,
        power_gap=g.power_gap,
        global_strength_gap=g.global_strength_gap,
        power_vs_elo_gap_delta=g.power_vs_elo_gap_delta,
        power_vs_world_gap_delta=g.power_vs_world_gap_delta,
        raw_form_gap=round(diag.home.raw_form - diag.away.raw_form, 3),
        adjusted_form_gap=round(
            diag.home.opponent_adjusted_form - diag.away.opponent_adjusted_form,
            3,
        ),
        home_confidence=diag.home.rating_confidence,
        away_confidence=diag.away.rating_confidence,
        warnings=",".join(diag.warnings) if diag.warnings else "",
        current_home_xg=home_xg,
        current_away_xg=away_xg,
        current_1x2_home=p_h,
        current_1x2_draw=p_d,
        current_1x2_away=p_a,
        top_scores=top_scores,
        max_warning_severity=max_sev,
    )


def audit_sample_matchups(
    *,
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
    predict_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> list[MatchupAuditRow]:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    return [
        build_matchup_audit_row(
            home,
            away,
            data_manager=dm,
            power_eval=pe,
            predict_fn=predict_fn,
        )
        for home, away in SAMPLE_MATCHUP_PAIRS
    ]


def audit_all_matchups(
    *,
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
    predict_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> list[MatchupAuditRow]:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    teams = dm.list_teams()
    rows: list[MatchupAuditRow] = []
    for home in teams:
        for away in teams:
            if home == away:
                continue
            rows.append(
                build_matchup_audit_row(
                    home,
                    away,
                    data_manager=dm,
                    power_eval=pe,
                    predict_fn=predict_fn,
                )
            )
    return rows


def format_matchup_audit_table(rows: list[MatchupAuditRow]) -> str:
    header = (
        f"{'home':12} | {'away':12} | {'elo':>6} | {'world':>6} | {'pwr':>6} | "
        f"{'glob':>6} | {'sev':>6} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.home:12} | {row.away:12} | {row.internal_elo_gap:6.1f} | "
            f"{row.world_elo_gap:6.1f} | {row.power_gap:6.1f} | "
            f"{row.global_strength_gap:6.3f} | {row.max_warning_severity:>6} | "
            f"{row.warnings or '-'}"
        )
    return "\n".join(lines)
