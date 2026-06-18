"""Phase 1.6 — Power component audit (diagnostics only)."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import config
from core.global_ratings import (
    WARNING_POWER_COMPRESSED,
    WarningDetail,
    build_match_diagnostics,
    english_name,
)
from core.h2h_adjustment import H2HSummary, apply_h2h_adjustment
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager

WARNING_POWER_COMPONENTS_CANCEL_ELO = "POWER_COMPONENTS_CANCEL_ELO"
WARNING_FORM_OVERPOWERING_ELO = "FORM_COMPONENT_OVERPOWERING_ELO"
WARNING_DEFENSE_SIGN = "DEFENSE_SIGN_MAY_BE_WRONG"
WARNING_DEFENSE_SEMANTICS = "DEFENSE_SEMANTICS_UNCLEAR"
WARNING_ATTACK_DEFENSE_OUTLIER = "ATTACK_DEFENSE_SCALE_OUTLIER"
WARNING_POWER_SCALE = "POWER_SCALE_INCONSISTENT"

SAMPLE_MATCHUP_PAIRS: list[tuple[str, str]] = [
    ("Portugal (פורטוגל)", "DR Congo (קונגו)"),
    ("Germany (גרמניה)", "Haiti (האיטי)"),
    ("Brazil (ברזיל)", "Morocco (מרוקו)"),
    ("England (אנגליה)", "USA (ארצות הברית)"),
    ("Spain (ספרד)", "Cape Verde (כף ורד)"),
    ("Argentina (ארגנטינה)", "France (צרפת)"),
]

COMPONENT_GAP_KEYS = (
    "elo_component_gap",
    "form_component_gap",
    "attack_component_gap",
    "defense_component_gap",
    "context_component_gap",
    "h2h_component_gap",
    "modifier_component_gap",
)


@dataclass
class TeamPowerAuditRow:
    team: str
    power: float
    elo: float
    elo_c: float
    form: float
    form_c: float
    attack: float
    atk_c: float
    defense: float
    def_c: float
    adj_form: float | None
    avg_opp_elo: float | None
    gf: float | None
    ga: float | None
    warnings: list[str]
    compression_suspect_score: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["warnings"] = ",".join(self.warnings) if self.warnings else ""
        return d


@dataclass
class MatchupPowerAuditRow:
    home: str
    away: str
    elo_gap: float
    world_gap: float
    power_gap: float
    elo_component_gap: float
    form_component_gap: float
    attack_component_gap: float
    defense_component_gap: float
    context_gap: float
    h2h_gap: float
    compression_ratio: float
    top_compression_driver: str
    warnings: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _component_gap(home_diag: dict, away_diag: dict, key: str) -> float:
    return round(
        float(home_diag["components"][key] or 0.0)
        - float(away_diag["components"][key] or 0.0),
        2,
    )


def assess_defense_semantics(raw_inputs: dict[str, Any]) -> list[str]:
    """Heuristic defense semantics check — does not change Power formula."""
    warnings: list[str] = []
    defense = raw_inputs.get("defense")
    ga = raw_inputs.get("ga")
    gf = raw_inputs.get("gf")

    if defense is None:
        return warnings

    defense_f = float(defense)
    # Derived ratings treat higher defense as better (fewer GA).
    if ga is not None:
        ga_f = float(ga)
        if ga_f <= config.DEFENSE_STRENGTH_GA_THRESHOLD and defense_f < 0.45:
            warnings.append(WARNING_DEFENSE_SEMANTICS)
        if ga_f <= config.DEFENSE_STRENGTH_GA_THRESHOLD and defense_f >= 0.5:
            warnings.append(WARNING_DEFENSE_SIGN)
    elif defense_f >= 0.55:
        warnings.append(WARNING_DEFENSE_SIGN)

    if gf is None and ga is None and 0.45 <= defense_f <= 0.55:
        warnings.append(WARNING_DEFENSE_SEMANTICS)

    return warnings


def assess_team_component_warnings(diag: dict[str, Any]) -> list[str]:
    warnings = assess_defense_semantics(diag["raw_inputs"])
    comps = diag["components"]
    elo_c = abs(float(comps["elo_component"]))
    form_c = abs(float(comps["form_component"]))
    attack_raw = diag["raw_inputs"].get("attack")
    defense_raw = diag["raw_inputs"].get("defense")

    if elo_c > 1 and form_c / elo_c >= config.FORM_OVERPOWERS_ELO_RATIO:
        warnings.append(WARNING_FORM_OVERPOWERING_ELO)

    for raw_val, label in ((attack_raw, "attack"), (defense_raw, "defense")):
        if raw_val is None:
            continue
        val = float(raw_val)
        if val < config.ATTACK_DEFENSE_RAW_MIN or val > config.ATTACK_DEFENSE_RAW_MAX:
            warnings.append(WARNING_ATTACK_DEFENSE_OUTLIER)

    magnitudes = [
        abs(float(comps["elo_component"])),
        abs(float(comps["form_component"])),
        abs(float(comps["attack_component"])),
        abs(float(comps["defense_component"])),
    ]
    positive = [m for m in magnitudes if m > 0]
    if len(positive) >= 2:
        ratio = max(positive) / max(min(positive), 1.0)
        if ratio > config.POWER_SCALE_INCONSISTENT_RATIO:
            warnings.append(WARNING_POWER_SCALE)

    seen: set[str] = set()
    out: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def compression_suspect_score(diag: dict[str, Any]) -> float:
    comps = diag["components"]
    elo_c = abs(float(comps["elo_component"]))
    non_elo = (
        abs(float(comps["form_component"]))
        + abs(float(comps["attack_component"]))
        + abs(float(comps["defense_component"]))
    )
    return round(non_elo / max(elo_c, 1.0), 4)


def identify_top_compression_driver(
    *,
    elo_component_gap: float,
    form_component_gap: float,
    attack_component_gap: float,
    defense_component_gap: float,
    context_component_gap: float = 0.0,
    h2h_component_gap: float = 0.0,
    modifier_component_gap: float = 0.0,
) -> str:
    if abs(elo_component_gap) < 1.0:
        return "none"

    expected = 1.0 if elo_component_gap > 0 else -1.0
    opposing: dict[str, float] = {}
    for name, gap in (
        ("form_component", form_component_gap),
        ("attack_component", attack_component_gap),
        ("defense_component", defense_component_gap),
        ("context_component", context_component_gap),
        ("h2h_component", h2h_component_gap),
        ("modifier_component", modifier_component_gap),
    ):
        if gap * expected < 0:
            opposing[name] = abs(gap)

    if not opposing:
        return "none"
    return max(opposing, key=opposing.get)


def build_power_path_diagnostics(
    home_key: str,
    away_key: str,
    power_eval: TeamPowerEvaluator,
    *,
    h2h_summary: H2HSummary | None = None,
    home_context_mult: float = 1.0,
    away_context_mult: float = 1.0,
    home_altitude: int = 0,
    away_altitude: int = 0,
    home_star_absent: bool = False,
    away_star_absent: bool = False,
    use_live: bool = False,
) -> dict[str, Any]:
    """Reconstruct matchup power path for diagnostics without changing predict()."""
    base_home = power_eval.calculate_composite_power(home_key, use_live=use_live)
    base_away = power_eval.calculate_composite_power(away_key, use_live=use_live)

    home_mod = power_eval.apply_environmental_modifiers(
        base_home, altitude=home_altitude, star_absent=home_star_absent
    )
    away_mod = power_eval.apply_environmental_modifiers(
        base_away, altitude=away_altitude, star_absent=away_star_absent
    )
    home_modifier_delta = home_mod - base_home
    away_modifier_delta = away_mod - base_away

    home_after_h2h, away_after_h2h, _ = apply_h2h_adjustment(
        home_mod, away_mod, h2h_summary
    )
    home_h2h_delta = home_after_h2h - home_mod
    away_h2h_delta = away_after_h2h - away_mod

    final_home = home_after_h2h * home_context_mult
    final_away = away_after_h2h * away_context_mult
    home_context_delta = final_home - home_after_h2h
    away_context_delta = final_away - away_after_h2h

    home_diag = power_eval.get_power_component_diagnostics(
        home_key,
        use_live=use_live,
        h2h_component=home_h2h_delta,
        context_component=home_context_delta,
        modifier_component=home_modifier_delta,
    )
    away_diag = power_eval.get_power_component_diagnostics(
        away_key,
        use_live=use_live,
        h2h_component=away_h2h_delta,
        context_component=away_context_delta,
        modifier_component=away_modifier_delta,
    )

    gap_breakdown = {
        "total_power_gap": round(final_home - final_away, 2),
        "elo_component_gap": _component_gap(home_diag, away_diag, "elo_component"),
        "form_component_gap": _component_gap(home_diag, away_diag, "form_component"),
        "attack_component_gap": _component_gap(home_diag, away_diag, "attack_component"),
        "defense_component_gap": _component_gap(home_diag, away_diag, "defense_component"),
        "context_component_gap": _component_gap(home_diag, away_diag, "context_component"),
        "h2h_component_gap": _component_gap(home_diag, away_diag, "h2h_component"),
        "modifier_component_gap": _component_gap(
            home_diag, away_diag, "modifier_component"
        ),
        "top_compression_driver": identify_top_compression_driver(
            elo_component_gap=_component_gap(home_diag, away_diag, "elo_component"),
            form_component_gap=_component_gap(home_diag, away_diag, "form_component"),
            attack_component_gap=_component_gap(home_diag, away_diag, "attack_component"),
            defense_component_gap=_component_gap(home_diag, away_diag, "defense_component"),
            context_component_gap=_component_gap(home_diag, away_diag, "context_component"),
            h2h_component_gap=_component_gap(home_diag, away_diag, "h2h_component"),
            modifier_component_gap=_component_gap(
                home_diag, away_diag, "modifier_component"
            ),
        ),
    }

    return {
        "home": home_diag,
        "away": away_diag,
        "gap_breakdown": gap_breakdown,
    }


def build_power_component_warnings(
    *,
    gap_breakdown: dict[str, Any],
    internal_elo_gap: float,
    world_elo_gap: float,
    home_team_diag: dict[str, Any],
    away_team_diag: dict[str, Any],
) -> list[WarningDetail]:
    details: list[WarningDetail] = []
    elo_c_gap = float(gap_breakdown["elo_component_gap"])
    power_gap = float(gap_breakdown["total_power_gap"])
    abs_elo_gap = abs(internal_elo_gap)
    abs_elo_c_gap = abs(elo_c_gap)

    non_elo_gap = (
        float(gap_breakdown["form_component_gap"])
        + float(gap_breakdown["attack_component_gap"])
        + float(gap_breakdown["defense_component_gap"])
        + float(gap_breakdown.get("context_component_gap", 0))
        + float(gap_breakdown.get("h2h_component_gap", 0))
        + float(gap_breakdown.get("modifier_component_gap", 0))
    )

    compression_ratio = abs(power_gap) / max(abs_elo_gap, 1.0)
    cancel_amount = abs(elo_c_gap) - abs(power_gap)
    if (
        abs_elo_gap >= config.POWER_COMPONENT_CANCEL_ELO_GAP
        and compression_ratio <= config.POWER_COMPONENT_CANCEL_RATIO
        and (
            cancel_amount >= 15.0
            or gap_breakdown["top_compression_driver"] != "none"
        )
    ):
        severity = "high" if compression_ratio <= 0.40 else "medium"
        details.append(
            WarningDetail(
                code=WARNING_POWER_COMPONENTS_CANCEL_ELO,
                severity=severity,
                message=(
                    "Non-Elo Power components cancel most of the Elo component gap "
                    f"(driver: {gap_breakdown['top_compression_driver']})."
                ),
                metrics={
                    "internal_elo_gap": internal_elo_gap,
                    "world_elo_gap": world_elo_gap,
                    "power_gap": power_gap,
                    "elo_component_gap": elo_c_gap,
                    "non_elo_component_gap": round(non_elo_gap, 2),
                    "compression_ratio": round(compression_ratio, 4),
                    "top_compression_driver": gap_breakdown["top_compression_driver"],
                },
            )
        )

    if abs_elo_c_gap > 1:
        expected = 1.0 if elo_c_gap > 0 else -1.0
        form_gap = float(gap_breakdown["form_component_gap"])
        if form_gap * expected < 0 and abs(form_gap) >= abs(elo_c_gap) * 0.35:
            severity = "high" if abs(form_gap) >= abs(elo_c_gap) * 0.85 else "medium"
            details.append(
                WarningDetail(
                    code=WARNING_FORM_OVERPOWERING_ELO,
                    severity=severity,
                    message="Form component gap opposes and narrows the Elo component gap.",
                    metrics={
                        "elo_component_gap": elo_c_gap,
                        "form_component_gap": form_gap,
                    },
                )
            )

    for side_name, side in (("home", home_team_diag), ("away", away_team_diag)):
        for code in assess_defense_semantics(side["raw_inputs"]):
            if code == WARNING_DEFENSE_SIGN:
                details.append(
                    WarningDetail(
                        code=WARNING_DEFENSE_SIGN,
                        severity="high",
                        message=(
                            f"{english_name(side['team'])} defense metric appears to "
                            "measure strength but is subtracted in Power."
                        ),
                        metrics={
                            "team": english_name(side["team"]),
                            "defense": side["raw_inputs"].get("defense"),
                            "ga": side["raw_inputs"].get("ga"),
                            "gf": side["raw_inputs"].get("gf"),
                            "defense_component": side["components"]["defense_component"],
                        },
                    )
                )
            elif code == WARNING_DEFENSE_SEMANTICS:
                details.append(
                    WarningDetail(
                        code=WARNING_DEFENSE_SEMANTICS,
                        severity="medium",
                        message=(
                            f"{english_name(side['team'])} defense semantics unclear "
                            "(inspect GF/GA vs defense rating)."
                        ),
                        metrics={
                            "team": english_name(side["team"]),
                            "defense": side["raw_inputs"].get("defense"),
                            "ga": side["raw_inputs"].get("ga"),
                            "gf": side["raw_inputs"].get("gf"),
                        },
                    )
                )

    for side in (home_team_diag, away_team_diag):
        for code in assess_team_component_warnings(side):
            if code in (WARNING_ATTACK_DEFENSE_OUTLIER, WARNING_POWER_SCALE):
                details.append(
                    WarningDetail(
                        code=code,
                        severity="medium",
                        message=f"{english_name(side['team'])} component scale outlier.",
                        metrics={
                            "team": english_name(side["team"]),
                            "attack": side["raw_inputs"].get("attack"),
                            "defense": side["raw_inputs"].get("defense"),
                        },
                    )
                )

    seen: set[str] = set()
    deduped: list[WarningDetail] = []
    for item in details:
        key = (item.code, item.metrics.get("team", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def audit_all_team_components(
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
) -> list[TeamPowerAuditRow]:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    rows: list[TeamPowerAuditRow] = []
    for team in dm.list_teams():
        diag = pe.get_power_component_diagnostics(team)
        raw = diag["raw_inputs"]
        comps = diag["components"]
        warnings = assess_team_component_warnings(diag)
        rows.append(
            TeamPowerAuditRow(
                team=english_name(team),
                power=float(diag["total_power"]),
                elo=float(diag["internal_elo"]),
                elo_c=float(comps["elo_component"]),
                form=float(raw["form"]),
                form_c=float(comps["form_component"]),
                attack=float(raw["attack"]),
                atk_c=float(comps["attack_component"]),
                defense=float(raw["defense"]),
                def_c=float(comps["defense_component"]),
                adj_form=raw.get("opponent_adjusted_form"),
                avg_opp_elo=raw.get("avg_opponent_elo"),
                gf=raw.get("gf"),
                ga=raw.get("ga"),
                warnings=warnings,
                compression_suspect_score=compression_suspect_score(diag),
            )
        )
    return rows


def sort_team_power_rows(rows: list[TeamPowerAuditRow], sort_key: str) -> list[TeamPowerAuditRow]:
    if sort_key == "power":
        return sorted(rows, key=lambda r: r.power, reverse=True)
    if sort_key == "form_component":
        return sorted(rows, key=lambda r: r.form_c, reverse=True)
    if sort_key == "defense_component":
        return sorted(rows, key=lambda r: abs(r.def_c), reverse=True)
    if sort_key == "compression_suspects":
        return sorted(rows, key=lambda r: r.compression_suspect_score, reverse=True)
    return rows


TEAM_POWER_COLUMNS = [
    "team",
    "power",
    "elo",
    "elo_c",
    "form",
    "form_c",
    "attack",
    "atk_c",
    "defense",
    "def_c",
    "adj_form",
    "avg_opp_elo",
    "gf",
    "ga",
    "warnings",
    "compression_suspect_score",
]


def format_team_power_table(rows: list[TeamPowerAuditRow]) -> str:
    header = (
        f"{'team':14} | {'power':>7} | {'elo':>7} | {'elo_c':>7} | "
        f"{'form':>5} | {'form_c':>6} | {'attack':>5} | {'atk_c':>6} | "
        f"{'def':>5} | {'def_c':>6} | {'adj_f':>5} | {'avg_o':>6} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        avg_o = f"{row.avg_opp_elo:.0f}" if row.avg_opp_elo is not None else "-"
        adj = f"{row.adj_form:.2f}" if row.adj_form is not None else "-"
        warns = ",".join(row.warnings) if row.warnings else "-"
        lines.append(
            f"{row.team:14} | {row.power:7.1f} | {row.elo:7.1f} | {row.elo_c:7.1f} | "
            f"{row.form:5.2f} | {row.form_c:6.1f} | {row.attack:5.2f} | {row.atk_c:6.1f} | "
            f"{row.defense:5.2f} | {row.def_c:6.1f} | {adj:>5} | {avg_o:>6} | {warns}"
        )
    return "\n".join(lines)


def audit_matchup_power(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
    h2h_summary: H2HSummary | None = None,
) -> MatchupPowerAuditRow:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    home_key, home_data = dm.resolve_team(home_input)
    away_key, away_data = dm.resolve_team(away_input)

    power_path = build_power_path_diagnostics(
        home_key, away_key, pe, h2h_summary=h2h_summary
    )
    gb = power_path["gap_breakdown"]
    home_power = pe.calculate_composite_power(home_key)
    away_power = pe.calculate_composite_power(away_key)
    grd = build_match_diagnostics(
        home_key,
        away_key,
        home_power=home_power,
        away_power=away_power,
        home_internal_elo=float(home_data["elo"]),
        away_internal_elo=float(away_data["elo"]),
        home_raw_form=float(home_data.get("form", 0.5)),
        away_raw_form=float(away_data.get("form", 0.5)),
    )
    power_warnings = build_power_component_warnings(
        gap_breakdown=gb,
        internal_elo_gap=grd.gaps.internal_elo_gap,
        world_elo_gap=grd.gaps.world_elo_gap,
        home_team_diag=power_path["home"],
        away_team_diag=power_path["away"],
    )
    warning_codes = [w.code for w in power_warnings]
    if grd.warnings:
        warning_codes.extend(grd.warnings)
    seen: set[str] = set()
    merged: list[str] = []
    for code in warning_codes:
        if code not in seen:
            seen.add(code)
            merged.append(code)

    return MatchupPowerAuditRow(
        home=english_name(home_key),
        away=english_name(away_key),
        elo_gap=grd.gaps.internal_elo_gap,
        world_gap=grd.gaps.world_elo_gap,
        power_gap=gb["total_power_gap"],
        elo_component_gap=gb["elo_component_gap"],
        form_component_gap=gb["form_component_gap"],
        attack_component_gap=gb["attack_component_gap"],
        defense_component_gap=gb["defense_component_gap"],
        context_gap=gb["context_component_gap"],
        h2h_gap=gb["h2h_component_gap"],
        compression_ratio=grd.gaps.power_compression_ratio,
        top_compression_driver=gb["top_compression_driver"],
        warnings=",".join(merged),
    )


def audit_sample_matchup_power(
    *,
    data_manager: LiveDataManager | None = None,
    power_eval: TeamPowerEvaluator | None = None,
    h2h_lookup=None,
) -> list[MatchupPowerAuditRow]:
    dm = data_manager or LiveDataManager()
    pe = power_eval or TeamPowerEvaluator(dm)
    rows: list[MatchupPowerAuditRow] = []
    for home, away in SAMPLE_MATCHUP_PAIRS:
        home_key, _ = dm.resolve_team(home)
        away_key, _ = dm.resolve_team(away)
        h2h = h2h_lookup(home_key, away_key) if h2h_lookup else None
        rows.append(
            audit_matchup_power(
                home,
                away,
                data_manager=dm,
                power_eval=pe,
                h2h_summary=h2h,
            )
        )
    return rows


def format_matchup_power_table(rows: list[MatchupPowerAuditRow]) -> str:
    header = (
        f"{'home':12} | {'away':12} | {'elo':>6} | {'world':>6} | {'pwr':>6} | "
        f"{'elo_c':>6} | {'form_c':>6} | {'atk_c':>6} | {'def_c':>6} | "
        f"{'ratio':>5} | {'driver':>16} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.home:12} | {row.away:12} | {row.elo_gap:6.1f} | {row.world_gap:6.1f} | "
            f"{row.power_gap:6.1f} | {row.elo_component_gap:6.1f} | "
            f"{row.form_component_gap:6.1f} | {row.attack_component_gap:6.1f} | "
            f"{row.defense_component_gap:6.1f} | {row.compression_ratio:5.2f} | "
            f"{row.top_compression_driver:>16} | {row.warnings or '-'}"
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
