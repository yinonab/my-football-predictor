"""Phase 2A — Shadow Power calibration (candidate variants, no production change)."""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import config
from core.blowout import apply_blowout_adjustment
from core.global_ratings import (
    compute_opponent_adjusted_form,
    english_name,
    lookup_external_record,
)
from core.maher import (
    blend_maher_with_power,
    floor_underdog_xg,
    mismatch_gap,
    scale_rho_for_gap,
)
from core.math_engine import AdvancedDixonColesEngine
from core.opponent_maher import estimate_xg_opponent_aware
from core.team_power import TeamPowerEvaluator
from data.database import LiveDataManager

WARNING_CANDIDATE_REVERSES_ELO = "CANDIDATE_REVERSES_ELO_DIRECTION"
WARNING_CANDIDATE_OVEREXPANDS = "CANDIDATE_OVEREXPANDS_GAP"
WARNING_CANDIDATE_REDUCES_COMPRESSION = "CANDIDATE_REDUCES_COMPRESSION"
WARNING_CANDIDATE_STILL_COMPRESSED = "CANDIDATE_STILL_COMPRESSED"
WARNING_DEFENSE_FLIP_HELPFUL = "DEFENSE_FLIP_LIKELY_HELPFUL"
WARNING_ADJ_FORM_HELPFUL = "ADJUSTED_FORM_LIKELY_HELPFUL"

SAMPLE_PAIRS: list[tuple[str, str]] = [
    ("Portugal (פורטוגל)", "DR Congo (קונגו)"),
    ("Germany (גרמניה)", "Haiti (האיטי)"),
    ("Brazil (ברזיל)", "Morocco (מרוקו)"),
    ("England (אנגליה)", "USA (ארצות הברית)"),
    ("Spain (ספרד)", "Cape Verde (כף ורד)"),
    ("Argentina (ארגנטינה)", "France (צרפת)"),
    ("Norway (נורווג)", "Algeria (אלג׳יריה)"),
]


@dataclass
class CandidatePowerResult:
    team: str
    variant: str
    total_power: float
    internal_elo: float
    world_elo: float | None
    raw_form: float
    opponent_adjusted_form: float
    attack: float
    defense: float
    components: dict[str, float | None]
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _defense_sign_for_variant(variant: str) -> int:
    if variant in ("defense_flipped", "defense_flipped_adjusted_form"):
        return 1
    return -1


def _form_value_for_variant(variant: str, raw_form: float, adj_form: float) -> float:
    if variant in ("adjusted_form", "defense_flipped_adjusted_form"):
        return adj_form
    return raw_form


