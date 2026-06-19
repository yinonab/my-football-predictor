# Prediction Intelligence Architecture

**Phase 4A — architectural foundation for a smarter football prediction system.**

This document describes the **current** production pipeline, the **target** layered architecture, a safe implementation roadmap, and explicit guardrails. It is planning documentation only unless a phase explicitly says otherwise.

**Live reference (as of Phase 4A):**

| Item | Value |
|------|-------|
| Active model (when enabled) | `v2.2.0-fifa-points-anchor` |
| Baseline model | `v2.1.3-baseline` |
| Activation flags | `MODEL_ACTIVATION_ENABLED`, `POWER_CANDIDATE_AFFECTS_PREDICTION` (both required) |
| Active candidate | `effective_external_current_formula` + `fifa_points_confidence_weighted` |

Related runbook: [STAGING_MODEL_ACTIVATION.md](STAGING_MODEL_ACTIVATION.md)

---

## 1. Current State

### Production prediction flow

When a client calls `POST /api/predict`, the backend runs the following pipeline. **No single module owns the full flow today** — orchestration lives in `backend/api/main.py` → `predict()`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. INPUT REQUEST                                                            │
│    PredictRequest: home_team, away_team, neutral_ground, optional context   │
│    Files: api/schemas.py, api/main.py                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. TEAM RESOLUTION + BASELINE POWER                                         │
│    LiveDataManager.resolve_team() → TeamPowerEvaluator.calculate_composite  │
│    Environmental modifiers (altitude, star_absent)                          │
│    Files: data/database.py, core/team_power.py, core/team_ratings.py        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. MATCH ADJUSTMENTS (pre-strength)                                         │
│    H2H adjustment → optional match context (rest, travel, weather, stage)   │
│    Files: core/h2h_adjustment.py, core/match_context.py,                    │
│           core/context_adjustments.py                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. ACTIVE FIFA-POINTS CANDIDATE (if both activation flags true)             │
│    try_apply_active_candidate_powers() → effective external Elo anchor      │
│    build_model_diagnostics() for response                                   │
│    Files: core/active_model_activation.py, core/power_effective_elo.py,     │
│           config.py (ACTIVE_* constants)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. Maher / xG CHAIN                                                         │
│    estimate_xg_opponent_aware → blend_maher_with_power → floor_underdog_xg  │
│    → context xG delta → apply_blowout_adjustment → scale_rho_for_gap        │
│    Files: core/opponent_maher.py, core/maher.py, core/blowout.py            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. DIXON–COLES / SCORE MATRIX                                               │
│    AdvancedDixonColesEngine.generate_match_prediction()                       │
│    Outputs: home_xg, away_xg, probabilities_1x2, top_scores, score_coverage │
│    Files: core/math_engine.py                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. OPTIONAL ODDS BLEND (1X2 ONLY)                                           │
│    OddsClient.fetch_match_odds() → blend_1x2() — 70% model / 30% market     │
│    **Only probabilities_1x2 and downstream text use blended values**        │
│    xG, top_scores, score_coverage remain from step 6                        │
│    Files: core/odds_ensemble.py                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. EXPLANATIONS                                                             │
│    explain_outcome_1x2, explain_exact_score, explain_score_coverage,        │
│    build_match_summary (+ H2H, Maher, blowout, context notes)                │
│    Files: core/explanations.py, api/main.py                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 9. DIAGNOSTICS (response payload, mostly non-predictive)                    │
│    global_rating_diagnostics — warnings, gaps, shadow comparison              │
│    model_diagnostics — version, activation, fallback                        │
│    Files: core/global_ratings.py, core/power_component_audit.py,            │
│           core/power_shadow_calibration.py, core/active_model_activation.py   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 10. MOBILE PARSING                                                          │
│     PredictionResult.fromJson — core fields only                              │
│     Ignores: model_diagnostics, global_rating_diagnostics                   │
│     Files: mobile/lib/models/prediction_result.dart,                        │
│            mobile/lib/screens/home_screen.dart                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Main files by concern

