# Football Predictor — WC 2026

Mobile-first football match prediction app with Hebrew RTL UI, Python FastAPI backend, and Dixon-Coles goal model calibrated on World Cup 2022.

## Architecture

```
Flutter (mobile/web)  ←→  FastAPI (Python)
                              ├── math_engine.py      Dixon-Coles + Poisson/NB
                              ├── team_power.py       Elo decomposition
                              ├── elo_updater.py      Dynamic rating updates
                              ├── tournament_sim.py   Monte Carlo groups + champion
                              ├── backtest.py         WC 2022 evaluation
                              └── data/
                                  ├── database.py     48 official WC 2026 teams
                                  ├── api_football.py Optional live stats
                                  └── wc2022.py       Historical backtest data
```

## Quick Start

### Backend
```powershell
cd my_football_predictor
.\start_backend.ps1 -Port 8001
```

Optional live stats:
```powershell
$env:API_FOOTBALL_KEY = "your-key"
```

### Flutter (Chrome / Android)
```powershell
cd mobile
flutter run -d chrome
```

API URL in settings: `http://127.0.0.1:8001`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Server status + live stats availability |
| GET | `/api/teams` | 48 teams list |
| GET | `/api/groups` | Groups A–L with Elo |
| GET | `/api/teams/info?name=` | Team group + Elo |
| POST | `/api/predict` | Match prediction (1X2, top-10 scores, coverage band) |
| GET | `/api/debug/global-ratings?home_team=&away_team=` | Global Rating Stack diagnostics only |
| POST | `/api/elo/update` | Update Elo after real result |
| POST | `/api/simulate/group` | Monte Carlo group standings |
| POST | `/api/simulate/champion` | Tournament winner odds |

## Model (v1.6 — WC 2022 calibrated)

| Parameter | Value |
|-----------|-------|
| Dixon-Coles ρ | −0.15 |
| Avg goals | 3.0 |
| Overdispersion α | 0.0 |
| Home advantage | 0 (neutral WC default) |
| Power formula | 45% Elo + 25% Form + 15% Attack − 15% Defense |

## Backtesting

```powershell
cd backend
python run_backtest.py
python run_calibrate.py
pytest tests/ -v
```

**WC 2022 results (calibrated):** 57.8% 1X2 · 12.5% exact score · 37.5% top-3 hit rate

## Phase 1.5 Global Ratings Audit

Phase 1.5 adds **reporting scripts** — still not a model change. Run these before enabling `GLOBAL_RATINGS_AFFECT_PREDICTION=true` to find:

- **Power compression** (large Elo/world gap, small Power gap)
- **Inflated form** (raw form vs opponent-adjusted form)
- **Missing external ratings** (teams falling back to internal Elo)
- **Low rating confidence** on underdogs or thin data

Team-level audit:

```powershell
cd backend
python scripts/audit_global_ratings.py --only-warnings
python scripts/audit_global_ratings.py --sort form_inflation --csv reports/global_ratings_audit.csv
```

Matchup-level audit (includes current neutral xG / 1X2 / top scores for context):

```powershell
python scripts/audit_matchup_divergence.py --sample
python scripts/audit_matchup_divergence.py --all --csv reports/matchup_divergence_audit.csv
```

`/api/predict` now also exposes `global_rating_diagnostics.gaps.global_strength_gap_label`, compression ratios, and structured `warning_details` with severity (`low` / `medium` / `high`). String `warnings` are unchanged for backward compatibility.

## Phase 1.6 Power Component Audit

Diagnostics-only decomposition of composite **Power** into Elo / form / attack / defense / H2H / context / modifier components. Does **not** change predictions.

Use this before editing `team_power.py` or enabling `GLOBAL_RATINGS_AFFECT_PREDICTION=true`.

Team-level:

```powershell
cd backend
python scripts/audit_power_components.py --only-warnings
python scripts/audit_power_components.py --sort compression_suspects
```

Matchup-level (shows `top_compression_driver`):

```powershell
python scripts/audit_power_matchups.py --sample
python scripts/audit_power_matchups.py --sample --csv reports/power_matchups_audit.csv
```