def calculate_candidate_power(
    team_key: str,
    variant: str,
    *,
    data_manager: LiveDataManager | None = None,
    use_live: bool = False,
    h2h_component: float | None = None,
    context_component: float | None = None,
    modifier_component: float | None = None,
) -> CandidatePowerResult:
    """Shadow-only candidate Power — does not alter production team_power path."""
    if variant not in config.POWER_SHADOW_VARIANTS:
        raise ValueError(f"Unknown variant: {variant}")

    dm = data_manager or LiveDataManager()
    raw = dm.get_team_data(team_key, use_live=use_live)
    elo = float(raw.get("elo", 1500.0))
    raw_form = float(raw.get("form", 0.5))
    attack = float(raw.get("attack", 0.5))
    defense = float(raw.get("defense", 0.5))

    adj_form, _, _, used_opp = compute_opponent_adjusted_form(team_key, raw_form)
    form_used = _form_value_for_variant(variant, raw_form, adj_form)
    defense_sign = _defense_sign_for_variant(variant)

    elo_c = config.POWER_WEIGHT_ELO * elo
    form_c = config.POWER_WEIGHT_FORM * form_used * 1000.0
    attack_c = config.POWER_WEIGHT_ATTACK * attack * 1000.0
    defense_c = defense_sign * config.POWER_WEIGHT_DEFENSE * defense * 1000.0

    extras = [
        x
        for x in (h2h_component, context_component, modifier_component)
        if x is not None
    ]
    total = elo_c + form_c + attack_c + defense_c + sum(extras)

    external = lookup_external_record(team_key)
    world_elo = external.world_elo if external.world_elo is not None else elo

    notes: list[str] = []
    warnings: list[str] = []
    if variant == "current":
        notes.append("production formula")
    if variant in ("adjusted_form", "defense_flipped_adjusted_form") and not used_opp:
        notes.append("opponent-adjusted form unavailable; using raw form")
    if variant in ("defense_flipped", "defense_flipped_adjusted_form"):
        notes.append("defense added (strength semantics)")
    if defense >= 0.55 and defense_sign < 0:
        warnings.append("defense_subtracted_in_current_formula")

    return CandidatePowerResult(
        team=team_key,
        variant=variant,
        total_power=round(total, 2),
        internal_elo=round(elo, 1),
        world_elo=round(world_elo, 1),
        raw_form=round(raw_form, 3),
        opponent_adjusted_form=adj_form,
        attack=round(attack, 3),
        defense=round(defense, 3),
        components={
            "elo_component": round(elo_c, 2),
            "form_component": round(form_c, 2),
            "attack_component": round(attack_c, 2),
            "defense_component": round(defense_c, 2),
            "h2h_component": round(h2h_component, 2) if h2h_component is not None else None,
            "context_component": (
                round(context_component, 2) if context_component is not None else None
            ),
            "modifier_component": (
                round(modifier_component, 2) if modifier_component is not None else None
            ),
        },
        notes=notes,
        warnings=warnings,
    )


def gap_alignment_score(
    power_gap: float,
    internal_elo_gap: float,
    world_elo_gap: float,
) -> float:
    """Higher = candidate gap better aligns with Elo/world anchors (0–1 scale)."""
    if abs(internal_elo_gap) < 1 and abs(world_elo_gap) < 1:
        return 1.0

    def _align(p_gap: float, anchor: float) -> float:
        if abs(anchor) < 1:
            return 0.5
        same_sign = (p_gap == 0) or (p_gap > 0) == (anchor > 0)
        if not same_sign:
            return 0.0
        expected = anchor * config.POWER_WEIGHT_ELO
        if abs(expected) < 1:
            return 0.5
        ratio = abs(p_gap) / abs(expected)
        return max(0.0, min(1.0, 1.0 - abs(1.0 - ratio)))

    internal = _align(power_gap, internal_elo_gap)
    world = _align(power_gap, world_elo_gap)
    return round(
        config.POWER_SHADOW_ALIGNMENT_ELO_WEIGHT * internal
        + config.POWER_SHADOW_ALIGNMENT_WORLD_WEIGHT * world,
        4,
    )


def _compression_ratio(power_gap: float, elo_gap: float) -> float:
    return round(abs(power_gap) / max(abs(elo_gap), 1.0), 4)


def _world_compression_ratio(power_gap: float, world_gap: float) -> float:
    return round(abs(power_gap) / max(abs(world_gap), 1.0), 4)