| Concern | Primary files |
|---------|---------------|
| HTTP orchestration | `backend/api/main.py` |
| API contracts | `backend/api/schemas.py` |
| Config / flags | `backend/config.py` |
| Team data & WC2026 registry | `backend/data/database.py` |
| Internal ratings cache | `backend/core/team_ratings.py`, `data/cache/nt_ratings.json` |
| Power formula | `backend/core/team_power.py` |
| Activation | `backend/core/active_model_activation.py` |
| Effective Elo / FIFA anchor | `backend/core/power_effective_elo.py` |
| External snapshots | `backend/core/external_rating_snapshots.py`, `data/external_rating_snapshots.json` |
| xG | `backend/core/maher.py`, `backend/core/opponent_maher.py`, `backend/core/blowout.py` |
| Score matrix | `backend/core/math_engine.py` |
| Odds | `backend/core/odds_ensemble.py` |
| Explanations | `backend/core/explanations.py` |
| Walk-forward / shadow eval | `backend/core/temporal_backtest.py`, `backend/core/power_shadow_calibration.py` |
| Activation gate | `backend/core/model_activation_gate.py` |
| Release / smoke | `backend/core/release_readiness.py`, `backend/scripts/smoke_*.py` |
| Mobile | `mobile/lib/models/prediction_result.dart`, `mobile/lib/screens/home_screen.dart` |

### Known gaps in current state

- Features are computed inline in `predict()`, not a reusable `MatchFeatures` object.
- Simple backtests (`backtest.py`) omit Maher, H2H, context, activation, and odds.
- Odds blend can make displayed 1X2 inconsistent with `top_scores` / xG.
- Calibration metrics (Brier, log-loss) exist for evaluation; no post-hoc calibrator on live output.
- Rich diagnostics are API-only; Flutter does not surface them.
- `/api/health` historically showed app version only, not active model (addressed in Phase 4A optional change).

---

## 2. Target Architecture Overview

The target system is organized into **layers**. Each layer has one responsibility. Upper layers consume lower layers; **prediction behavior changes only through explicit activation flags**.

```
 Data Layer
     ↓
 Match Feature Layer  (MatchFeatures)
     ↓
 Strength / Rating Layer  (StrengthResult)
     ↓
 Probability Engine Layer  (ProbabilityResult)
     ↓
 Market / Odds Layer  (diagnostics first; blend gated later)
     ↓
 Calibration Layer  (shadow / gated)
     ↓
 Confidence / Uncertainty Layer
     ↓
 Explainability Layer
     ↓
 Activation / Safety Layer  (wraps all intelligence features)
     ↓
 API / Mobile Contract
```

---

### A. Data Layer

**Purpose:** Provide raw, cached, and persisted inputs. No prediction logic.

| Source | Current location | Notes |
|--------|------------------|-------|
| Static team database | `data/database.py` — `FIFA_ELO_2026`, `LiveDataManager` | 48 WC2026 teams, baseline FIFA points |
| Internal ratings | `core/team_ratings.py` → `data/cache/nt_ratings.json` | Elo, attack, defense, form from NT history |
| FIFA points (production snapshot) | `data/external_rating_snapshots.json` — dataset `wc2026_current` | Used by active candidate |
| External rating snapshots (historical) | `core/external_rating_snapshots.py` | Walk-forward / multitournament eval |
| Match history (bundled) | `data/nt_history_bundle.py`, tournament modules | WC qualifiers, past tournaments |
| Match history (fetched) | `data/cache/nt_history_fetched.json` | API-Football when key set |
| Live results cache | `core/match_store.py` → `data/cache/wc2026_live_matches.json` | Manual `POST /api/elo/update` |
| Elo overrides | `core/elo_store.py` → `data/cache/elo_overrides.json` | Post-match patches |
| Odds data | `core/odds_ensemble.py` — The Odds API | Ephemeral per request |
| Context / weather / rest | `core/match_context.py`, `core/weather.py` | Optional per predict |
| H2H index | `core/h2h_adjustment.py` → `data/cache/h2h_index.json` | Pairwise history |
| Cloud persistence | `core/cloud_persist.py` | Optional Gist backup on Render |
| Manual global ratings | `data/global_ratings.json` | Diagnostics / world Elo confidence |

**Target:** Data layer stays distributed in files but exposes **stable loader functions** consumed only by `build_match_features()`.

---

### B. Match Feature Layer

**Target module:** `backend/core/match_features.py`  
**Target object:** `MatchFeatures`

**Purpose:** One object containing everything known about a match **before** strength and probability computation. Built once per request and reused by API, walk-forward shadow, diagnostics, and (later) ML training.