`/api/predict` → `global_rating_diagnostics.power_component_diagnostics` when `POWER_COMPONENT_DIAGNOSTICS_ENABLED=true` (default).

## Phase 2A Shadow Power Calibration

Tests **candidate Power fixes in shadow mode** without changing production predictions.

| Variant | Description |
|---------|-------------|
| `current` | Production v2.1.3 formula (default) |
| `defense_flipped` | Add defense term (+) instead of subtract |
| `adjusted_form` | Use opponent-adjusted form instead of raw form |
| `defense_flipped_adjusted_form` | Both fixes combined |

Flags in `config.py`:
- `POWER_SHADOW_CALIBRATION_ENABLED=true` — expose diagnostics in API
- `POWER_CANDIDATE_AFFECTS_PREDICTION=false` — production unchanged

```powershell
cd backend
python scripts/audit_power_shadow.py --sample
python scripts/audit_power_shadow.py --all --csv reports/power_shadow_audit.csv
python scripts/audit_power_shadow.py --sample --include-xg
python scripts/backtest_power_shadow.py
```

`/api/predict` → `global_rating_diagnostics.power_shadow_calibration` includes per-variant gaps, compression ratios, alignment scores, and optional shadow xG/1X2.

## Phase 2B Full-Pipeline Shadow Backtest + Global Elo Anchor Audit

Tests whether **internal Elo should be anchored to World Elo** — shadow-only, no production change.

Effective Elo strategies: `internal_only`, `world_only`, `blended_static`, `blended_confidence_weighted`, `blended_disagreement_weighted`.

Shadow variants: `effective_elo_current_formula`, `effective_elo_adjusted_form`, `effective_elo_defense_flipped`, `effective_elo_defense_flipped_adjusted_form`.

Full pipeline: Maher → power blend → underdog floor → blowout → Dixon-Coles.

```powershell
cd backend
python scripts/audit_effective_elo_anchor.py --sample
python scripts/audit_effective_elo_anchor.py --all --csv reports/effective_elo_anchor_audit.csv
python scripts/backtest_power_shadow.py --full-pipeline
```

API: `power_shadow_calibration.effective_elo_anchor` (top 5 shadow variants in response).

## Phase 2C Multi-Tournament Backtest + Activation Gate

Phase 2B found a promising effective Elo anchor, but **WC 2022 alone is insufficient** for production activation.

- Tests candidates across WC 2018, WC 2022, Euro 2024, Copa 2024, WC 2026 qualifiers, and combined history.
- **Defense flip excluded by default** — use `--include-defense-flip` only for exploratory runs.
- **Activation gate** requires passing log-loss, Brier, 1X2, and calibration thresholds across datasets.
- **Backtest leakage risk** must be reviewed before trusting absolute metrics — current backtest is **not walk-forward**.

```powershell
cd backend
python scripts/backtest_power_shadow.py --full-pipeline --dataset all --compare-top-candidates
python scripts/backtest_power_shadow.py --full-pipeline --dataset all --compare-top-candidates --csv reports/power_shadow_multitournament_backtest.csv
python scripts/audit_backtest_leakage.py
python scripts/evaluate_activation_gate.py
python scripts/regression_diagnostic_matchups.py
```

API: `power_shadow_calibration.activation_candidate_status` is `shadow_only` by default (no auto-activation).

## Phase 2E Walk-Forward Data Quality Hardening

Walk-forward is the **trusted evaluation path**, but reliability depends on temporal data quality.

- **Match date overrides** (`data/match_dates_overrides.json`) — curated real dates/times
- **Rating priors** (`data/rating_priors.json`) — pre-tournament Elo from existing FIFA snapshots
- **Prior modes**: `default_internal`, `tournament_prior_file`, `rolling_from_prior_dataset`
- **Current/static World Elo** remains blocked for historical activation (`world_elo_mode=none` default)

