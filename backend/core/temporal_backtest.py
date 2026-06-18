"""Phase 2D/2E — Temporal / walk-forward backtest infrastructure."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import config
from core.blowout import apply_blowout_adjustment
from core.elo_updater import update_elo_pair
from core.maher import (
    blend_maher_with_power,
    floor_underdog_xg,
    mismatch_gap,
    scale_rho_for_gap,
)
from core.math_engine import AdvancedDixonColesEngine
from core.opponent_maher import build_opponent_index, estimate_xg_opponent_aware
from core.power_effective_elo import (
    EFFECTIVE_EXTERNAL_VARIANT_BASE,
    EFFECTIVE_VARIANT_BASE,
    blend_weights_for_strategy,
)
from core.power_shadow_calibration import (
    _defense_sign_for_variant,
    _form_value_for_variant,
)
from core.temporal_match_data import (
    PriorMode,
    apply_match_date_overrides,
    resolve_initial_elos,
)
from data.database import compute_derived_metrics
from data.nt_match import NationalTeamMatch
from data.tournament_data import DATASET_REGISTRY, list_dataset_keys, resolve_dataset_key
from data.wc2026_qualifiers import WC2026_QUALIFIER_MATCHES

WorldEloMode = Literal["none", "current_static", "snapshot_file", "proxy_from_internal"]
LeakageLabel = Literal["low", "medium", "high"]
DataQualityLabel = Literal["exact_datetime", "exact_date", "estimated_order", "missing_date"]

INITIAL_ELO: float = 1500.0
FORM_WINDOW: int = 10


@dataclass(frozen=True)
class TemporalMatch:
    date: str
    competition: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    neutral_ground: bool
    source: str
    kickoff_time: str | None = None
    sequence_index: int = 0
    source_order: int = 0
    data_quality: DataQualityLabel = "estimated_order"
    date_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sort_key(self) -> tuple[str, str, int, int, str, str]:
        return (
            self.date,
            self.kickoff_time or "00:00",
            self.sequence_index,
            self.source_order,
            self.home_team,
            self.away_team,
        )


@dataclass
class TeamRatingSnapshot:
    team: str
    internal_elo: float
    form: float
    attack: float
    defense: float
    goals_for_per_game: float
    goals_against_per_game: float
    match_count: int
    avg_opponent_elo: float
    opponent_adjusted_form: float
    rating_confidence: float


@dataclass
class RatingSnapshot:
    as_of_date: str
    teams: dict[str, TeamRatingSnapshot]
    low_confidence_teams: list[str] = field(default_factory=list)
    prior_quality: str = "default_internal"

    def get_team(self, team: str) -> TeamRatingSnapshot:
        if team in self.teams:
            return self.teams[team]
        return _default_team_snapshot(team)


@dataclass
class WalkForwardBacktestRow:
    dataset: str
    matches: int
    candidate: str
    elo_strategy: str
    world_elo_mode: str
    leakage_label: str
    outcome_accuracy: float
    exact_score_accuracy: float
    top3_score_hit_rate: float
    mean_log_loss: float
    mean_brier: float
    prior_mode: str = "default_internal"
    data_quality: str = "estimated_order"
    favorite_calibration_error: float = 0.0
    notes: str = ""
    external_rating_mode: str = "none"
    external_rating_type: str = "none"
    external_coverage: float = 0.0
    fifa_points_coverage: float = 0.0
    normalization_method: str = ""
    delta_log_loss_vs_baseline: float | None = None
    delta_brier_vs_baseline: float | None = None
    delta_1x2_acc_pp_vs_baseline: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemporalSnapshotDataManager:
    """Point-in-time team registry for walk-forward predictions."""

    def __init__(self, snapshot: RatingSnapshot) -> None:
        self._snapshot = snapshot
        self.team_database: dict[str, dict[str, float]] = {}
        for team, ts in snapshot.teams.items():
            self.team_database[team] = {
                "elo": ts.internal_elo,
                "form": ts.form,
                "attack": ts.attack,
                "defense": ts.defense,
                "goals_for_per_game": ts.goals_for_per_game,
                "goals_against_per_game": ts.goals_against_per_game,
                "rating_confidence": ts.rating_confidence,
                "opponent_adjusted_form": ts.opponent_adjusted_form,
                "avg_opponent_elo": ts.avg_opponent_elo,
                "match_count": float(ts.match_count),
            }

    def get_team_data(self, team_name: str, *, use_live: bool = False) -> dict[str, Any]:
        if team_name not in self.team_database:
            return _default_team_data(team_name)
        return self.team_database[team_name]

    def list_teams(self) -> list[str]:
        return list(self.team_database.keys())


def _default_team_snapshot(team: str) -> TeamRatingSnapshot:
    derived = compute_derived_metrics(INITIAL_ELO)
    return TeamRatingSnapshot(
        team=team,
        internal_elo=INITIAL_ELO,
        form=derived["form"],
        attack=derived["attack"],
        defense=derived["defense"],
        goals_for_per_game=config.GLOBAL_XG_AVG / 2.0,
        goals_against_per_game=config.GLOBAL_XG_AVG / 2.0,
        match_count=0,
        avg_opponent_elo=INITIAL_ELO,
        opponent_adjusted_form=derived["form"],
        rating_confidence=config.TEMPORAL_MIN_CONFIDENCE,
    )


def _default_team_data(team: str) -> dict[str, float]:
    ts = _default_team_snapshot(team)
    return {
        "elo": ts.internal_elo,
        "form": ts.form,
        "attack": ts.attack,
        "defense": ts.defense,
        "goals_for_per_game": ts.goals_for_per_game,
        "goals_against_per_game": ts.goals_against_per_game,
        "rating_confidence": ts.rating_confidence,
        "opponent_adjusted_form": ts.opponent_adjusted_form,
        "avg_opponent_elo": ts.avg_opponent_elo,
        "match_count": 0.0,
    }


def _tournament_temporal_matches(
    matches: tuple,
    *,
    competition: str,
    source: str,
    start: date,
) -> list[TemporalMatch]:
    out: list[TemporalMatch] = []
    for index, match in enumerate(matches):
        neutral = getattr(match, "neutral", True)
        out.append(
            TemporalMatch(
                date=(start + timedelta(days=index)).isoformat(),
                competition=competition,
                home_team=match.home,
                away_team=match.away,
                home_goals=match.home_goals,
                away_goals=match.away_goals,
                neutral_ground=neutral,
                source=source,
                sequence_index=index + 1,
                source_order=index,
                data_quality="estimated_order",
                date_estimated=True,
            )
        )
    return out


def _raw_historical_matches(dataset: str) -> list[TemporalMatch]:
    key = resolve_dataset_key(dataset)
    if key == "wc2018":
        from data.wc2018 import WC2018_MATCHES

        return _tournament_temporal_matches(
            WC2018_MATCHES,
            competition="FIFA World Cup",
            source="wc2018",
            start=date(2018, 6, 14),
        )
    if key == "wc2022":
        from data.wc2022 import WC2022_MATCHES

        return _tournament_temporal_matches(
            WC2022_MATCHES,
            competition="FIFA World Cup",
            source="wc2022",
            start=date(2022, 11, 20),
        )
    if key == "euro2024":
        from data.euro2024 import EURO2024_MATCHES

        return _tournament_temporal_matches(
            EURO2024_MATCHES,
            competition="UEFA European Championship",
            source="euro2024",
            start=date(2024, 6, 14),
        )
    if key == "copa2024":
        from data.copa2024 import COPA2024_MATCHES

        return _tournament_temporal_matches(
            COPA2024_MATCHES,
            competition="Copa America",
            source="copa2024",
            start=date(2024, 6, 20),
        )
    if key == "qualifiers2026":
        return [
            TemporalMatch(
                date=q.date,
                competition=q.competition,
                home_team=q.home,
                away_team=q.away,
                home_goals=q.home_goals,
                away_goals=q.away_goals,
                neutral_ground=True,
                source="qualifiers2026",
                sequence_index=i + 1,
                data_quality="exact_date",
                date_estimated=False,
            )
            for i, q in enumerate(WC2026_QUALIFIER_MATCHES)
        ]
    raise ValueError(f"Unsupported dataset: {dataset}")


def load_historical_matches(
    dataset: str,
    *,
    apply_overrides: bool = True,
) -> list[TemporalMatch]:
    """Load normalized historical matches, sorted deterministically."""
    key = resolve_dataset_key(dataset)
    if key == "all":
        combined: list[TemporalMatch] = []
        for dk in list_dataset_keys():
            combined.extend(load_historical_matches(dk, apply_overrides=apply_overrides))
        combined.sort(key=lambda m: m.sort_key)
        return combined

    matches = _raw_historical_matches(key)
    if apply_overrides:
        matches = apply_match_date_overrides(matches, key)
    matches.sort(key=lambda m: m.sort_key)
    return matches


def matches_before_target(
    matches: list[TemporalMatch],
    target: TemporalMatch,
) -> list[TemporalMatch]:
    """Matches strictly before target (datetime, sequence, or date ordering)."""
    tkey = target.sort_key
    return [m for m in matches if m.sort_key < tkey]


def matches_before_date(
    matches: list[TemporalMatch],
    as_of_date: str,
) -> list[TemporalMatch]:
    """Legacy: date-only filter."""
    return [m for m in matches if m.date < as_of_date]


def dataset_data_quality_summary(matches: list[TemporalMatch]) -> str:
    if not matches:
        return "missing_date"
    qualities = {m.data_quality for m in matches}
    if qualities == {"exact_datetime"}:
        return "exact_datetime"
    if "exact_datetime" in qualities or "exact_date" in qualities:
        if "estimated_order" in qualities:
            return "mixed"
        return "exact_date"
    if all(m.data_quality == "exact_date" for m in matches):
        return "exact_date"
    if any(m.data_quality == "missing_date" for m in matches):
        return "missing_date"
    return "estimated_order"


def leakage_label_for_dataset_quality(
    matches: list[TemporalMatch],
    *,
    world_elo_mode: WorldEloMode = "none",
    prior_mode: str = "default_internal",
    dataset_key: str = "",
) -> LeakageLabel:
    from core.fixture_metadata import classify_dataset_leakage

    label, _, _ = classify_dataset_leakage(
        matches,
        world_elo_mode=world_elo_mode,
        prior_mode=prior_mode,
        dataset_key=dataset_key,
    )
    return label  # type: ignore[return-value]


def leakage_label_for_mode(
    world_elo_mode: WorldEloMode,
    *,
    has_estimated_dates: bool = False,
    uses_static_nt_ratings: bool = False,
    data_quality_summary: str | None = None,
) -> LeakageLabel:
    if data_quality_summary:
        return _leakage_from_quality_summary(data_quality_summary, world_elo_mode)
    if world_elo_mode == "current_static" or uses_static_nt_ratings:
        return "high"
    if has_estimated_dates:
        return "medium"
    if world_elo_mode in ("snapshot_file", "proxy_from_internal"):
        return "medium"
    return "low"


def _leakage_from_quality_summary(
    summary: str,
    world_elo_mode: WorldEloMode,
) -> LeakageLabel:
    if world_elo_mode == "current_static":
        return "high"
    if summary in ("exact_datetime", "exact_date"):
        return "low"
    if summary in ("mixed", "estimated_order"):
        return "medium"
    return "high"


def _match_points(home_goals: int, away_goals: int, *, for_home: bool) -> float:
    if home_goals == away_goals:
        return 0.5
    if for_home:
        return 1.0 if home_goals > away_goals else 0.0
    return 1.0 if away_goals > home_goals else 0.0


def _update_elo_state(
    elos: dict[str, float],
    match: TemporalMatch,
    *,
    k_factor: float | None = None,
) -> None:
    home = match.home_team
    away = match.away_team
    home_elo = elos.get(home, INITIAL_ELO)
    away_elo = elos.get(away, INITIAL_ELO)
    home_adv = 0.0 if match.neutral_ground else config.DEFAULT_HOME_ADV
    new_home, new_away, _ = update_elo_pair(
        home_elo,
        away_elo,
        match.home_goals,
        match.away_goals,
        k=k_factor or config.TEMPORAL_ELO_K_FACTOR,
        home_advantage=home_adv,
    )
    elos[home] = new_home
    elos[away] = new_away


def build_rating_snapshot(
    as_of_date: str,
    matches_before: list[TemporalMatch],
    *,
    k_factor: float | None = None,
    initial_elos: dict[str, float] | None = None,
    prior_quality: str = "default_internal",
    dataset_for_priors: str | None = None,
) -> RatingSnapshot:
    """Build as-of-date ratings using only matches strictly before target."""
    elos: dict[str, float] = dict(initial_elos or {})
    team_history: dict[str, list[tuple[TemporalMatch, bool, float]]] = {}

    for match in sorted(matches_before, key=lambda m: m.sort_key):
        _update_elo_state(elos, match, k_factor=k_factor)
        opp_home = elos.get(match.away_team, INITIAL_ELO)
        opp_away = elos.get(match.home_team, INITIAL_ELO)
        team_history.setdefault(match.home_team, []).append((match, True, opp_home))
        team_history.setdefault(match.away_team, []).append((match, False, opp_away))

    teams: dict[str, TeamRatingSnapshot] = {}
    low_confidence: list[str] = []
    all_team_names = set(elos.keys()) | set(team_history.keys())

    for team in all_team_names:
        history = team_history.get(team, [])
        recent = history[-FORM_WINDOW:]
        count = len(recent)

        if count == 0:
            seeded_elo = elos.get(team, INITIAL_ELO)
            snap = _default_team_snapshot(team)
            teams[team] = TeamRatingSnapshot(
                team=team,
                internal_elo=round(seeded_elo, 1),
                form=snap.form,
                attack=snap.attack,
                defense=snap.defense,
                goals_for_per_game=snap.goals_for_per_game,
                goals_against_per_game=snap.goals_against_per_game,
                match_count=0,
                avg_opponent_elo=snap.avg_opponent_elo,
                opponent_adjusted_form=snap.opponent_adjusted_form,
                rating_confidence=snap.rating_confidence,
            )
            if seeded_elo == INITIAL_ELO:
                low_confidence.append(team)
            continue

        points: list[float] = []
        gf_total = 0.0
        ga_total = 0.0
        opp_elos: list[float] = []
        adj_points: list[float] = []

        for match, is_home, opp_elo in recent:
            if is_home:
                gf_total += match.home_goals
                ga_total += match.away_goals
                pt = _match_points(match.home_goals, match.away_goals, for_home=True)
            else:
                gf_total += match.away_goals
                ga_total += match.home_goals
                pt = _match_points(match.home_goals, match.away_goals, for_home=False)
            points.append(pt)
            opp_elos.append(opp_elo)
            expected = 1.0 / (1.0 + 10 ** ((opp_elo - elos.get(team, INITIAL_ELO)) / 400))
            adj_points.append(pt - expected + 0.5)

        form = round(sum(points) / count, 3)
        opp_adj_form = round(max(0.05, min(0.95, sum(adj_points) / count)), 3)
        gpg = round(gf_total / count, 2)
        gapg = round(ga_total / count, 2)
        avg_opp = round(sum(opp_elos) / count, 1)

        internal = elos.get(team, INITIAL_ELO)
        attack = round(min(0.95, max(0.05, 0.10 + (gpg / max(config.GLOBAL_XG_AVG, 0.5)) * 0.5)), 2)
        defense = round(min(0.95, max(0.05, 0.95 - (gapg / max(config.GLOBAL_XG_AVG, 0.5)) * 0.5)), 2)

        confidence = round(min(1.0, count / config.TEMPORAL_CONFIDENCE_MATCH_TARGET), 2)
        if count < config.TEMPORAL_LOW_CONFIDENCE_MATCHES:
            low_confidence.append(team)

        teams[team] = TeamRatingSnapshot(
            team=team,
            internal_elo=round(internal, 1),
            form=form,
            attack=attack,
            defense=defense,
            goals_for_per_game=gpg,
            goals_against_per_game=gapg,
            match_count=count,
            avg_opponent_elo=avg_opp,
            opponent_adjusted_form=opp_adj_form,
            rating_confidence=max(config.TEMPORAL_MIN_CONFIDENCE, confidence),
        )

    return RatingSnapshot(
        as_of_date=as_of_date,
        teams=teams,
        low_confidence_teams=low_confidence,
        prior_quality=prior_quality,
    )


def _rolling_elos_before_dataset(
    eval_matches: list[TemporalMatch],
    full_history: list[TemporalMatch],
) -> dict[str, float]:
    if not eval_matches:
        return {}
    first = min(eval_matches, key=lambda m: m.sort_key)
    prior = matches_before_target(full_history, first)
    if not prior:
        return {}
    snap = build_rating_snapshot(first.date, prior)
    return {team: ts.internal_elo for team, ts in snap.teams.items()}


def _resolve_snapshot_for_match(
    match: TemporalMatch,
    full_history: list[TemporalMatch],
    *,
    dataset_key: str,
    prior_mode: PriorMode,
) -> RatingSnapshot:
    prior = matches_before_target(full_history, match)
    rolling = _rolling_elos_before_dataset([match], full_history) if prior_mode == "rolling_from_prior_dataset" else None
    initial, prior_quality, _ = resolve_initial_elos(
        dataset_key,
        match.date,
        prior_mode=prior_mode,
        rolling_elos=rolling,
    )
    if prior_mode == "tournament_prior_file" and initial and not prior:
        return build_rating_snapshot(
            match.date,
            [],
            initial_elos=initial,
            prior_quality=prior_quality,
            dataset_for_priors=dataset_key,
        )
    if prior_mode == "tournament_prior_file" and initial:
        pre_snap = build_rating_snapshot(match.date, [], initial_elos=initial, prior_quality=prior_quality)
        merged_elos = {t: s.internal_elo for t, s in pre_snap.teams.items()}
        return build_rating_snapshot(match.date, prior, initial_elos=merged_elos, prior_quality=prior_quality)
    return build_rating_snapshot(match.date, prior, prior_quality=prior_quality)


def _load_world_elo_snapshot(path: Path) -> dict[str, float]:
    import json

    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "teams" in data:
        data = data["teams"]
    out: dict[str, float] = {}
    for name, val in data.items():
        if isinstance(val, dict):
            w = val.get("world_elo")
            if w is not None:
                out[name] = float(w)
        else:
            out[name] = float(val)
    return out


def resolve_world_elo(
    team: str,
    internal_elo: float,
    *,
    mode: WorldEloMode,
    rating_confidence: float,
    snapshot_path: Path | None = None,
    dataset_key: str | None = None,
    match_date: str | None = None,
) -> tuple[float, bool]:
    if mode == "none":
        return internal_elo, False
    if mode == "proxy_from_internal":
        return internal_elo, True
    if mode == "snapshot_file":
        if dataset_key:
            from core.external_rating_snapshots import get_team_external_rating

            world, available = get_team_external_rating(
                dataset_key,
                team,
                match_date=match_date,
            )
            if available and world is not None:
                return world, True
            return internal_elo, False
        path = snapshot_path or Path(config.TEMPORAL_WORLD_ELO_SNAPSHOT_PATH)
        snap = _load_world_elo_snapshot(path)
        if team in snap:
            return snap[team], True
        return internal_elo, False
    if mode == "current_static":
        from core.global_ratings import lookup_external_record

        ext = lookup_external_record(team)
        if ext.world_elo is not None:
            return float(ext.world_elo), True
        return internal_elo, False
    raise ValueError(f"Unknown world_elo_mode: {mode}")


def compute_temporal_effective_elo(
    team: str,
    strategy: str,
    snapshot: TeamRatingSnapshot,
    *,
    world_elo_mode: WorldEloMode,
    snapshot_path: Path | None = None,
    dataset_key: str | None = None,
    match_date: str | None = None,
) -> tuple[float, bool]:
    internal = snapshot.internal_elo
    world, world_available = resolve_world_elo(
        team,
        internal,
        mode=world_elo_mode,
        rating_confidence=snapshot.rating_confidence,
        snapshot_path=snapshot_path,
        dataset_key=dataset_key,
        match_date=match_date,
    )
    if world_elo_mode == "none":
        world_available = False

    wi, ww = blend_weights_for_strategy(
        strategy,
        internal_elo=internal,
        world_elo=world,
        rating_confidence=snapshot.rating_confidence,
        world_available=world_available,
    )
    if not world_available:
        wi, ww = 1.0, 0.0
    return round(wi * internal + ww * world, 1), world_available


_fifa_norm_cache: dict[str, dict[str, Any]] = {}


def _normalized_fifa_anchor(
    dataset_key: str,
    team: str,
) -> tuple[float | None, str]:
    from core.external_rating_mode import NORMALIZATION_METHOD, build_fifa_normalization_context

    if dataset_key not in _fifa_norm_cache:
        _fifa_norm_cache[dataset_key] = build_fifa_normalization_context(dataset_key)
    ctx = _fifa_norm_cache[dataset_key]
    team_ctx = ctx.get("teams", {}).get(team)
    if not team_ctx:
        return None, ctx.get("normalization_method", NORMALIZATION_METHOD)
    return team_ctx.get("normalized_external_rating"), team_ctx.get(
        "normalization_method", NORMALIZATION_METHOD
    )


def compute_temporal_external_anchor(
    team: str,
    strategy: str,
    snapshot: TeamRatingSnapshot,
    *,
    dataset_key: str | None = None,
    match_date: str | None = None,
) -> tuple[float, bool, str]:
    """Blend internal Elo with normalized FIFA-points anchor (not World Elo)."""
    from core.external_rating_snapshots import get_team_fifa_points

    internal = snapshot.internal_elo
    norm_method = ""
    external = internal
    external_available = False

    if dataset_key:
        fifa_points, fifa_available = get_team_fifa_points(
            dataset_key,
            team,
            match_date=match_date,
        )
        if fifa_available and fifa_points is not None:
            normalized, norm_method = _normalized_fifa_anchor(dataset_key, team)
            if normalized is not None:
                external = float(normalized)
                external_available = True

    wi, ww = blend_weights_for_strategy(
        strategy,
        internal_elo=internal,
        world_elo=external,
        rating_confidence=snapshot.rating_confidence,
        world_available=external_available,
    )
    if not external_available:
        wi, ww = 1.0, 0.0
    return round(wi * internal + ww * external, 1), external_available, norm_method


def compute_temporal_power(
    team: str,
    snapshot: TeamRatingSnapshot,
    *,
    candidate: str,
    elo_strategy: str = "internal_only",
    world_elo_mode: WorldEloMode = "none",
    snapshot_path: Path | None = None,
    dataset_key: str | None = None,
    match_date: str | None = None,
) -> tuple[float, float]:
    raw = snapshot
    internal = raw.internal_elo
    raw_form = raw.form
    attack = raw.attack
    defense = raw.defense
    adj_form = raw.opponent_adjusted_form

    if candidate in ("baseline", "current"):
        effective_elo = internal
        base = "current"
    elif candidate in EFFECTIVE_EXTERNAL_VARIANT_BASE:
        base = EFFECTIVE_EXTERNAL_VARIANT_BASE[candidate]
        effective_elo, _, _ = compute_temporal_external_anchor(
            team,
            elo_strategy,
            snapshot,
            dataset_key=dataset_key,
            match_date=match_date,
        )
    elif candidate in EFFECTIVE_VARIANT_BASE:
        base = EFFECTIVE_VARIANT_BASE[candidate]
        effective_elo, _ = compute_temporal_effective_elo(
            team,
            elo_strategy,
            snapshot,
            world_elo_mode=world_elo_mode,
            snapshot_path=snapshot_path,
            dataset_key=dataset_key,
            match_date=match_date,
        )
    else:
        raise ValueError(f"Unknown walk-forward candidate: {candidate}")

    form_used = _form_value_for_variant(base, raw_form, adj_form)
    defense_sign = _defense_sign_for_variant(base)

    elo_c = config.POWER_WEIGHT_ELO * effective_elo
    form_c = config.POWER_WEIGHT_FORM * form_used * 1000.0
    attack_c = config.POWER_WEIGHT_ATTACK * attack * 1000.0
    defense_c = defense_sign * config.POWER_WEIGHT_DEFENSE * defense * 1000.0
    total = elo_c + form_c + attack_c + defense_c
    return round(total, 2), effective_elo


def _temporal_matches_to_nt(matches: list[TemporalMatch]) -> list[NationalTeamMatch]:
    return [
        NationalTeamMatch(
            date=m.date,
            home=m.home_team,
            away=m.away_team,
            home_goals=m.home_goals,
            away_goals=m.away_goals,
            neutral=m.neutral_ground,
            competition=m.competition,
            weight=1.0,
        )
        for m in matches
    ]


def _favorite_bucket(prob: float) -> str | None:
    if prob >= 80:
        return "80+"
    if prob >= 70:
        return "70-80"
    if prob >= 60:
        return "60-70"
    if prob >= 50:
        return "50-60"
    return None


def run_temporal_shadow_pipeline(
    home: str,
    away: str,
    *,
    snapshot: RatingSnapshot,
    prior_matches: list[TemporalMatch],
    candidate: str = "baseline",
    elo_strategy: str = "internal_only",
    world_elo_mode: WorldEloMode = "none",
    advantage: float = 0.0,
    top_n: int = 3,
    snapshot_path: Path | None = None,
    dataset_key: str | None = None,
    match_date: str | None = None,
) -> dict[str, Any]:
    home_snap = snapshot.get_team(home)
    away_snap = snapshot.get_team(away)

    home_power, home_blend = compute_temporal_power(
        home,
        home_snap,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        snapshot_path=snapshot_path,
        dataset_key=dataset_key,
        match_date=match_date,
    )
    away_power, away_blend = compute_temporal_power(
        away,
        away_snap,
        candidate=candidate,
        elo_strategy=elo_strategy,
        world_elo_mode=world_elo_mode,
        snapshot_path=snapshot_path,
        dataset_key=dataset_key,
        match_date=match_date,
    )

    registry = {m.home_team for m in prior_matches} | {m.away_team for m in prior_matches}
    registry |= {home, away}
    opp_idx = build_opponent_index(_temporal_matches_to_nt(prior_matches), registry)

    dm = TemporalSnapshotDataManager(snapshot)
    home_data = dm.get_team_data(home)
    away_data = dm.get_team_data(away)

    home_xg, away_xg, _ = estimate_xg_opponent_aware(
        home,
        away,
        home_data.get("goals_for_per_game", 0.0),
        home_data.get("goals_against_per_game", 0.0),
        away_data.get("goals_for_per_game", 0.0),
        away_data.get("goals_against_per_game", 0.0),
        opp_idx,
        global_avg=config.GLOBAL_XG_AVG,
    )
    home_xg, away_xg = blend_maher_with_power(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        global_avg=config.GLOBAL_XG_AVG,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    home_xg, away_xg = floor_underdog_xg(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    blowout = apply_blowout_adjustment(
        home_xg,
        away_xg,
        home_power,
        away_power,
        advantage,
        base_alpha=config.OVERDISPERSION_ALPHA,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    home_xg, away_xg = blowout.home_xg, blowout.away_xg
    gap_for_rho = mismatch_gap(
        home_power,
        away_power,
        advantage,
        home_elo=home_blend,
        away_elo=away_blend,
    )
    engine = AdvancedDixonColesEngine(
        rho=scale_rho_for_gap(config.DEFAULT_RHO, gap_for_rho),
        global_avg=config.GLOBAL_XG_AVG,
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
    top_scores = [item["score"] for item in result.get("top_scores", [])]
    return {
        "probabilities_1x2": result["probabilities_1x2"],
        "top_scores": top_scores,
        "home_xg": result["home_xg"],
        "away_xg": result["away_xg"],
    }


def run_walk_forward_backtest(
    dataset: str,
    *,
    candidate: str = "baseline",
    elo_strategy: str = "internal_only",
    world_elo_mode: WorldEloMode = "none",
    external_rating_mode: str | None = None,
    prior_mode: PriorMode = "default_internal",
    snapshot_path: Path | None = None,
) -> WalkForwardBacktestRow:
    from core.backtest import _brier_score, _log_loss_score, _outcome, _predicted_outcome
    from core.external_rating_mode import (
        external_rating_type_label,
        legacy_world_elo_mode,
        resolve_external_rating_mode,
        world_elo_mode_for_resolve,
    )

    ext_mode = resolve_external_rating_mode(
        external_rating_mode=external_rating_mode,
        world_elo_mode=world_elo_mode,
    )
    resolved_world_mode: WorldEloMode = world_elo_mode_for_resolve(ext_mode)  # type: ignore[assignment]
    row_world_elo_mode = legacy_world_elo_mode(ext_mode)

    eval_matches = load_historical_matches(dataset)
    full_history = load_historical_matches("all")
    key = resolve_dataset_key(dataset)
    label = DATASET_REGISTRY[key].label if key in DATASET_REGISTRY else key

    dq_summary = dataset_data_quality_summary(eval_matches)
    from core.fixture_metadata import classify_dataset_leakage

    leakage, _, _ = classify_dataset_leakage(
        eval_matches,
        world_elo_mode=row_world_elo_mode,
        external_rating_mode=ext_mode,
        prior_mode=prior_mode,
        dataset_key=key,
    )

    external_coverage = 0.0
    normalization_method = ""
    ext_type = external_rating_type_label(ext_mode)
    wf_notes = "walk-forward full pipeline"

    if ext_mode == "world_elo_snapshot":
        from core.external_rating_snapshots import validate_external_rating_snapshot

        snap_report = validate_external_rating_snapshot(
            key, external_rating_mode="world_elo_snapshot"
        )
        external_coverage = snap_report.world_elo_coverage
        wf_notes = (
            f"walk-forward world_elo_snapshot; ext_cov={external_coverage:.2f}; "
            f"fallback=internal_when_missing"
        )
        if external_coverage < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:
            wf_notes += "; INSUFFICIENT_WORLD_ELO_SNAPSHOT"
        if external_coverage == 0.0:
            wf_notes += "; effective_elo_uses_internal_only"
    elif ext_mode == "fifa_points_snapshot":
        from core.external_rating_mode import NORMALIZATION_METHOD
        from core.external_rating_snapshots import validate_external_rating_snapshot

        snap_report = validate_external_rating_snapshot(
            key, external_rating_mode="fifa_points_snapshot"
        )
        external_coverage = snap_report.fifa_points_coverage
        normalization_method = NORMALIZATION_METHOD
        wf_notes = (
            f"walk-forward fifa_points_snapshot; fifa_cov={external_coverage:.2f}; "
            f"norm={normalization_method}; fallback=internal_when_missing"
        )
        if external_coverage < config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION:
            wf_notes += "; PARTIAL_FIFA_COVERAGE"
    elif ext_mode == "current_static_world_elo":
        wf_notes = "walk-forward current_static_world_elo (high leakage for history)"

    fifa_cov = external_coverage if ext_mode == "fifa_points_snapshot" else 0.0

    pv = "current" if candidate in ("baseline", "current") else candidate
    results: list[dict[str, Any]] = []
    bucket_errors: list[float] = []

    for match in eval_matches:
        prior = matches_before_target(full_history, match)
        snap = _resolve_snapshot_for_match(
            match,
            full_history,
            dataset_key=key,
            prior_mode=prior_mode,
        )
        pred = run_temporal_shadow_pipeline(
            match.home_team,
            match.away_team,
            snapshot=snap,
            prior_matches=prior,
            candidate=pv,
            elo_strategy=elo_strategy,
            world_elo_mode=resolved_world_mode,
            advantage=0.0 if match.neutral_ground else config.DEFAULT_HOME_ADV,
            snapshot_path=snapshot_path,
            dataset_key=key,
            match_date=match.date,
        )
        probs = pred["probabilities_1x2"]
        actual = _outcome(match.home_goals, match.away_goals)
        predicted = _predicted_outcome(probs)
        actual_score = f"{match.home_goals}-{match.away_goals}"
        prob_map = {"home": probs["home_win"], "draw": probs["draw"], "away": probs["away_win"]}

        fav_prob = max(probs["home_win"], probs["draw"], probs["away_win"])
        bucket = _favorite_bucket(fav_prob)
        if bucket:
            hit = 1.0 if (
                (predicted == "home" and actual == "home")
                or (predicted == "draw" and actual == "draw")
                or (predicted == "away" and actual == "away")
            ) else 0.0
            bucket_errors.append(abs(fav_prob / 100.0 - hit))

        results.append(
            {
                "outcome_correct": actual == predicted,
                "exact_hit": actual_score == pred["top_scores"][0] if pred["top_scores"] else False,
                "top3_hit": actual_score in pred["top_scores"][:3],
                "brier": _brier_score(probs, actual),
                "log_loss": _log_loss_score(prob_map[actual]),
            }
        )

    n = len(results)
    fav_calib = round(sum(bucket_errors) / len(bucket_errors), 4) if bucket_errors else 0.0

    if n == 0:
        return WalkForwardBacktestRow(
            dataset=label,
            matches=0,
            candidate=candidate,
            elo_strategy=elo_strategy,
            prior_mode=prior_mode,
            world_elo_mode=row_world_elo_mode,
            external_rating_mode=ext_mode,
            external_rating_type=ext_type,
            external_coverage=external_coverage,
            fifa_points_coverage=fifa_cov,
            normalization_method=normalization_method,
            leakage_label=leakage,
            data_quality=dq_summary,
            outcome_accuracy=0.0,
            exact_score_accuracy=0.0,
            top3_score_hit_rate=0.0,
            mean_log_loss=0.0,
            mean_brier=0.0,
            favorite_calibration_error=0.0,
            notes="no evaluable matches",
        )

    return WalkForwardBacktestRow(
        dataset=label,
        matches=n,
        candidate=candidate,
        elo_strategy=elo_strategy,
        prior_mode=prior_mode,
        world_elo_mode=row_world_elo_mode,
        external_rating_mode=ext_mode,
        external_rating_type=ext_type,
        external_coverage=external_coverage,
        fifa_points_coverage=fifa_cov,
        normalization_method=normalization_method,
        leakage_label=leakage,
        data_quality=dq_summary,
        outcome_accuracy=round(sum(r["outcome_correct"] for r in results) / n * 100, 1),
        exact_score_accuracy=round(sum(r["exact_hit"] for r in results) / n * 100, 1),
        top3_score_hit_rate=round(sum(r["top3_hit"] for r in results) / n * 100, 1),
        mean_log_loss=round(sum(r["log_loss"] for r in results) / n, 4),
        mean_brier=round(sum(r["brier"] for r in results) / n, 4),
        favorite_calibration_error=fav_calib,
        notes=wf_notes,
    )


def format_walk_forward_table(rows: list[WalkForwardBacktestRow]) -> str:
    header = (
        f"{'dataset':16} | {'n':>4} | {'candidate':30} | {'elo_strat':22} | "
        f"{'prior':>12} | {'world':>8} | {'leak':>4} | {'dq':>8} | "
        f"{'1x2':>5} | {'exact':>5} | {'top3':>5} | {'log_loss':>8} | "
        f"{'brier':>6} | {'fav':>5} | notes"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.dataset:16} | {row.matches:4d} | {row.candidate:30} | "
            f"{row.elo_strategy:22} | {row.prior_mode:>12} | {row.world_elo_mode:>8} | "
            f"{row.leakage_label:>4} | {row.data_quality:>8} | "
            f"{row.outcome_accuracy:5.1f} | {row.exact_score_accuracy:5.1f} | "
            f"{row.top3_score_hit_rate:5.1f} | {row.mean_log_loss:8.4f} | "
            f"{row.mean_brier:6.4f} | {row.favorite_calibration_error:5.3f} | {row.notes}"
        )
    return "\n".join(lines)


def attach_walk_forward_baseline_deltas(
    rows: list[WalkForwardBacktestRow],
) -> list[WalkForwardBacktestRow]:
    """Add delta_*_vs_baseline columns relative to baseline per dataset."""
    baselines: dict[str, WalkForwardBacktestRow] = {}
    for row in rows:
        if row.candidate in ("baseline", "current") and row.elo_strategy == "internal_only":
            baselines[row.dataset] = row
    out: list[WalkForwardBacktestRow] = []
    for row in rows:
        base = baselines.get(row.dataset)
        if base and row is not base:
            out.append(
                replace(
                    row,
                    delta_log_loss_vs_baseline=round(
                        row.mean_log_loss - base.mean_log_loss, 4
                    ),
                    delta_brier_vs_baseline=round(row.mean_brier - base.mean_brier, 4),
                    delta_1x2_acc_pp_vs_baseline=round(
                        row.outcome_accuracy - base.outcome_accuracy, 1
                    ),
                )
            )
        else:
            out.append(
                replace(
                    row,
                    delta_log_loss_vs_baseline=0.0 if base else None,
                    delta_brier_vs_baseline=0.0 if base else None,
                    delta_1x2_acc_pp_vs_baseline=0.0 if base else None,
                )
            )
    return out


def write_walk_forward_csv(rows: list[WalkForwardBacktestRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    enriched = attach_walk_forward_baseline_deltas(rows)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(enriched[0].to_dict().keys()))
        writer.writeheader()
        for row in enriched:
            writer.writerow(row.to_dict())