| Field | Status | Current source |
|-------|--------|----------------|
| `home_team` | **exists now** | `PredictRequest`, `resolve_team()` |
| `away_team` | **exists now** | same |
| `neutral_ground` | **exists now** | `PredictRequest.neutral_ground` |
| `internal_elo` | **exists now** | `LiveDataManager.get_team_data()` |
| `fifa_points` | **exists now** | `FIFA_ELO_2026` / external snapshot |
| `external_rating_gap` | **partial** | `global_ratings.build_team_diagnostics()` — not unified |
| `rating_disagreement` | **partial** | `power_effective_elo.blend_weights_for_strategy()` — activation only |
| `attack_strength` | **exists now** | `team_ratings` / `get_team_data` |
| `defense_strength` | **exists now** | same |
| `raw_form` | **exists now** | `team_ratings` last-10 form |
| `adjusted_form` | **partial** | `global_ratings.compute_opponent_adjusted_form()` — shadow/diagnostics; walk-forward variant in `temporal_backtest` |
| `h2h_signal` | **exists now** | `h2h_adjustment.apply_h2h_adjustment()` |
| `context_signal` | **partial** | `match_context` + `context_adjustments` — API path only |
| `rest_days` | **partial** | `MatchContextGatherer` — API only, not in backtests |
| `weather_signal` | **partial** | same |
| `tournament_stage` | **partial** | metadata in `match_context`; **not a model input** |
| `group_context` | **missing** | static groups only; no live standings |
| `must_win_context` | **missing** | future only |
| `odds_market_signal` | **partial** | fetched in `odds_ensemble`; not in feature object |
| `data_quality_flags` | **partial** | scattered warnings in `global_ratings`, `power_component_audit` |

**Target function:**

```python
def build_match_features(
    *,
    home_team: str,
    away_team: str,
    neutral_ground: bool,
    request_options: PredictOptions,  # future: bundles use_live, context, etc.
    data_manager: LiveDataManager,
) -> MatchFeatures:
    ...
```

**Rule:** API, `run_temporal_shadow_pipeline()`, and diagnostics must call the same builder (Phase 4B — **partial**: API `predict()` uses `build_match_features()`; walk-forward not yet wired).

#### MatchFeatures skeleton implemented (Phase 4B)

| Field group | Populated now | Still `None` / future |
|-------------|---------------|------------------------|
| Core identity | `home_team`, `away_team`, `resolved_*`, `neutral_ground` | — |
| Team data | `home_team_data`, `away_team_data` (copies) | — |
| Ratings | `internal_elo`, `attack`, `defense`, `raw_form`, `fifa_points`, `external_rating_gap` | `rating_disagreement` |
| Context | `group_context` (group letter(s)) | `h2h_signal`, `context_signal`, `rest_days`, `weather_signal`, `tournament_stage`, `must_win_context`, `odds_market_signal` |
| Diagnostics | `data_quality_flags` (unknown team, limited history) | `warnings` (empty; aggregated later) |

Module: `backend/core/match_features.py` — `to_debug_dict()` for scripts/tests only; not exposed on `/api/predict` yet.

---

### C. Strength / Rating Layer

**Target object:** `StrengthResult`

**Purpose:** Decide team strength for the probability engine, with explicit baseline vs active separation.

| Field | Status | Notes |
|-------|--------|-------|
| `baseline_home_power` | **exists now** (implicit) | `TeamPowerEvaluator` + H2H + context, pre-activation |
| `baseline_away_power` | **exists now** (implicit) | same |
| `active_home_power` | **exists now** | After `try_apply_active_candidate_powers()` |
| `active_away_power` | **exists now** | same |
| `baseline_gap` | **partial** | Computable; not explicit object |
| `active_gap` | **partial** | same |
| `rating_sources` | **partial** | In diagnostics, not structured |
| `fifa_anchor_details` | **partial** | `active_model_activation` + `power_effective_elo` |
| `fallback_to_baseline` | **exists now** | `model_diagnostics.fallback_to_baseline` |
| `fallback_reasons` | **exists now** | `model_diagnostics.fallback_reasons` |
| `warning_details` | **exists now** | `global_rating_diagnostics.warning_details` |
| `confidence` | **partial** | `rating_confidence` per team in diagnostics |

#### How `v2.2.0-fifa-points-anchor` fits

When **both** `MODEL_ACTIVATION_ENABLED=true` and `POWER_CANDIDATE_AFFECTS_PREDICTION=true`:

1. Baseline power is computed from internal Elo, form, attack, defense (`team_power.py`).
2. `try_apply_active_candidate_powers()` replaces power/Elo with **effective external** strength:
   - Candidate: `effective_external_current_formula`
   - Strategy: `fifa_points_confidence_weighted`
   - Mode: `fifa_points_snapshot` (dataset `wc2026_current`)
3. `model_diagnostics.model_version` → `v2.2.0-fifa-points-anchor`.
4. On validation failure or missing FIFA data → `fallback_to_baseline=true`, baseline powers used.

**Target:** `StrengthResult` makes baseline vs active explicit; breakdown text must match active power (Phase 4C — **implemented**).