```powershell
cd backend
python scripts/audit_walk_forward_data_quality.py
python scripts/backtest_walk_forward.py --dataset wc2022 --compare-top-candidates --world-elo-mode none --prior-mode default_internal
python scripts/backtest_walk_forward.py --dataset all --compare-top-candidates --world-elo-mode none --prior-mode tournament_prior_file --csv reports/walk_forward_candidates.csv
python scripts/compare_static_vs_walk_forward.py --compare-candidates
python scripts/evaluate_activation_gate.py --run-walk-forward
```

Activation requires **low-leakage** walk-forward evidence (`NEEDS_BETTER_TEMPORAL_DATA` if promising but dates still estimated).

## Phase 2F Historical Fixture Metadata Completion

**Do not tune the model** (rho, floor, blowout, odds, Maher, xG, defense sign) until walk-forward evidence is **low leakage**.

This phase completes curated fixture metadata and pre-tournament priors — **production `/api/predict` is unchanged**.

- **Full override coverage** for `wc2018`, `wc2022`, `euro2024`, `copa2024` in `data/match_dates_overrides.json`
  - `exact_datetime` only when kickoff is known in repo (e.g. Qatar vs Ecuador opener)
  - otherwise `exact_date` + deterministic `sequence_index` (one match per calendar day from tournament start)
- **Rating priors** materialized in `data/rating_priors.json` from repo `FIFA_ELO` snapshots (`as_of` before first match)
- **Current/static World Elo** remains blocked for historical activation (`world_elo_mode=none`)
- **Activation gate** reports per-dataset blockers; PASS only when low-leakage criteria are truly met

```powershell
cd backend
python scripts/validate_match_date_overrides.py
python scripts/audit_walk_forward_data_quality.py --coverage
python scripts/backtest_walk_forward.py --dataset wc2022 --compare-top-candidates --world-elo-mode none --prior-mode tournament_prior_file
python scripts/backtest_walk_forward.py --dataset all --compare-top-candidates --world-elo-mode none --prior-mode tournament_prior_file --csv reports/walk_forward_candidates_phase2f.csv
python scripts/evaluate_activation_gate.py --run-walk-forward
```

## Phase 2H Historical External Rating Snapshots

Effective Elo cannot be fairly evaluated historically using **current** World Elo (`global_ratings.json`). Low-leakage walk-forward requires **as-of** external snapshots before each tournament.

- **Snapshot file**: `data/external_rating_snapshots.json` (manual curation only — no scraping)
- **`world_elo_mode=snapshot_file`**: uses per-tournament snapshots; missing `world_elo` falls back to internal (never `current_static`)
- **Empty/partial snapshots** are valid schema-wise but block effective Elo activation until coverage ≥ 90%
- **Production `/api/predict` unchanged**

```powershell
cd backend
python scripts/validate_external_rating_snapshots.py
python scripts/audit_walk_forward_data_quality.py --coverage
python scripts/backtest_walk_forward.py --dataset wc2022 --compare-top-candidates --world-elo-mode snapshot_file --prior-mode tournament_prior_file
python scripts/evaluate_activation_gate.py --run-walk-forward
```

## Phase 2G Activation Gate Semantics

Temporal data readiness and model activation readiness are **separate**:

- **Temporal data PASS** means walk-forward fixture metadata and priors are low-leakage ready — it does **not** mean a shadow candidate should be activated.
- A candidate must **meaningfully beat baseline** on walk-forward metrics before `MODEL_ACTIVATION_PASS`.
- Identical candidate metrics (zero deltas) yield `DATA_READY_MODEL_NEUTRAL` with `recommended_candidate: null`.
- `activation_candidate_status` in API may be `data_ready_model_neutral` (diagnostics only; predictions unchanged).

```powershell
cd backend
python scripts/evaluate_activation_gate.py --run-walk-forward
```

Expected when effective Elo matches baseline (`world_elo_mode=none`):

```
Temporal data status: PASS
Model candidate status: NO_MEANINGFUL_IMPROVEMENT
Overall status: DATA_READY_MODEL_NEUTRAL
Recommended candidate: None
```

## Phase 2D Temporal / Walk-Forward Backtesting

