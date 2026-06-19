"""Global constants and hyperparameters — no magic numbers in core modules."""

import os


def _env_bool(name: str, default: bool) -> bool:
    """Optional env override; default unchanged when variable unset."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

GLOBAL_XG_AVG: float = 2.6  # Calibrated on WC18–26 bundle incl. qualifiers
DEFAULT_RHO: float = -0.15  # Calibrated on WC18+22 Euro24 Copa24+qualifiers
DEFAULT_HOME_ADV: float = 0.0  # Legacy Dixon-Coles advantage param; Phase 4O uses power points
# Phase 4O — home advantage on composite power scale (~Elo-weighted, typical values ~700–900)
HOME_ADVANTAGE_POWER_POINTS: float = float(
    os.getenv("HOME_ADVANTAGE_POWER_POINTS", "35")
)
OVERDISPERSION_ALPHA: float = 0.0  # Calibrated: Poisson core fits WC 2022 best

# Power decomposition weights
WEIGHT_ELO: float = 0.45
WEIGHT_FORM: float = 0.25
WEIGHT_ATTACK: float = 0.15
WEIGHT_DEFENSE: float = 0.15

# Shadow calibration aliases (Phase 2A — candidate formulas use these)
POWER_WEIGHT_ELO: float = WEIGHT_ELO
POWER_WEIGHT_FORM: float = WEIGHT_FORM
POWER_WEIGHT_ATTACK: float = WEIGHT_ATTACK
POWER_WEIGHT_DEFENSE: float = WEIGHT_DEFENSE

# Environmental rule-based modifiers (not ML)
ALTITUDE_THRESHOLD_M: int = 1200
ALTITUDE_PENALTY: float = 0.04
STAR_ABSENT_PENALTY: float = 0.08
MIN_MODIFIER: float = 0.70
MAX_MODIFIER: float = 1.30

# Match context (rest / travel / weather)
TRAVEL_KM_THRESHOLD: float = 2000.0
RAIN_LIGHT_XG_PENALTY: float = 0.12
RAIN_HEAVY_XG_PENALTY: float = 0.28
HEAT_TEMP_C: float = 32.0
HEAT_XG_PENALTY: float = 0.10
COLD_TEMP_C: float = 5.0
COLD_XG_PENALTY: float = 0.06
CONTEXT_CACHE_HOURS: int = 6

# Global Rating Stack (diagnostics — Phase 1)
GLOBAL_RATINGS_ENABLED: bool = True
GLOBAL_RATINGS_AFFECT_PREDICTION: bool = False

GLOBAL_STRENGTH_WEIGHT_WORLD_ELO: float = 0.50
GLOBAL_STRENGTH_WEIGHT_INTERNAL_ELO: float = 0.25
GLOBAL_STRENGTH_WEIGHT_FIFA: float = 0.10
GLOBAL_STRENGTH_WEIGHT_ADJ_FORM: float = 0.15
DEFAULT_RATING_CONFIDENCE: float = 0.65

ELO_NORMALIZE_MIN: float = 1200.0
ELO_NORMALIZE_MAX: float = 2100.0
FIFA_POINTS_NORMALIZE_MAX: float = 1900.0
FIFA_RANK_NORMALIZE_MAX: float = 200.0

POWER_COMPRESSED_VS_ELO_RATIO: float = 0.45
FORM_INFLATED_RAW_MIN: float = 0.58
FORM_INFLATED_ADJ_RATIO: float = 0.75
LOW_RATING_CONFIDENCE_THRESHOLD: float = 0.60
MODEL_MARKET_DIVERGENCE_PP: float = 15.0
GLOBAL_POWER_NUDGE_MAX: float = 0.12

# Global strength gap labels (Phase 1.5 audit)
GLOBAL_STRENGTH_GAP_TINY_MAX: float = 0.05
GLOBAL_STRENGTH_GAP_SMALL_MAX: float = 0.10
GLOBAL_STRENGTH_GAP_MEDIUM_MAX: float = 0.20
GLOBAL_STRENGTH_GAP_LARGE_MAX: float = 0.35

# Warning severity thresholds (Phase 1.5)
POWER_COMPRESSED_HIGH_ELO_GAP: float = 200.0
POWER_COMPRESSED_HIGH_RATIO: float = 0.50
FORM_INFLATED_HIGH_DELTA: float = 0.20
FORM_INFLATED_MEDIUM_DELTA: float = 0.10
LOW_CONFIDENCE_HIGH_THRESHOLD: float = 0.50
MODEL_MARKET_DIVERGENCE_HIGH_PP: float = 20.0

# Power component audit (Phase 1.6)
POWER_COMPONENT_DIAGNOSTICS_ENABLED: bool = True
POWER_COMPONENT_CANCEL_ELO_GAP: float = 150.0
POWER_COMPONENT_CANCEL_RATIO: float = 0.55
FORM_OVERPOWERS_ELO_RATIO: float = 0.85
ATTACK_DEFENSE_RAW_MIN: float = 0.05
ATTACK_DEFENSE_RAW_MAX: float = 0.95
POWER_SCALE_INCONSISTENT_RATIO: float = 2.5
DEFENSE_STRENGTH_GA_THRESHOLD: float = 1.2

# Shadow Power calibration (Phase 2A — diagnostics only by default)
POWER_SHADOW_CALIBRATION_ENABLED: bool = True
POWER_CANDIDATE_AFFECTS_PREDICTION: bool = _env_bool("POWER_CANDIDATE_AFFECTS_PREDICTION", False)
POWER_SHADOW_VARIANTS: tuple[str, ...] = (
    "current",
    "defense_flipped",
    "adjusted_form",
    "defense_flipped_adjusted_form",
)
POWER_SHADOW_COMPRESSION_THRESHOLD: float = 0.45
POWER_SHADOW_OVEREXPAND_RATIO: float = 1.25
POWER_SHADOW_ALIGNMENT_ELO_WEIGHT: float = 0.65
POWER_SHADOW_ALIGNMENT_WORLD_WEIGHT: float = 0.35

# Effective Elo anchor (Phase 2B — shadow only)
EFFECTIVE_ELO_STRATEGIES: tuple[str, ...] = (
    "internal_only",
    "world_only",
    "blended_static",
    "blended_confidence_weighted",
    "blended_disagreement_weighted",
)
EFFECTIVE_ELO_INTERNAL_WEIGHT_STATIC: float = 0.65
EFFECTIVE_ELO_WORLD_WEIGHT_STATIC: float = 0.35
EFFECTIVE_ELO_CONF_HIGH_INTERNAL: float = 0.75
EFFECTIVE_ELO_CONF_HIGH_WORLD: float = 0.25
EFFECTIVE_ELO_CONF_HIGH_THRESHOLD: float = 0.80
EFFECTIVE_ELO_CONF_MID_INTERNAL: float = 0.60
EFFECTIVE_ELO_CONF_MID_WORLD: float = 0.40
EFFECTIVE_ELO_CONF_LOW_INTERNAL: float = 0.45
EFFECTIVE_ELO_CONF_LOW_WORLD: float = 0.55
EFFECTIVE_ELO_CONF_LOW_THRESHOLD: float = 0.60
EFFECTIVE_ELO_DISAGREE_SMALL_INTERNAL: float = 0.75
EFFECTIVE_ELO_DISAGREE_SMALL_WORLD: float = 0.25
EFFECTIVE_ELO_DISAGREE_SMALL_DELTA: float = 75.0
EFFECTIVE_ELO_DISAGREE_MID_INTERNAL: float = 0.60
EFFECTIVE_ELO_DISAGREE_MID_WORLD: float = 0.40
EFFECTIVE_ELO_DISAGREE_MID_DELTA: float = 150.0
EFFECTIVE_ELO_DISAGREE_LARGE_INTERNAL: float = 0.45
EFFECTIVE_ELO_DISAGREE_LARGE_WORLD: float = 0.55
EFFECTIVE_ELO_DIVERGENCE_THRESHOLD: float = 75.0
EFFECTIVE_ELO_WORLD_ANCHOR_THRESHOLD: float = 0.50
POWER_SHADOW_EFFECTIVE_VARIANTS: tuple[str, ...] = (
    "effective_elo_current_formula",
    "effective_elo_adjusted_form",
    "effective_elo_defense_flipped",
    "effective_elo_defense_flipped_adjusted_form",
)
POWER_SHADOW_API_TOP_VARIANTS: int = 5

# Phase 2C — Activation gate + balanced-match stability
ACTIVATION_MAX_1X2_DROP_PP: float = 1.5
ACTIVATION_MAX_LOGLOSS_WORSEN: float = 0.005
ACTIVATION_MAX_BRIER_WORSEN: float = 0.005
ACTIVATION_MAX_FAV_CALIB_WORSEN: float = 0.02
ACTIVATION_REQUIRE_MULTI_DATASET_IMPROVEMENT: bool = True
# Phase 2G — Meaningful improvement thresholds (candidate must beat baseline)
ACTIVATION_MIN_LOGLOSS_IMPROVEMENT: float = 0.005
ACTIVATION_MIN_BRIER_IMPROVEMENT: float = 0.003
ACTIVATION_ALLOW_EQUAL_IF_1X2_IMPROVES_PP: float = 1.0
ACTIVATION_TREAT_ZERO_DELTA_AS_NEUTRAL: bool = True
ACTIVATION_DELTA_FLOAT_TOLERANCE: float = 1e-9
BALANCED_MATCH_MAX_BASE_PROB: float = 45.0
BALANCED_MATCH_MAX_SHIFT_PP: float = 7.0
ACTIVATION_GATE_DEFAULT_CANDIDATE: tuple[str, str] = (
    "effective_elo_current_formula",
    "blended_confidence_weighted",
)

# Phase 2D — Walk-forward / temporal backtest
TEMPORAL_ELO_K_FACTOR: float = 40.0
TEMPORAL_CONFIDENCE_MATCH_TARGET: int = 10
TEMPORAL_LOW_CONFIDENCE_MATCHES: int = 3
TEMPORAL_MIN_CONFIDENCE: float = 0.35
TEMPORAL_WORLD_ELO_SNAPSHOT_PATH: str = "data/world_elo_historical_snapshot.json"
TEMPORAL_DEFAULT_WORLD_ELO_MODE: str = "none"
TEMPORAL_MATCH_DATES_OVERRIDES_PATH: str = "data/match_dates_overrides.json"
TEMPORAL_RATING_PRIORS_PATH: str = "data/rating_priors.json"
FIXTURE_STATE_OVERRIDES_PATH: str = "data/fixture_state_overrides.json"
TEMPORAL_DEFAULT_PRIOR_MODE: str = "default_internal"

# Phase 2H — Historical external rating snapshots (manual, no scraping)
EXTERNAL_RATING_SNAPSHOTS_PATH: str = "data/external_rating_snapshots.json"
EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION: float = 0.90
EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION: float = 0.90
PRODUCTION_EXTERNAL_FIFA_POINTS_MIN_COVERAGE: float = 1.00
PRODUCTION_FIFA_SNAPSHOT_DATASET: str = "wc2026_current"

# Phase 3A — Controlled model activation (disabled by default; env override for local/staging)
MODEL_ACTIVATION_ENABLED: bool = _env_bool("MODEL_ACTIVATION_ENABLED", False)
ACTIVE_POWER_CANDIDATE: str = "effective_external_current_formula"
ACTIVE_EXTERNAL_RATING_MODE: str = "fifa_points_snapshot"
ACTIVE_EXTERNAL_RATING_STRATEGY: str = "fifa_points_confidence_weighted"
ACTIVE_MODEL_VERSION: str = "v2.2.0-fifa-points-anchor"
BASELINE_MODEL_VERSION: str = "v2.1.3-baseline"
ACTIVE_FIFA_SNAPSHOT_DATASET: str = "wc2026_current"

# Phase 3D — Large shift review records (local/staging enablement)
ACTIVATION_LARGE_SHIFT_REVIEWS_PATH: str = "data/activation_large_shift_reviews.json"

# Phase 4H — Probability coherence + odds safety (default: odds diagnostics-only)
ODDS_AFFECT_PREDICTION: bool = _env_bool("ODDS_AFFECT_PREDICTION", False)

# Phase 4H — Calibration readiness (default off; no live transform until enabled)
PROBABILITY_CALIBRATION_ENABLED: bool = _env_bool("PROBABILITY_CALIBRATION_ENABLED", False)
PROBABILITY_CALIBRATION_METHOD: str = os.getenv("PROBABILITY_CALIBRATION_METHOD", "temperature")
PROBABILITY_CALIBRATION_TEMPERATURE: float = float(
    os.getenv("PROBABILITY_CALIBRATION_TEMPERATURE", "1.35")
)

# Phase 4X — football-data.org World Cup fixture provider (env-only key; never log token)
FOOTBALL_DATA_BASE_URL: str = os.getenv(
    "FOOTBALL_DATA_BASE_URL", "https://api.football-data.org/v4"
).rstrip("/")
FOOTBALL_DATA_ENABLED: bool = _env_bool("FOOTBALL_DATA_ENABLED", True)
FOOTBALL_DATA_WC_CODE: str = "WC"
FOOTBALL_DATA_WC_SEASON: int = 2026
FOOTBALL_DATA_REQUEST_TIMEOUT: int = int(os.getenv("FOOTBALL_DATA_REQUEST_TIMEOUT", "15"))

# API
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000