#### StrengthResult implemented (Phase 4C)

| Concept | Module / field | Notes |
|---------|----------------|-------|
| Baseline power | `baseline_home_power`, `baseline_away_power` | After H2H/context, before activation |
| Active candidate power | `active_home_power`, `active_away_power` | From `try_apply_active_candidate_powers()` |
| Final prediction power | `final_home_power`, `final_away_power` | Used by Maher/xG/engine; equals active when activation on, baseline on fallback |
| API `home_power` / `away_power` | `strength.final_*` | Unchanged numerically vs pre-4C |
| `model_diagnostics` | Additive: `baseline_*`, `active_*`, `final_*`, `gap_delta` | Contract fields preserved |
| Breakdown fix | `enrich_breakdown_text()` | `power_score` matches final; Hebrew note when active candidate applied |

Module: `backend/core/strength_result.py` — `build_strength_result()` wraps existing activation output; no recalculation.

---

### D. Probability Engine Layer

**Target object:** `ProbabilityResult`

**Purpose:** Single coherent source for all score-based outputs.

| Output | Status | Source today |
|--------|--------|--------------|
| `home_xg` | **exists now** | Maher chain → engine |
| `away_xg` | **exists now** | same |
| `score_matrix` | **exists now** (internal) | `math_engine` — not exposed in API |
| `probabilities_1x2_from_matrix` | **exists now** | Matrix marginals before odds |
| `top_scores` | **exists now** | From matrix |
| `score_coverage` | **exists now** | Greedy coverage from matrix |

**Coherence rule (target):**

> `probabilities_1x2`, `home_xg`, `away_xg`, and `top_scores` must derive from the **same** probability model unless a later layer explicitly documents and tests a transformation.

**Current issue:**

`blend_1x2()` in `odds_ensemble.py` modifies **only** `probabilities_1x2` (and explanation text that uses blended probs). `home_xg`, `away_xg`, and `top_scores` remain from the pre-blend Dixon–Coles matrix. This can produce:

- Favorite direction in 1X2 disagreeing with xG-implied favorite
- `top_scores` marginal sums not matching displayed 1X2

**Phase 4D — implemented:** `probability_diagnostics` on `/api/predict` exposes `raw_probabilities_1x2`, `final_probabilities_1x2`, `odds_blend_applied`, and `coherence_warnings`. Odds blend behavior unchanged.

#### ProbabilityResult + odds coherence diagnostics (Phase 4D)

| Item | Module / API field |
|------|-------------------|
| Raw matrix 1X2 | `probability_diagnostics.raw_probabilities_1x2` |
| Final displayed 1X2 | `probabilities_1x2` (= `final_probabilities_1x2`) |
| Coherence checks | `core/probability_coherence.py` |
| Structured wrapper | `core/probability_result.py` — `ProbabilityResult` |
| Odds blend | Unchanged — `blend_1x2()` 70/30 when market available |

Warning codes: `PROBABILITY_SUM_INVALID`, `ODDS_BLEND_APPLIED`, `FAVORITE_PROBABILITY_XG_MISMATCH`, `TOP_SCORE_DIRECTION_MISMATCH`, `ODDS_BLEND_1X2_SCORELINE_MISMATCH`.

#### Probability quality reports (Phase 4E)

Walk-forward calibration metrics only — `core/probability_quality.py`, `scripts/evaluate_probability_quality.py`. Compares **baseline** vs **active FIFA-points** candidate on wc2018/wc2022/euro2024/copa2024. No live calibrator; reports under `backend/reports/` (gitignored).

---

### E. Market / Odds Layer

**Current:**

- `OddsClient.fetch_match_odds()` — The Odds API v4, h2h market
- Proportional de-vig per bookmaker
- `blend_1x2()` — 70% model / 30% market on **final 1X2 only**
- `MODEL_MARKET_DIVERGENCE` warning in `global_rating_diagnostics` (pre-blend model vs market)

**Target role:**

| Stage | Behavior |
|-------|----------|
| **Now → 4D** | Odds as **diagnostics** and optional 1X2 blend (unchanged until flag) |
| **Future (gated)** | `ODDS_AFFECT_PREDICTION=false` by default |
| Disagreement detection | Already partial via `WARNING_MODEL_MARKET` |
| Coherence | If odds affect predictions, they must adjust **matrix or unified ProbabilityResult**, not orphan 1X2 |
| Coverage | Log bookmaker, raw odds, blend applied — in `probability_diagnostics` |

**Do not:** matrix-level odds blending in Phase 4A–4E.

---

### F. Calibration Layer

**Current:**