Previous static backtests are useful diagnostics but **not sufficient for activation** due to leakage risk (HIGH in Phase 2C).

Walk-forward mode uses **only information available before each match date**:
- As-of-date Elo from chronological match updates
- Form / attack / defense from prior matches only
- Opponent-aware xG from prior matches only
- Default `--world-elo-mode none` (no current `global_ratings.json` in historical tests)

```powershell
cd backend
python scripts/backtest_walk_forward.py --dataset wc2022 --candidate baseline --world-elo-mode none
python scripts/backtest_walk_forward.py --dataset all --candidate baseline --world-elo-mode none --csv reports/walk_forward_backtest.csv
python scripts/compare_static_vs_walk_forward.py
python scripts/evaluate_activation_gate.py --run-walk-forward
```

Activation gate now requires **low-leakage walk-forward results** (`FAIL_HIGH_LEAKAGE` for static-only).

## Global Rating Stack Diagnostics

Phase 1 adds an **observability layer** — not machine learning and **not a replacement** for the Dixon-Coles / Maher / Power model.

- Compares **internal Elo / Power** against **manual external anchors** (`data/global_ratings.json`: world Elo, optional FIFA fields).
- Computes **opponent-adjusted form** to flag qualifier inflation (weak schedules boosting form).
- Surfaces **warnings** in `/api/predict` under `global_rating_diagnostics` (e.g. compressed Power vs Elo, inflated form, low confidence, missing external data).
- **Predictions are unchanged by default** (`GLOBAL_RATINGS_AFFECT_PREDICTION=false` in `config.py`). Set `GLOBAL_RATINGS_AFFECT_PREDICTION=true` only for experimental power nudging.
- External ratings are **static / manually maintained** for now — no scraping in production.

CLI sanity check:

```powershell
cd backend
python scripts/diag_global_ratings.py
```

Debug API (no full prediction engine):

```
GET /api/debug/global-ratings?home_team=Portugal&away_team=DR%20Congo
```

## Phase 2I External Snapshot Rating Types — FIFA Points Mode

Historical walk-forward evaluation can use **pre-tournament FIFA ranking points** from repo constants (`WC2018_FIFA_ELO`, `WC2022_FIFA_ELO`, `EURO2024_FIFA_ELO`, `COPA2024_FIFA_ELO`). These are **not** World Elo and must **not** be stored in `world_elo` in `data/external_rating_snapshots.json`.

- `fifa_points` — FIFA ranking points from repo pre-tournament snapshots
- `world_elo` — remains `null` until true eloratings-style World Elo is curated
- FIFA points are normalized to internal-Elo scale (`tournament_zscore_to_internal_field`) for external-anchor blending only
- `world_elo_snapshot` mode stays blocked until real World Elo coverage exists
- Production `/api/predict` probabilities remain unchanged (`GLOBAL_RATINGS_AFFECT_PREDICTION=false`, `POWER_CANDIDATE_AFFECTS_PREDICTION=false`)

```powershell
cd backend
python scripts/validate_external_rating_snapshots.py
python scripts/backtest_walk_forward.py --dataset wc2022 --compare-top-candidates --external-rating-mode fifa_points_snapshot --prior-mode tournament_prior_file
python scripts/backtest_walk_forward.py --dataset all --compare-top-candidates --external-rating-mode fifa_points_snapshot --prior-mode tournament_prior_file --csv reports/walk_forward_fifa_points_candidates.csv
python scripts/evaluate_activation_gate.py --run-walk-forward
```

External rating modes (`--external-rating-mode`):

| Mode | Description |
|------|-------------|
| `none` | Internal Elo only (default baseline) |
| `fifa_points_snapshot` | Normalized FIFA points from `external_rating_snapshots.json` |
| `world_elo_snapshot` | True World Elo from snapshot file (blocked until populated) |
| `current_static_world_elo` | Current `global_ratings.json` (high leakage for history) |

Legacy `--world-elo-mode snapshot_file` maps to `world_elo_snapshot`. Euro 2024 has partial FIFA coverage (Poland missing in `EURO2024_FIFA_ELO` — not invented).

