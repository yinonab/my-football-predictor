"""Global constants and hyperparameters — no magic numbers in core modules."""

GLOBAL_XG_AVG: float = 2.6  # Calibrated on WC18–26 bundle incl. qualifiers
DEFAULT_RHO: float = -0.15  # Calibrated on WC18+22 Euro24 Copa24+qualifiers
DEFAULT_HOME_ADV: float = 0.0  # WC neutral default; calibrated on WC 2022
OVERDISPERSION_ALPHA: float = 0.0  # Calibrated: Poisson core fits WC 2022 best

# Power decomposition weights
WEIGHT_ELO: float = 0.45
WEIGHT_FORM: float = 0.25
WEIGHT_ATTACK: float = 0.15
WEIGHT_DEFENSE: float = 0.15

# Environmental rule-based modifiers (not ML)
ALTITUDE_THRESHOLD_M: int = 1200
ALTITUDE_PENALTY: float = 0.04
STAR_ABSENT_PENALTY: float = 0.08
MIN_MODIFIER: float = 0.70
MAX_MODIFIER: float = 1.30

# API
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000