- Hyperparameter grid search: `core/calibrate.py` → `config` constants (rho, alpha, avg goals, home adv)
- Evaluation metrics: Brier, log-loss, favorite-bucket error in backtests and activation gate
- **No** ECE, reliability curves, temperature scaling, isotonic, or Platt on live output

**Target system:**

```
raw probabilities (from ProbabilityResult)
        ↓
  [optional, gated] calibrator (shadow-trained)
        ↓
calibrated probabilities → API when PROBABILITY_CALIBRATION_ENABLED=true
```

| Component | Status |
|-----------|--------|
| Raw probabilities | exists now |
| Calibrated probabilities | **missing** |
| ECE | **missing** |
| Reliability buckets | **partial** (`_favorite_bucket` in backtests) |
| Brier / log-loss tracking | **exists now** (eval only) |
| Favorite bucket calibration | **partial** (eval; `ACTIVATION_MAX_FAV_CALIB_WORSEN` unused in gate) |
| Temperature scaling | **future only** |
| Isotonic regression | **future only** |
| Platt scaling | **future only** if binary subtasks warrant it |

**Rules for all calibrators:**

1. Shadow-evaluated first (walk-forward rows)
2. Walk-forward tested with leakage controls (`temporal_backtest.py`, `backtest_leakage_audit.py`)
3. Must pass activation gate (or dedicated calibration gate)
4. `PROBABILITY_CALIBRATION_ENABLED=false` by default
5. Never auto-enabled on Render

---

### G. Confidence / Uncertainty Layer

**Target object:** `ConfidenceDiagnostics` (future API field)

| Signal | Status | Source |
|--------|--------|--------|
| `confidence_level` (high/medium/low) | **missing** (structured) | future aggregation |
| `confidence_reasons` | **partial** | `warning_details`, `fallback_reasons` |
| Data quality warnings | **partial** | `MISSING_EXTERNAL_RATING`, temporal audits |
| Model disagreement warnings | **partial** | `POWER_COMPRESSED_VS_ELO`, component audit |
| Market disagreement warnings | **partial** | `MODEL_MARKET_DIVERGENCE` |
| Fallback warnings | **exists now** | `model_diagnostics` |
| Balanced match warnings | **partial** | `activation_qa.py`, gate — not live UI |
| User-facing confidence text | **missing** | future `explanation_diagnostics` |

**Target:** Aggregate backend warnings into one `confidence_level` + Hebrew summary for mobile (Phase 4N — future mobile UI).

---

### H. Explainability Layer

**Target object:** `ExplanationDiagnostics` (future)

| Element | Status | API | Mobile |
|---------|--------|-----|--------|
| `why_this_prediction` | **partial** | `match_summary` | shown |
| `top_drivers` | **missing** (structured) | component gaps in diagnostics only |
| Rating explanation | **partial** | `home_breakdown` / `away_breakdown` | expansion tile |
| xG explanation | **partial** | Maher/blowout notes in summary | indirect |
| Market disagreement explanation | **missing** | warning code only | not shown |
| Fallback explanation | **partial** | `fallback_reasons` | not shown |
| Mobile-friendly summary | **partial** | long Hebrew `match_summary` | shown |

**Smallest useful improvement:** One short `explanation_diagnostics.summary_he` + top 3 drivers (Phase 4N — future mobile UI).

**Known bug to fix in 4C:** Breakdown may describe baseline power while `home_power` shows active candidate power.

---

### I. Activation / Safety Layer

**Reuse existing (complete):**

| Mechanism | Location |
|-----------|----------|
| `MODEL_ACTIVATION_ENABLED` | `config.py` — default `false` |
| `POWER_CANDIDATE_AFFECTS_PREDICTION` | `config.py` — default `false` |
| Dual-flag gate | `model_activation_should_apply()` — `active_model_activation.py` |
| Activation gate | `model_activation_gate.evaluate_activation_gate()` |
| Rollback smoke | `scripts/smoke_activation_rollback.py` |
| Release readiness | `core/release_readiness.py` |
| `model_diagnostics` | per-request on `/api/predict` |
| `fallback_to_baseline` | per-request with reasons |
| Staging runbook | `docs/STAGING_MODEL_ACTIVATION.md` |

**Future flags (all default `false`):**

| Flag | Purpose |
|------|---------|
| `PROBABILITY_CALIBRATION_ENABLED` | Apply post-hoc calibrator to 1X2 |
| `ODDS_AFFECT_PREDICTION` | Explicit gate for any odds-driven probability change |
| `LIVE_TOURNAMENT_UPDATES_ENABLED` | Auto-ingest finished WC2026 matches |
| `ML_CANDIDATE_ENABLED` | Shadow/logistic candidate affects prediction |