## Phase 3A Controlled Activation Wiring

The Phase 2J winning FIFA-points candidate is wired but **disabled by default**:

- `effective_external_current_formula` + `fifa_points_confidence_weighted` + `fifa_points_snapshot`
- `MODEL_ACTIVATION_ENABLED=false`
- `POWER_CANDIDATE_AFFECTS_PREDICTION=false`

Production `/api/predict` is unchanged until both flags are explicitly enabled. Safe fallback to baseline when snapshots, FIFA points, or config are invalid.

### Recommended rollout

1. Keep activation disabled (default).
2. Run `python -m pytest tests/ -q`.
3. Run `python scripts/activation_dry_run.py` (disabled — expect zero deltas).
4. Run `python scripts/activation_dry_run.py --enable-candidate` (simulated activation).
5. Review diagnostic matchups and `model_diagnostics` on `/api/predict`.
6. Only then consider enabling in local/staging.
7. Production enablement requires explicit approval.
8. **Rollback:** set `MODEL_ACTIVATION_ENABLED=false` and `POWER_CANDIDATE_AFFECTS_PREDICTION=false`.

```powershell
cd backend
python scripts/activation_dry_run.py
python scripts/activation_dry_run.py --enable-candidate --csv reports/activation_dry_run.csv
python scripts/evaluate_activation_gate.py --run-walk-forward --external-rating-mode fifa_points_snapshot --prior-mode tournament_prior_file --candidate-set serious
```

## Phase 3B Production Coverage / WC2026 FIFA Snapshot Readiness

Phase 3A wired the FIFA-points candidate but several production matchups fell back to baseline because historical tournament snapshots (e.g. `wc2022`) do not include all 48 WC 2026 teams. Phase 3B adds a **current production FIFA-points snapshot** (`wc2026_current`) sourced only from repo `FIFA_ELO_2026`.

- Historical tournament snapshots remain for walk-forward backtesting.
- Live `/api/predict` activation (when explicitly enabled) uses `wc2026_current`, not historical snapshots.
- `world_elo` stays `null`; FIFA points are never mislabeled as World Elo.
- Production remains **disabled by default** (`MODEL_ACTIVATION_ENABLED=false`, `POWER_CANDIDATE_AFFECTS_PREDICTION=false`).
- **Rollback:** set both activation flags to `false`.

```powershell
cd backend
python scripts/validate_external_rating_snapshots.py --dataset wc2026_current
python scripts/activation_dry_run.py --enable-candidate --sample-production
python scripts/activation_dry_run.py --enable-candidate --all-production-pairs --only-fallbacks
python scripts/check_activation_readiness.py
python -m pytest tests/ -q
```

## Phase 3C Local Candidate Enablement QA

Phase 3C does **not** enable production. It compares baseline vs the FIFA-points candidate across curated WC 2026 matchups so you can review shifts and fallbacks before any controlled enablement.

- Production `/api/predict` stays unchanged unless flags are explicitly enabled or tests simulate activation.
- Large shifts, balanced-match instability, favorite reversals, and fallbacks are flagged for review.
- Move to controlled enablement only when QA has no unexplained fallbacks and acceptable shift profile.

```powershell
cd backend
python scripts/check_activation_readiness.py
python scripts/activation_dry_run.py --enable-candidate --sample-production
python scripts/activation_dry_run.py --enable-candidate --all-production-pairs --only-fallbacks
python scripts/activation_qa_report.py --markdown reports/activation_qa_report.md --csv reports/activation_qa_report.csv
python scripts/activation_qa_report.py --only-large-shifts
python scripts/smoke_predict_active_candidate.py
python -m pytest tests/ -q
```

## Phase 3D Large Shift Review + Controlled Local Enablement

Phase 3C found one large shift (Germany vs Haiti, +11.5pp home win). Phase 3D explains large shifts, records review status, and provides a **local/staging enablement checklist**. Production remains disabled by default.