@dataclass
class VariantMatchupMetrics:
    variant: str
    home_power: float
    away_power: float
    power_gap: float
    compression_ratio: float
    world_compression_ratio: float
    gap_alignment_score: float
    home_xg: float | None = None
    away_xg: float | None = None
    home_win: float | None = None
    draw: float | None = None
    away_win: float | None = None
    top_scores: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_shadow_match_pipeline(
    home_key: str,
    away_key: str,
    variant: str,
    *,
    data_manager: LiveDataManager,
    opponent_index: dict,
    advantage: float = 0.0,
    rho: float = config.DEFAULT_RHO,
    global_avg: float = config.GLOBAL_XG_AVG,
    alpha: float = config.OVERDISPERSION_ALPHA,
    top_n: int = 3,
) -> VariantMatchupMetrics:
    """Run xG + Dixon-Coles with candidate Power (shadow only)."""
    home_data = data_manager.get_team_data(home_key)
    away_data = data_manager.get_team_data(away_key)
    home_elo = float(home_data["elo"])
    away_elo = float(away_data["elo"])

    home_c = calculate_candidate_power(home_key, variant, data_manager=data_manager)
    away_c = calculate_candidate_power(away_key, variant, data_manager=data_manager)
    home_power = home_c.total_power
    away_power = away_c.total_power
    power_gap = round(home_power - away_power, 2)
    internal_elo_gap = home_elo - away_elo
    world_elo_gap = (home_c.world_elo or home_elo) - (away_c.world_elo or away_elo)

    home_xg, away_xg, _ = estimate_xg_opponent_aware(
        home_key,
        away_key,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        opponent_index,
        global_avg=global_avg,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        global_avg=global_avg,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        base_alpha=alpha,
        home_elo=home_elo,
        away_elo=away_elo,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    gap_for_rho = mismatch_gap(
        home_power, away_power, advantage, home_elo=home_elo, away_elo=away_elo
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(rho, gap_for_rho),
        global_avg=global_avg,
        alpha=blowout.alpha,
    )
    result = engine.generate_match_prediction(
        home_power,
        away_power,
        advantage,
        top_n=top_n,
        max_goals=blowout.max_goals,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    probs = result["probabilities_1x2"]
    return VariantMatchupMetrics(
        variant=variant,
        home_power=home_power,
        away_power=away_power,
        power_gap=power_gap,
        compression_ratio=_compression_ratio(power_gap, internal_elo_gap),
        world_compression_ratio=_world_compression_ratio(power_gap, world_elo_gap),
        gap_alignment_score=gap_alignment_score(power_gap, internal_elo_gap, world_elo_gap),
        home_xg=result["home_xg"],
        away_xg=result["away_xg"],
        home_win=probs["home_win"],
        draw=probs["draw"],
        away_win=probs["away_win"],
        top_scores=[s["score"] for s in result["top_scores"]],
    )


def build_matchup_shadow_comparison(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    opponent_index: dict | None = None,
    include_xg: bool = False,
) -> dict[str, Any]:
    dm = data_manager or LiveDataManager()
    home_key, home_data = dm.resolve_team(home_input)
    away_key, away_data = dm.resolve_team(away_input)
    internal_elo_gap = round(float(home_data["elo"]) - float(away_data["elo"]), 1)
    home_ext = lookup_external_record(home_key)
    away_ext = lookup_external_record(away_key)
    world_elo_gap = round(
        (home_ext.world_elo or float(home_data["elo"]))
        - (away_ext.world_elo or float(away_data["elo"])),
        1,
    )

    from core.global_ratings import build_team_diagnostics

    home_gss = build_team_diagnostics(
        home_key,
        internal_elo=float(home_data["elo"]),
        raw_form=float(home_data.get("form", 0.5)),
    ).global_strength_score
    away_gss = build_team_diagnostics(
        away_key,
        internal_elo=float(away_data["elo"]),
        raw_form=float(away_data.get("form", 0.5)),
    ).global_strength_score
    global_strength_gap = round(home_gss - away_gss, 4)

    variants: dict[str, Any] = {}
    metrics_by_variant: dict[str, VariantMatchupMetrics] = {}

    opp_idx = opponent_index
    if include_xg and opp_idx is None:
        from core.opponent_maher import build_opponent_index
        from core.team_ratings import build_all_matches
        from data.database import FIFA_ELO_2026

        opp_idx = build_opponent_index(build_all_matches(), set(FIFA_ELO_2026.keys()))

    for variant in config.POWER_SHADOW_VARIANTS:
        if include_xg and opp_idx is not None:
            m = run_shadow_match_pipeline(
                home_key,
                away_key,
                variant,
                data_manager=dm,
                opponent_index=opp_idx,
            )
            metrics_by_variant[variant] = m
            variants[variant] = {
                "home": calculate_candidate_power(
                    home_key, variant, data_manager=dm
                ).to_dict(),
                "away": calculate_candidate_power(
                    away_key, variant, data_manager=dm
                ).to_dict(),
                "power_gap": m.power_gap,
                "compression_ratio": m.compression_ratio,
                "world_compression_ratio": m.world_compression_ratio,
                "gap_alignment_score": m.gap_alignment_score,
                "home_xg": m.home_xg,
                "away_xg": m.away_xg,
                "probabilities_1x2": {
                    "home_win": m.home_win,
                    "draw": m.draw,
                    "away_win": m.away_win,
                },
                "top_scores": m.top_scores,
            }
        else:
            home_c = calculate_candidate_power(home_key, variant, data_manager=dm)
            away_c = calculate_candidate_power(away_key, variant, data_manager=dm)
            p_gap = round(home_c.total_power - away_c.total_power, 2)
            variants[variant] = {
                "home": home_c.to_dict(),
                "away": away_c.to_dict(),
                "power_gap": p_gap,
                "compression_ratio": _compression_ratio(p_gap, internal_elo_gap),
                "world_compression_ratio": _world_compression_ratio(p_gap, world_elo_gap),
                "gap_alignment_score": gap_alignment_score(
                    p_gap, internal_elo_gap, world_elo_gap
                ),
            }
            metrics_by_variant[variant] = VariantMatchupMetrics(
                variant=variant,
                home_power=home_c.total_power,
                away_power=away_c.total_power,
                power_gap=p_gap,
                compression_ratio=_compression_ratio(p_gap, internal_elo_gap),
                world_compression_ratio=_world_compression_ratio(p_gap, world_elo_gap),
                gap_alignment_score=gap_alignment_score(
                    p_gap, internal_elo_gap, world_elo_gap
                ),
            )

    current_gap = variants["current"]["power_gap"]
    warnings = _shadow_warnings(
        internal_elo_gap=internal_elo_gap,
        world_elo_gap=world_elo_gap,
        current_gap=current_gap,
        metrics_by_variant=metrics_by_variant,
    )

    best_variant = max(
        config.POWER_SHADOW_VARIANTS,
        key=lambda v: metrics_by_variant[v].gap_alignment_score,
    )

    return {
        "enabled": config.POWER_SHADOW_CALIBRATION_ENABLED,
        "affects_prediction": config.POWER_CANDIDATE_AFFECTS_PREDICTION,
        "variants": variants,
        "matchup_comparison": {
            "internal_elo_gap": internal_elo_gap,
            "world_elo_gap": world_elo_gap,
            "global_strength_gap": global_strength_gap,
            "current_power_gap": current_gap,
            "best_alignment_variant": best_variant,
            "warnings": warnings,
        },
    }


def _shadow_warnings(
    *,
    internal_elo_gap: float,
    world_elo_gap: float,
    current_gap: float,
    metrics_by_variant: dict[str, VariantMatchupMetrics],
) -> list[str]:
    warnings: list[str] = []
    current_ratio = _compression_ratio(current_gap, internal_elo_gap)

    for variant, metrics in metrics_by_variant.items():
        if variant == "current":
            continue
        p_gap = metrics.power_gap
        ratio = metrics.compression_ratio

        if abs(internal_elo_gap) >= 50:
            if (p_gap > 0) != (internal_elo_gap > 0) and abs(p_gap) > 20:
                warnings.append(f"{variant}:{WARNING_CANDIDATE_REVERSES_ELO}")

        expected = internal_elo_gap * config.POWER_WEIGHT_ELO
        if abs(expected) > 1 and abs(p_gap) > abs(expected) * config.POWER_SHADOW_OVEREXPAND_RATIO:
            warnings.append(f"{variant}:{WARNING_CANDIDATE_OVEREXPANDS}")

        if ratio < config.POWER_SHADOW_COMPRESSION_THRESHOLD:
            warnings.append(f"{variant}:{WARNING_CANDIDATE_STILL_COMPRESSED}")

        if ratio < current_ratio - 0.08:
            warnings.append(f"{variant}:{WARNING_CANDIDATE_REDUCES_COMPRESSION}")

    adj_metrics = metrics_by_variant.get("adjusted_form")
    if adj_metrics and abs(internal_elo_gap) >= 50:
        same_sign = (adj_metrics.power_gap > 0) == (internal_elo_gap > 0)
        if same_sign and abs(adj_metrics.power_gap) > abs(current_gap) + 25:
            warnings.append(WARNING_ADJ_FORM_HELPFUL)

    def_flip = metrics_by_variant.get("defense_flipped")
    if def_flip and abs(internal_elo_gap) >= 50:
        if def_flip.gap_alignment_score > metrics_by_variant["current"].gap_alignment_score + 0.02:
            warnings.append(WARNING_DEFENSE_FLIP_HELPFUL)
    elif (
        def_flip
        and def_flip.compression_ratio < current_ratio - 0.05
    ):
        warnings.append(WARNING_DEFENSE_FLIP_HELPFUL)

    seen: set[str] = set()
    out: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


@dataclass
class ShadowAuditRow:
    home: str
    away: str
    elo_gap: float
    world_gap: float
    current_gap: float
    def_flip_gap: float
    adj_form_gap: float
    both_gap: float
    best_variant: str
    warnings: str
    improvement: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_shadow_audit_row(
    home_input: str,
    away_input: str,
    *,
    data_manager: LiveDataManager | None = None,
    include_xg: bool = False,
    opponent_index: dict | None = None,
) -> ShadowAuditRow:
    dm = data_manager or LiveDataManager()
    home_key, _ = dm.resolve_team(home_input)
    away_key, _ = dm.resolve_team(away_input)
    comp = build_matchup_shadow_comparison(
        home_input,
        away_input,
        data_manager=dm,
        opponent_index=opponent_index,
        include_xg=include_xg,
    )
    mc = comp["matchup_comparison"]
    v = comp["variants"]
    current_ratio = v["current"]["compression_ratio"]
    best = mc["best_alignment_variant"]
    best_ratio = v[best]["compression_ratio"]
    return ShadowAuditRow(
        home=english_name(home_key),
        away=english_name(away_key),
        elo_gap=mc["internal_elo_gap"],
        world_gap=mc["world_elo_gap"],
        current_gap=v["current"]["power_gap"],
        def_flip_gap=v["defense_flipped"]["power_gap"],
        adj_form_gap=v["adjusted_form"]["power_gap"],
        both_gap=v["defense_flipped_adjusted_form"]["power_gap"],
        best_variant=best,
        warnings=",".join(mc["warnings"]) if mc["warnings"] else "",
        improvement=round(current_ratio - best_ratio, 4),
    )


def audit_sample_shadow(
    *,
    data_manager: LiveDataManager | None = None,
    include_xg: bool = False,
    opponent_index: dict | None = None,
) -> list[ShadowAuditRow]:
    dm = data_manager or LiveDataManager()
    return [
        build_shadow_audit_row(
            home,
            away,
            data_manager=dm,
            include_xg=include_xg,
            opponent_index=opponent_index,
        )
        for home, away in SAMPLE_PAIRS
    ]


def audit_all_shadow(
    *,
    data_manager: LiveDataManager | None = None,
    include_xg: bool = False,
    opponent_index: dict | None = None,
) -> list[ShadowAuditRow]:
    dm = data_manager or LiveDataManager()
    teams = dm.list_teams()
    rows: list[ShadowAuditRow] = []
    for home in teams:
        for away in teams:
            if home == away:
                continue
            row = build_shadow_audit_row(
                home,
                away,
                data_manager=dm,
                include_xg=include_xg,
                opponent_index=opponent_index,
            )
            rows.append(row)
    return rows


def format_shadow_table(rows: list[ShadowAuditRow]) -> str:
    header = (
        f"{'home':12} | {'away':12} | {'elo':>6} | {'world':>6} | {'cur':>6} | "
        f"{'def+':>6} | {'adj_f':>6} | {'both':>6} | {'best':>22} | warnings"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.home:12} | {row.away:12} | {row.elo_gap:6.1f} | {row.world_gap:6.1f} | "
            f"{row.current_gap:6.1f} | {row.def_flip_gap:6.1f} | {row.adj_form_gap:6.1f} | "
            f"{row.both_gap:6.1f} | {row.best_variant:>22} | {row.warnings or '-'}"
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


@dataclass
class ShadowBacktestRow:
    variant: str
    outcome_accuracy: float
    exact_score_accuracy: float
    top3_score_hit_rate: float
    mean_log_loss: float
    mean_brier: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_shadow_backtest(
    variant: str,
    *,
    data_manager: Any | None = None,
) -> ShadowBacktestRow:
    """WC 2022 backtest using a shadow Power variant."""
    from core.backtest import BacktestRunner, _brier_score, _log_loss_score, _outcome, _predicted_outcome
    from data.wc2022 import WC2022_MATCHES, Wc2022DataManager

    dm = data_manager or Wc2022DataManager()
    runner = BacktestRunner(data_manager=dm)
    results = []
    for match in WC2022_MATCHES:
        home_key = match.home
        away_key = match.away
        try:
            home_c = calculate_candidate_power(home_key, variant, data_manager=dm)  # type: ignore[arg-type]
            away_c = calculate_candidate_power(away_key, variant, data_manager=dm)  # type: ignore[arg-type]
        except Exception:
            continue
        home_power = runner._evaluator.apply_environmental_modifiers(home_c.total_power)
        away_power = runner._evaluator.apply_environmental_modifiers(away_c.total_power)
        advantage = 0.0 if match.neutral else runner._home_advantage
        prediction = runner._engine.generate_match_prediction(
            home_power,
            away_power,
            advantage,
            include_all_scores=True,
        )
        probs = prediction["probabilities_1x2"]
        actual = _outcome(match.home_goals, match.away_goals)
        predicted = _predicted_outcome(probs)
        actual_score = f"{match.home_goals}-{match.away_goals}"
        top_scores = prediction["top_scores"]
        predicted_top = top_scores[0]["score"]
        top3 = {item["score"] for item in top_scores}
        all_scores = prediction.get("all_scores", {})
        actual_prob = all_scores.get(actual_score, 0.01)
        results.append(
            {
                "outcome_correct": actual == predicted,
                "exact_hit": actual_score == predicted_top,
                "top3_hit": actual_score in top3,
                "brier": _brier_score(probs, actual),
                "log_loss": _log_loss_score(actual_prob),
            }
        )

    n = len(results)
    if n == 0:
        return ShadowBacktestRow(
            variant=variant,
            outcome_accuracy=0.0,
            exact_score_accuracy=0.0,
            top3_score_hit_rate=0.0,
            mean_log_loss=0.0,
            mean_brier=0.0,
            notes="no evaluable matches",
        )
    note = "full xG/matrix via engine" if variant != "current" else "baseline"
    return ShadowBacktestRow(
        variant=variant,
        outcome_accuracy=round(sum(r["outcome_correct"] for r in results) / n * 100, 1),
        exact_score_accuracy=round(sum(r["exact_hit"] for r in results) / n * 100, 1),
        top3_score_hit_rate=round(sum(r["top3_hit"] for r in results) / n * 100, 1),
        mean_log_loss=round(sum(r["log_loss"] for r in results) / n, 4),
        mean_brier=round(sum(r["brier"] for r in results) / n, 4),
        notes=note,
    )


def run_all_shadow_backtests() -> list[ShadowBacktestRow]:
    return [run_shadow_backtest(v) for v in config.POWER_SHADOW_VARIANTS]


def format_backtest_table(rows: list[ShadowBacktestRow]) -> str:
    header = (
        f"{'variant':28} | {'1x2_acc':>7} | {'exact':>7} | {'top3':>7} | "
        f"{'log_loss':>8} | {'brier':>7} | notes"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.variant:28} | {row.outcome_accuracy:7.1f} | "
            f"{row.exact_score_accuracy:7.1f} | {row.top3_score_hit_rate:7.1f} | "
            f"{row.mean_log_loss:8.4f} | {row.mean_brier:7.4f} | {row.notes}"
        )
    return "\n".join(lines)