**Principle:** Every intelligence feature is **default off** unless both documented env activation and gate pass (where applicable).

---

### J. API / Mobile Contract

#### Stable prediction fields (existing — must remain)

| Field | Purpose |
|-------|---------|
| `probabilities_1x2` | Home / draw / away win % |
| `home_xg`, `away_xg` | Expected goals |
| `top_scores` | Most likely scorelines |
| `score_coverage` | Mass covered by listed scores |
| `match_summary` | Hebrew narrative |
| `outcome_explanations` | Per-outcome text |
| `h2h_summary` | Head-to-head note |
| `home_power`, `away_power` | Composite strength |
| `home_breakdown`, `away_breakdown` | Component text |
| `match_context` | Rest, weather, travel (optional) |

#### Diagnostic fields (existing — additive)

| Field | Flutter today |
|-------|---------------|
| `model_diagnostics` | **ignored** |
| `global_rating_diagnostics` | **ignored** |

#### Future diagnostic fields (Phase 4D+)

| Field | Purpose |
|-------|---------|
| `probability_diagnostics` | Pre/post odds 1X2, matrix marginals, coherence flags |
| `confidence_diagnostics` | `confidence_level`, reasons, user text |
| `explanation_diagnostics` | Structured drivers, fallback/market explanations |

**Mobile parsing today** (`mobile/lib/models/prediction_result.dart`):

- Parses: teams, power, breakdowns, xG, probabilities, outcomes, top_scores, coverage, summaries, match_context
- Ignores: `model_diagnostics`, `global_rating_diagnostics`, any unknown keys (safe for additive API)

**Health endpoint (Phase 4A):** optional operational fields — see §3 Phase 4A.

---

## 3. Roadmap

### Phase 4A — Architecture doc + operational visibility ✅ (this document)

| Deliverable | Behavior change? |
|-------------|------------------|
| `docs/PREDICTION_INTELLIGENCE_ARCHITECTURE.md` | No |
| Optional `/api/health` model visibility fields | No — read config only, no predict |
| README link | No |

### Phase 4B — Unified `MatchFeatures` skeleton ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/match_features.py` — `MatchFeatures`, `build_match_features()` | ✅ |
| Wired into `api/main.py` → `predict()` for team resolution + team data | ✅ |
| `tests/test_match_features.py` — parity + predict stability | ✅ |
| Prediction behavior change | **No** |

### Phase 4C — `StrengthResult` cleanup ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/strength_result.py` — `StrengthResult`, `build_strength_result()` | ✅ |
| Wired into `predict()`; `model_diagnostics` enriched with power fields | ✅ |
| Breakdown `power_score` + activation note aligned with final power | ✅ |
| `tests/test_strength_result.py` | ✅ |
| Prediction probability/xG/top_scores change | **No** |

### Phase 4D — `ProbabilityResult` + odds coherence diagnostics ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/probability_result.py` — `ProbabilityResult`, `build_probability_result()` | ✅ |
| `backend/core/probability_coherence.py` — coherence helpers + warnings | ✅ |
| `probability_diagnostics` on `/api/predict` | ✅ |
| `tests/test_probability_result.py`, `tests/test_probability_coherence.py` | ✅ |
| Odds blend / prediction outputs change | **No** |

### Phase 4E — Probability quality reports ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/probability_quality.py` — ECE, reliability buckets, Brier, log-loss | ✅ |
| `backend/scripts/evaluate_probability_quality.py` — markdown + CSV reports | ✅ |
| `tests/test_probability_quality.py` | ✅ |
| Live prediction / calibrator change | **No** |

Generated artifacts (`backend/reports/probability_quality_report.*`) are gitignored and should not be committed by default.

### Phase 4F — Shadow calibration evaluation ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/probability_calibration.py` — Identity, Temperature, FavoriteShrink | ✅ |
| `backend/scripts/evaluate_probability_calibrators.py` | ✅ |
| `tests/test_probability_calibration.py` | ✅ |
| Live `/api/predict` / production calibrator | **No change** |

Shadow-only: `PROBABILITY_CALIBRATION_ENABLED` not wired. Bucket smoothing and isotonic (sklearn) deferred. Reports: `backend/reports/probability_calibrators_report.*` (gitignored).

### Phase 4G — Nested / holdout calibration validation ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/probability_calibration_validation.py` — LOO + fixed-candidate holdout validation | ✅ |
| `backend/scripts/validate_probability_calibrators.py` | ✅ |
| `tests/test_probability_calibration_validation.py` | ✅ |
| Live `/api/predict` / production calibrator | **No change** |