- Large shifts must be explained before controlled enablement.
- `review_large_activation_shifts.py` auto-classifies and records reviews in `data/activation_large_shift_reviews.json`.
- Local/staging enablement uses environment overrides only — not committed defaults.
- **Rollback:** set `MODEL_ACTIVATION_ENABLED=false` and `POWER_CANDIDATE_AFFECTS_PREDICTION=false`.

### Local/staging enable (not production defaults)

Set environment variables for local or staging runs only:

```powershell
$env:MODEL_ACTIVATION_ENABLED="true"
$env:POWER_CANDIDATE_AFFECTS_PREDICTION="true"
```

Production deployment requires explicit approval. Defaults in `config.py` stay `false`.

```powershell
cd backend
python scripts/explain_activation_shift.py --home Germany --away Haiti --markdown reports/germany_haiti_shift_explanation.md
python scripts/review_large_activation_shifts.py
python scripts/local_enablement_checklist.py
python scripts/activation_qa_report.py --only-large-shifts
python scripts/smoke_predict_active_candidate.py
python -m pytest tests/ -q
```

## Phase 3E Local/Staging Enablement Smoke + Release Readiness

Phase 3E validates **local/staging enablement** end-to-end without changing production defaults. Status `READY_FOR_STAGING_ENABLEMENT` means safe for controlled staging — **not** production deployment approval.

### Local/staging enable (environment only)

```powershell
cd backend
$env:MODEL_ACTIVATION_ENABLED="true"
$env:POWER_CANDIDATE_AFFECTS_PREDICTION="true"
# run API locally or deploy to staging with these env vars only
```

### Rollback (immediate)

```powershell
$env:MODEL_ACTIVATION_ENABLED="false"
$env:POWER_CANDIDATE_AFFECTS_PREDICTION="false"
# restart process — no persisted activation state in repo defaults
```

Defaults in `config.py` remain `false`. Production deployment still requires explicit approval.

### Smoke + release commands

```powershell
cd backend
python scripts/smoke_local_activation_enabled.py
python scripts/smoke_activation_rollback.py
python scripts/release_readiness_report.py --markdown reports/release_readiness_report.md
python scripts/local_enablement_checklist.py
python scripts/check_activation_readiness.py
python -m pytest tests/ -q
```

### Frontend / mobile compatibility

`/api/predict` adds optional `model_diagnostics` (Phase 3A). The Flutter mobile client parses only existing prediction fields (`probabilities_1x2`, `top_scores`, `home_xg`, etc.) and **ignores** `model_diagnostics` — no UI or schema break.

## Phase 3F Staging Enablement Runbook

Step-by-step local/staging enablement, verification, and rollback: **[docs/STAGING_MODEL_ACTIVATION.md](docs/STAGING_MODEL_ACTIVATION.md)**

- Phase 3E status: `READY_FOR_STAGING_ENABLEMENT`
- Candidate: `v2.2.0-fifa-points-anchor` (production repo defaults remain disabled)
- Does **not** approve production activation

## Phase 2J FIFA Points Multi-Dataset Activation Evaluation

Phase 2I showed FIFA points improve WC 2022 walk-forward in low-leakage mode. Phase 2J runs the same evaluation across all tournament datasets and wires the activation gate to evaluate FIFA-points candidates explicitly.

- Still shadow/evaluation only — production `/api/predict` unchanged
- Activation requires multi-dataset improvement and gate pass (not WC 2022 alone)
- `world_elo` remains unavailable; FIFA points are a separate, correctly labeled external anchor

```powershell
cd backend
python scripts/backtest_walk_forward.py --dataset all --compare-top-candidates --external-rating-mode fifa_points_snapshot --prior-mode tournament_prior_file --csv reports/walk_forward_fifa_points_candidates.csv
python scripts/evaluate_activation_gate.py --run-walk-forward --external-rating-mode fifa_points_snapshot --prior-mode tournament_prior_file --candidate-set serious
python scripts/report_fifa_points_candidate_summary.py
python scripts/regression_diagnostic_matchups.py --external-rating-mode fifa_points_snapshot --candidate effective_external_current_formula --strategy fifa_points_confidence_weighted
```