Phase 4F selected `temperature(T=1.35)` in-sample on 211 walk-forward rows. Phase 4G validates out-of-sample via leave-one-dataset-out and fixed-candidate evaluation. No `PROBABILITY_CALIBRATION_ENABLED` wiring. Reports: `backend/reports/probability_calibration_validation.*` (gitignored).

### Phase 4H — General probability coherence audit + gate + calibration readiness ✅

| Deliverable | Status |
|-------------|--------|
| `backend/scripts/audit_probability_coherence.py` — multi-matchup coherence audit | ✅ |
| `backend/core/probability_coherence_gate.py` — conservative blocking/advisory gate | ✅ |
| `backend/core/probability_coherence_audit.py` — audit row helpers | ✅ |
| `ODDS_AFFECT_PREDICTION=false` default — odds diagnostics-only | ✅ |
| `PROBABILITY_CALIBRATION_ENABLED=false` default — config/tests only | ✅ |
| `probability_diagnostics` extended (`odds_available`, `odds_affect_prediction`) | ✅ |
| `tests/test_probability_coherence_phase4h.py` | ✅ |
| Live calibration activation | **Blocked / default off** |

Phase 4G found a shadow-validated calibrator, but app screenshots exposed a likely general 1X2 vs xG/top_scores inconsistency (often when odds blend shifts final 1X2 only). Calibration activation is deferred until coherence is controlled. Odds influence is diagnostics-only by default; set `ODDS_AFFECT_PREDICTION=true` locally to restore legacy 70/30 1X2 blend (coherence gate will warn on mismatch). Reports: `backend/reports/probability_coherence_audit.*` (gitignored).

### Phase 4I — Coherent probability pipeline completion ✅

| Deliverable | Status |
|-------------|--------|
| `backend/core/probability_pipeline.py` — single final probability state | ✅ |
| `probability_coherence` on `/api/predict` (additive diagnostics) | ✅ |
| Explanation consistency (`ExplanationContext` for odds/calibration) | ✅ |
| Calibration runtime gated on coherence (default off) | ✅ |
| Extended coherence audit script | ✅ |
| `tests/test_probability_calibration_runtime.py` | ✅ |

Pipeline order: MatchFeatures → StrengthResult → score matrix/xG/top_scores → ProbabilityResult → odds diagnostics → coherence gate → optional calibration → API output.

Default: `ODDS_AFFECT_PREDICTION=false`, `PROBABILITY_CALIBRATION_ENABLED=false` — user-visible 1X2/xG/top_scores/explanations are coherent.

### Phase 4J — Release readiness / deploy decision for coherence safety

- Commit/deploy decision for odds diagnostics-only default
- Post-deploy coherence audit on Render
- Not live tournament updates yet

### Phase 4K — Prediction quality root-cause audit

- Audit-only phase: xG/Maher gaps, `top_scores` semantics, missing fixture state, host advantage diagnostics
- **Outcome:** calibration activation deferred until fixture/context foundation exists
- Canada vs Qatar: moderate power gap, 1–1 top score mathematically valid but product-confusing; completed matches not detected

### Phase 4L — Fixture State + Match Context Engine

- `FixtureState` model: `scheduled` | `live` | `completed` | `unknown`
- Resolver order: manual override → curated metadata → API-Football → unknown
- Additive `match_context_diagnostics` on `/api/predict`:
  - `prediction_valid`, `prediction_mode`, `actual_score`, fixture source warnings
  - Host-country detection (Canada/USA/Mexico) with `HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO` when `DEFAULT_HOME_ADV=0`
  - API-Football failure codes: `EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE`, `API_FOOTBALL_ACCOUNT_SUSPENDED`
- Completed matches: `prediction_valid=false`, `MATCH_ALREADY_COMPLETED` — prediction fields retained for backward compatibility
- **No xG/Maher/calibration tuning** in this phase

### Phase 4M — Scoreline Decision Engine

- **Display/decision layer only** — no change to Maher, xG, Dixon-Coles, power candidate, calibration, or odds math
- `top_scores` remain the highest-probability individual cells from the score matrix (backward compatible)
- New additive field: `scoreline_decision.primary_predicted_score` — user-facing central exact score
- `top_exact_score_overall` may differ from `primary_predicted_score` when the 1X2 favorite is home/away win but the single most likely cell is a draw (e.g. Canada vs Qatar)
- Algorithm: favorite from final 1X2 → group matrix cells by outcome → clear favorite picks highest cell within favorite bucket; balanced match uses top exact overall with `BALANCED_MATCH_LOW_CONFIDENCE`
- Uses full score matrix internally (`include_all_scores=True` in predict pipeline); matrix not exposed on public API
- Completed / invalid fixtures: warnings `MATCH_ALREADY_COMPLETED`, `PREDICTION_NOT_VALID`; confidence forced low
- Module: `backend/core/scoreline_decision.py`
- Audit: `backend/scripts/audit_scoreline_decision.py` → `backend/reports/scoreline_decision_audit.{md,csv}`

### Phase 4N — Calibration activation behind default-off flag

- Only after fixture/context foundation and scoreline UX
- `temperature(T=1.35)` from Phase 4G validation

### Phase 4O — Live tournament updates

- Finished-match ingest (API-Football or admin)
- Capped Elo update, persistence, rollback
- `LIVE_TOURNAMENT_UPDATES_ENABLED=false` default

### Phase 4P — ML shadow candidate

- **Only after MatchFeatures parity**
- Logistic regression on feature vector first
- Walk-forward gate required
- `ML_CANDIDATE_ENABLED=false` default

### Phase 4Q — Mobile confidence / explainability UI

- Parse `model_diagnostics`, `probability_coherence`, `match_context_diagnostics`, `confidence_diagnostics`
- Show model version, fallback badge, coherence warnings, completed-match state
- **No prediction logic change** — mobile display only

---

## 4. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| **API / backtest divergence** | False confidence in improvements | `MatchFeatures` parity tests; walk-forward shadow as canonical eval path |
| **Odds breaking xG / top_scores coherence** | User sees contradictory UI | Phase 4D diagnostics; future matrix-level blend behind `ODDS_AFFECT_PREDICTION` |
| **Overfitting calibrators** | Overconfident favorites on WC2022 only | Walk-forward only; multi-dataset gate; default off |
| **Live result leakage** | Future matches influence past preds | Separate walk-forward snapshots; audit in `backtest_leakage_audit.py` |
| **Render persistence / cache loss** | Ratings reset on redeploy | `cloud_persist.py`; document manual restore |
| **Mobile parsing / UI overload** | Crashes or noisy UI | Additive fields only; optional debug/settings screen |
| **Too many flags without diagnostics** | Ops confusion | Every flag surfaces in `/api/health` or `model_diagnostics`; runbook updates |
| **Breakdown vs active power mismatch** | Misleading explanations | Phase 4C |
| **Health shows config, not per-request fallback** | Ops thinks active when FIFA missing | Document: health = env state; predict = per-request fallback |

---

## 5. Do Not Do Yet

Explicitly **out of scope** until later phases:

- ❌ No ML implementation (Phase 4P)
- ❌ No production calibrator affecting live 1X2 (Phase 4N+ after scoreline UX)
- ❌ No odds matrix blending (Phase 4D+ planning only)
- ❌ No automatic live WC2026 result updates (Phase 4O)
- ❌ No Maher, Dixon-Coles, xG, rho, floor, blowout, Power weight, or defense sign tuning
- ❌ No prediction behavior change in Phase 4A
- ❌ No Render env var changes as part of architecture work
- ❌ No commit/push/deploy without explicit user request

---

## 6. Acceptance Criteria for Phase 4A

| Criterion | Status |
|-----------|--------|
| `docs/PREDICTION_INTELLIGENCE_ARCHITECTURE.md` created | ✅ |
| README links to doc | ✅ |
| No prediction behavior change | Required |
| No Render env changes | Required |
| No secrets changed | Required |
| Tests pass if code changed | Required |
| Final report states whether code changed | Required |

---

## Appendix: File map (current → target layer)

| Current file | Layer |
|--------------|-------|
| `data/database.py`, `data/cache/*` | Data |
| `core/team_ratings.py`, `core/elo_store.py`, `core/match_store.py` | Data |
| `core/match_features.py` (future) | Match Feature |
| `core/team_power.py`, `core/active_model_activation.py`, `core/power_effective_elo.py` | Strength |
| `core/maher.py`, `core/opponent_maher.py`, `core/blowout.py`, `core/math_engine.py` | Probability |
| `core/odds_ensemble.py` | Market |
| `core/calibrate.py`, future calibrator module | Calibration |
| `core/global_ratings.py`, `core/power_component_audit.py` | Confidence |
| `core/explanations.py`, `core/activation_shift_explainer.py` | Explainability |
| `config.py`, `core/model_activation_gate.py`, `core/release_readiness.py` | Activation / Safety |
| `api/main.py`, `api/schemas.py`, `mobile/lib/*` | API / Mobile |
