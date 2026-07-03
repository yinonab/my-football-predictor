# Stable Prediction — Unified Fix Strategy

**Design branch:** `design/stable-prediction-unified-fix-strategy`  
**Based on diagnosis:** `2304df1` on `diagnosis/stable-goliath-underdog-scoreline`  
**Stable base:** `cff4c30c366980e75ad82f18fa96bfd0984c95f5` (`origin/main`)  
**Diagnosis reference:** [STABLE_GOLIATH_UNDERDOG_SCORELINE_DIAGNOSIS.md](./STABLE_GOLIATH_UNDERDOG_SCORELINE_DIAGNOSIS.md)  
**Audit script:** `backend/scripts/audit_stable_goliath_underdog_scoreline.py`  
**Mode:** Design only — no prediction math, UI, env, or deploy changes in this document.

---

## Executive Summary

The stable prediction path suffers from **two converging upstream inflation paths** and **one downstream presentation layer issue**:

1. **Foundation path (pre-fusion):** missing GF/GA → symmetric Maher fallback → power blend → aggressive underdog floor (~0.8) → elevated P(underdog scores).
2. **Amplification path (post-matrix):** wide 1X2 margin + power gap → high `blowout_t` → large favorite xG uplift (+1.5 to +2.0) → blowout scoreline candidates.
3. **Presentation path:** representative scoreline picker favors clean sheets even when P(underdog scores) ≈ 50–60%.

These are **connected but not identical**. Capping Goliath alone stops the worst favorite xG jumps but **does not** fix inflated underdog scoring probability or clean-sheet contradiction. Fixing the underdog floor alone **does not** stop Goliath from re-amplifying whatever base xG remains.

### Strategy options considered

| Option | Summary | Verdict |
|--------|---------|---------|
| **A — Foundation-first** | Maher → floor → attack/defense → Goliath cap → scoreline | Correct long-term ordering for *root causes*, but leaves extreme Goliath jumps visible until late stages; cap tuning depends on foundation state. |
| **B — Goliath-first** | Cap fusion → floor/fallback → scoreline | Pragmatic for user-visible blowouts; risks under-correcting if scoreline guard ships too early. |
| **C — Combined minimal** | Cap + adaptive floor + scoreline guard in one PR | Fastest single deploy; **rejected** — hard to attribute regressions; floor + cap may over-suppress weak underdogs. |
| **D — Two-phase safe** | Phase 1 safety caps; Phase 2 foundation; scoreline after xG | **Preferred base** — staged, measurable, rollback-friendly. |
| **E — Refined D** | Stage 1 cap only; Stage 2 foundation bundle; Stage 3 scoreline; Stage 4 external; Stage 5 OFF-path | **Recommended** — see below. |

### Recommended strategy: **Refined Option E (staged two-phase core + deferred scoreline)**

| Stage | Focus | Ship alone? |
|-------|-------|-------------|
| **1** | Fusion favorite uplift cap (underdog unchanged) | **Yes — first implementation** |
| **2** | Maher fallback confidence + adaptive underdog floor (+ optional small attack/defense) | **Bundle together** |
| **3** | Scoreline clean-sheet coherence guard | After Stage 2 measured |
| **4** | Altitude persistence, odds isolation, context guardrails | Independent, low priority |
| **5** | Standard blowout OFF-path cap | After Stage 1 semantics settled |

**First implementation decision:** `IMPLEMENT_STAGE_1_ONLY` — not foundation-first, not Stage 1+2 together.

**Why not cap Goliath together with adaptive floor?** Both reduce goal expectation on mismatch fixtures; combined in one release they can over-correct (favorite too low, underdog too low, BTTS collapsed). Stage 1 isolates the amplification layer so audit deltas are attributable.

**Why scoreline guard waits:** Fixing xG first changes P(underdog scores) and BTTS; guard thresholds set on today's numbers may misfire after Stage 2. Guard after foundation is stable.

---

## Root Cause Dependency Graph

```
[DATA LAYER]
Missing / zero GF-GA history
  └─> Maher estimate_xg_pair fallback: global_avg/2 per team (e.g. 1.30 / 1.30)
        └─> Weak attack rating NOT applied in Maher (legacy path)
              └─> Symmetric Maher before power blend
                    └─> blend_maher_with_power differentiates favorites only partially

Power gap large (|gap| > 200)
  └─> floor_underdog_xg: min ~0.80 for weaker side
        └─> Weak underdog xG inflated BEFORE Goliath
              └─> Pre-fusion base xG already mismatch-inconsistent
                    └─> Dixon-Coles matrix (1st pass)
                          └─> P(underdog scores) often 49–55% on "weak underdog" fixtures

Attack/defense ratings
  └─> team_power composite ONLY (legacy served path)
        └─> Indirect favorite uplift via blend; NO direct weak-attack suppression
              └─> Haiti / Cape Verde attack ~0.10 still floors to ~0.8 xG

[AMPLIFICATION LAYER — Goliath ON]
Blended 1X2 margin_pp + power_gap + optional market_t
  └─> compute_fusion_blowout_signal → blowout_t (often 0.65–0.87 on audit fixtures)
        └─> apply_fusion_blowout:
              ├─> fav_xg += t × max(0, fav_target - fav_xg)   [NO HARD CAP]
              └─> dog_xg = max(dog_floor, dog_xg × (1 - 0.12×t))  [dog_floor prevents collapse]
                    └─> Matrix regeneration (2nd pass)
                          └─> Final xG jumps (e.g. 2.37 → 4.27 ARG)
                                └─> Blowout primary candidates (3-0, 4-0)

[AMPLIFICATION LAYER — Goliath OFF]
apply_blowout_adjustment (standard blowout)
  └─> Also aggressive on same fixtures (e.g. ARG/CPV 4.40 / 0.95)
        └─> Lower priority; parallel semantics needed later

[DOWNSTREAM — SCORELINE]
Regenerated top_scores + final xG
  └─> build_scoreline_decision (representative utility)
        ├─> Favors floor(fav_xg + 0.5) goal target on clear favorites
        ├─> gate_candidate_adjustment boosts clean-sheet lines (+utility)
        └─> Warnings (PRIMARY_CLEAN_SHEET_WITH_UNDERDOG_XG_HIGH) are display-only
              └─> Primary 4-0 while P(ud scores) ≈ 53%, BTTS ≈ 45%
                    └─> UI underdog narrative / confidence feels contradictory

[EXTERNAL / UX — MOSTLY INDEPENDENT]
Persisted altitude=1500 (mobile SharedPreferences)
  └─> UI confusion; legacy xG path insensitive to altitude in audit

use_match_context=true + venue city
  └─> context_adjustments weather/travel delta
        └─> Can materially change xG (Houston: 4.27 → 2.89)
              └─> Interacts with fusion weather_factor

odds_affect_prediction=false
  └─> Skips 1X2 blend BUT market_odds still passed to fusion signal (market_t)
        └─> Indirect fusion_t inflation when odds fetched

API-Football fixture lookup failure
  └─> Context/diagnostics fallback only when use_match_context=false
```

### Dependency Q&A

| Question | Answer |
|----------|--------|
| **1. Upstream issues** | Missing GF/GA; Maher fallback symmetry; attack/defense not in Maher; underdog floor; power gap driving fusion signal inputs |
| **2. Downstream symptoms** | High P(underdog scores) with clean-sheet primary; BTTS elevated vs CS primary; UI narrative contradiction; extreme final favorite xG |
| **3. Independent issues** | Altitude persistence (UX); odds isolation policy; API-Football context fallback; standard blowout OFF-path (when fusion ON) |
| **4. Safe to fix alone** | Stage 1 Goliath cap; altitude UX cleanup; odds isolation; Stage 5 standard blowout (after Stage 1) |
| **5. Should NOT fix alone** | Adaptive floor without Maher confidence; attack/defense direct adjustment without floor review; scoreline guard before Stage 2; Goliath underdog suppression without floor alignment |
| **6. Fixes that mask root causes** | Scoreline guard alone; Goliath cap alone (masks favorite jump but not dog inflation); lowering top_n / hiding diagnostics |
| **7. Conflicting fixes** | Cap Goliath + adaptive floor + attack/defense (triple suppression); scoreline guard + unchanged high dog xG; direct attack/defense + power blend double-count; market_t removal + existing calibration tuned with market |

---

## Fix Candidate Evaluation Matrix

| # | Fix | Root cause | Improves | Does NOT improve | Risk | Alone or together | Files | Tests | Rollback | Key fixture impact |
|---|-----|------------|----------|------------------|------|-------------------|-------|-------|----------|-------------------|
| 1 | Cap fusion **favorite uplift** (e.g. MAX Δ ≤ 0.75–1.25) | Goliath over-amplification | Final fav xG, blowout primaries, fusion delta | Underdog floor, Maher symmetry, scoreline utility bias | **Low–medium** | **Stage 1 alone** | `fusion_blowout.py`, `config.py` | `test_fusion_blowout.py`, audit script | Config flag `FUSION_MAX_FAVORITE_UPLIFT` | ARG/CPV: Δ fav +1.90 → ~+1.0; FRA/HAI similar; POR/CRO barely changes (t≈0.13) |
| 2 | Cap **final fav xG** vs pre-fusion | Same as #1 | Hard ceiling on post-fusion fav | Underdog path; may clip before target interpolation differently than #1 | **Medium** | Prefer #1 or #3; not both without care | `fusion_blowout.py` | Fusion unit + audit | Same flag family | Competitive fixtures: ensure no clip when t low |
| 3 | Cap **blowout_t** (e.g. ≤ 0.55–0.65) | Signal over-confidence | All fusion uplift + dog_floor/dog shrink | Pre-fusion base xG | **Medium** | Alternative to #1; pick one primary cap | `fusion_blowout.py` | Fusion tests + audit | `FUSION_MAX_BLOWOUT_T` | Blunt instrument; may under-blowout true mismatches |
| 4 | **Adaptive underdog floor** (attack, fav defense, gap) | Weak underdog inflation pre-Goliath | Base away xG, P(ud scores) on Haiti/CPV/Curaçao | Goliath fav uplift; scoreline picker bias | **Medium–high** | **With #5** (Stage 2 bundle) | `maher.py`, `main.py` | Maher/floor tests, audit | `ADAPTIVE_UNDERDOG_FLOOR_ENABLED` | Weak UD: 0.80 → ~0.45–0.65 target band; must not touch POR/CRO ~0.96 |
| 5 | **Lower Maher trust** on GF/GA fallback | Maher flattening | Pre-blend symmetry, differentiation | Post-fusion amp | **Medium** | **With #4** | `maher.py`, `opponent_maher.py`, `main.py` | Maher source flag tests | `MAHER_FALLBACK_CONFIDENCE_WEIGHT` | Weak teams: Maher pair below 1.30/1.30 effective |
| 6 | **Direct attack-vs-defense** in legacy xG (small coeff.) | Attack/defense unused in Maher | Weak vs strong underdog split | Fusion signal (unless xG changes 1X2) | **High** | **With #4+#5** only after audit | `maher.py` or `main.py` | New unit + 12-fixture audit | Feature flag | Risk double-count with power blend |
| 7 | Goliath considers **P(ud scores)** | Blowout incoherent with scoring | Fusion intensity on high-dog-score matches | Maher floor | **Medium** | Stage 2b optional OR Stage 3 precursor | `fusion_blowout.py`, `main.py` | Integration tests | `FUSION_UD_SCORE_GATE` | May reduce t when dog P high — overlaps Stage 1+2 |
| 8 | **Scoreline clean-sheet guard** | CS bias downstream | Primary vs P(ud), BTTS coherence | xG magnitudes | **Low–medium** | **After Stage 2** (Stage 3) | `scoreline_decision.py` | Scoreline decision tests | `SCORELINE_CS_GUARD_ENABLED` | ARG/CPV: 4-0 → 3-1 or 4-1 if guard rules |
| 9 | **Altitude persistence** cleanup | Stale 1500 in UI | UX clarity | xG blowout (legacy) | **Low** | **Alone** (Stage 4 mobile) | `mobile/` prefs, maybe display | Widget tests | Revert mobile commit | No xG change required on backend |
| 10 | **Odds isolation** | market_t when odds_affect=false | Fusion signal purity | 1X2 when odds_affect=true | **Low–medium** | **Alone** (Stage 4) | `api/main.py`, `fusion_blowout.py` | Odds + fusion tests | Pass `None` for market when flag false | Slight t reduction when market fetched |
| 11 | **Standard blowout** cap (Goliath OFF) | OFF-path aggression | Users with fusion disabled | ON-path | **Low** | **Stage 5** after Stage 1 | `blowout.py` | Blowout tests | Mirror fusion cap semantics | ARG/CPV OFF: 4.40 → closer to capped ON |

### Cap value guidance (design targets, not implementation)

| Parameter | Conservative | Balanced (recommended start) | Aggressive |
|-----------|--------------|------------------------------|------------|
| MAX fusion Δ fav xG | +0.75 | **+1.00** | +1.25 |
| MAX blowout_t | 0.55 | **0.65** | 0.70 |
| Adaptive floor (weak attack ≤0.33, gap>200) | 0.65 | **0.50–0.60** | 0.45 |
| Scoreline guard P(ud) threshold | 50% | **45%** | 40% |

Use **one** primary fusion limiter in Stage 1: **pre-fusion-relative favorite uplift cap** (candidate #1). It is interpretable in audit (`fusion delta` column) and preserves `blowout_t` diagnostics.

---

## Dangerous Interactions and Guardrails

| Combination | Risk | Prevention | Tests | Order |
|-------------|------|------------|-------|-------|
| **Cap Goliath + adaptive floor** | Favorite and underdog both pushed down → low-scoring, collapsed BTTS | Ship separately; audit BTTS and total xG; competitive fixtures unchanged | 12-fixture matrix; assert POR/CRO BTTS ≥ 55% | Stage 1 → measure → Stage 2 |
| **Adaptive floor + Maher fallback confidence** | Double suppression of weak teams | Single Stage 2 PR with shared `underdog_effective_xg` bounds; cap minimum away xG at 0.35 | Haiti/CPV/Curaçao band; Senegal/Croatia not below audit −0.15 | Same commit |
| **Scoreline guard before xG fix** | Hides xG/model inconsistency; wrong primary for new probabilities | Defer to Stage 3; if urgent, use confidence label only, not primary swap | Compare guard output pre/post Stage 2 | After Stage 2 |
| **Attack/defense direct + power blend** | Double-count strength | Small coefficient (≤0.08); apply only when GF/GA fallback; exclude from power re-blend | Spain/Portugal must not drop below 1.0 away xG | Last in Stage 2 bundle |
| **Odds isolation + fusion signal** | Changes calibrated t for users with odds fetch | Stage 4 only; document behavior change | Fusion test with market present, odds_affect=false | After Stage 1 stable |
| **Altitude fix + context** | User thinks altitude changed xG when context did | Separate UI copy; show resolved altitude + context badge | Houston context ON/OFF pairs | Stage 4 |
| **Cap blowout_t + cap Δ fav** | Redundant / over-constrained | Pick one primary cap in Stage 1 | — | Stage 1 only one |
| **Stage 1 + Stage 2 same PR** | Attribution impossible | Separate branches/commits | — | **Forbidden** |

### Guardrails (global)

- No Matchup Relative, no model variant toggle.
- Each stage behind a config flag defaulting to **off** until validated, then default **on** in separate commit.
- Run full audit (`audit_stable_goliath_underdog_scoreline.py`) before/after every stage.
- Competitive fixtures (9–12): |Δ home_win| ≤ 3 pp, |Δ total xG| ≤ 0.15 unless documented.

---

## Preferred Unified Fix Strategy

### Stage 1 — Fusion safety cap (favorite only)

| Field | Detail |
|-------|--------|
| **Name** | Fusion favorite uplift cap |
| **Goal** | Stop +1.5 to +2.0 favorite xG jumps without touching underdog or scoreline logic |
| **Root causes** | Goliath over-amplification (#1) |
| **Files** | `backend/core/fusion_blowout.py`, `backend/config.py`, `backend/tests/test_fusion_blowout.py` |
| **Implementation idea** | After computing `fav_xg` uplift, clamp: `fav_xg ≤ pre_fusion_fav_xg + FUSION_MAX_FAVORITE_UPLIFT` (start **1.00**). Do not change `dog_xg` formula. Optional diagnostic field `uplift_capped: true`. |
| **What not to touch** | Maher, floor, scoreline, mobile, standard blowout, NR3 served |
| **Acceptance criteria** | ARG/CPV FRA/HAI FRA/CUR: Δ fav ≤ 1.05; final fav xG ≤ 3.5 for ARG/CPV; POR/CRO Δ fav ≤ 0.25; competitive fixtures: no 1X2 shift > 3 pp |
| **Fixtures** | 1–3 primary; 4–8 regression; 9–12 unchanged |
| **Tests** | Unit tests for cap edge cases; audit before/after table |
| **Rollback** | `FUSION_MAX_FAVORITE_UPLIFT=None` or flag disable → current behavior |
| **Commit** | **Separate commit/PR** — first production fix |

### Stage 2 — Weak underdog foundation bundle

| Field | Detail |
|-------|--------|
| **Name** | Maher confidence + adaptive underdog floor |
| **Goal** | Lower artificial underdog xG on weak teams; preserve dangerous underdogs |
| **Root causes** | #2, #4, #5, #6 (partial #3) |
| **Files** | `maher.py`, `opponent_maher.py`, `api/main.py` (pass attack/defense, gf_ga source), tests |
| **Implementation idea** | (a) Tag Maher output with `gf_ga_source`; down-weight fallback in blend. (b) `floor_underdog_xg`: floor = f(gap, underdog_attack, favorite_defense) with minimum ~0.35, weak attack cap ~0.55. (c) Optional: tiny attack/defense adjustment **only when fallback_zero**. |
| **What not to touch** | Fusion cap (Stage 1), scoreline, mobile |
| **Acceptance criteria** | Weak UD base away xG: 0.45–0.65; P(ud scores) 38–48% (down from ~52–53%); strong UD away xG within −0.15 of current; FRA/CRO, BEL/SEN, ESP/POR unchanged ±0.10 |
| **Fixtures** | 1–3 target; 4–8 guardrails; 9–12 neutral |
| **Tests** | `test_maher*` floor tests; audit script; no regression on Portugal/Croatia |
| **Rollback** | `ADAPTIVE_UNDERDOG_FLOOR_ENABLED=false`, `MAHER_FALLBACK_CONFIDENCE_WEIGHT=1.0` |
| **Commit** | **Single bundled commit** — do not split floor from Maher confidence |

### Stage 3 — Scoreline coherence guard

| Field | Detail |
|-------|--------|
| **Name** | Clean-sheet primary guard |
| **Goal** | Align primary scoreline with P(underdog scores) and BTTS |
| **Root causes** | #7 scoreline bias |
| **Files** | `scoreline_decision.py`, tests |
| **Implementation idea** | If primary is clean sheet and P(ud scores) ≥ 45% (or BTTS ≥ 40%): prefer highest-utility BTTS candidate within ε of primary utility, or demote CS with `low_confidence` flag. Do not change matrix. |
| **What not to touch** | xG, fusion, maher |
| **Acceptance criteria** | Fixtures 1–4: no CS primary when P(ud)≥45% unless raw CS prob leads by ≥8 pp; competitive fixtures primary unchanged |
| **Fixtures** | 1–4 primary; 5–12 regression |
| **Tests** | Scoreline unit tests with synthetic matrices |
| **Rollback** | `SCORELINE_CS_GUARD_ENABLED=false` |
| **Commit** | Separate after Stage 2 audit sign-off |

### Stage 4 — External and context cleanup

| Field | Detail |
|-------|--------|
| **Name** | Altitude, odds isolation, context guardrails |
| **Goal** | Remove confusing indirect effects |
| **Root causes** | #8, #9, #10, #11 partial |
| **Files** | `api/main.py`, `fusion_blowout.py`, mobile altitude prefs/display |
| **Implementation idea** | (a) When `odds_affect_prediction=false`, pass `market_odds=None` to fusion. (b) Mobile: reset stale 1500 on upgrade or show "manual override". (c) Document context ON behavior; optional cap on context xG delta magnitude. |
| **What not to touch** | Stage 1–3 math unless odds isolation changes fusion_t |
| **Acceptance criteria** | odds_affect=false → market_t=0 in diagnostics; altitude 1500 only when user sets; context OFF → city alone no xG change |
| **Fixtures** | ARG/CPV altitude probes; Houston context |
| **Tests** | Odds isolation test; mobile widget test |
| **Rollback** | Per-sub-flag |
| **Commit** | Backend and mobile may be separate commits |

### Stage 5 — Standard blowout OFF-path parity

| Field | Detail |
|-------|--------|
| **Name** | Standard blowout cap |
| **Goal** | Parity when `fusion_blowout_enabled=false` |
| **Root causes** | #12 |
| **Files** | `blowout.py`, tests |
| **Implementation idea** | Mirror Stage 1 uplift semantics on pre-matrix blowout |
| **What not to touch** | Fusion ON path |
| **Acceptance criteria** | Scenario D/E audit: Δ fav comparable to capped Scenario A |
| **Fixtures** | ARG/CPV, FRA/HAI in scenario D |
| **Tests** | `test_blowout*` |
| **Rollback** | Config flag |
| **Commit** | Separate, low priority |

---

## Fixture Acceptance Criteria

### Weak underdogs (1–3)

| Guardrail | Target |
|-----------|--------|
| Favorite remains clear | home_win (or fav side) ≥ 65% post-Stage 2 |
| Underdog base xG | ≤ 0.65 after Stage 2 (from ~0.80) |
| Fusion Δ fav | ≤ +1.05 after Stage 1 (from +1.8–1.9) |
| Final fav xG | ≤ 3.50 ARG/CPV; ≤ 3.30 FRA/HAI/CUR |
| P(underdog scores) | 38–48% after Stage 2 (from ~52–53%) |
| Primary scoreline | After Stage 3: not bare CS if P(ud)≥45%; BTTS-consistent line preferred |
| BTTS | May decrease modestly; not below 30% |

### Strong underdogs (4–8)

| Guardrail | Target |
|-----------|--------|
| Croatia / Senegal / Portugal | Away xG ≥ 0.75 where currently ≥0.83 (max −0.10 from Stage 2) |
| P(ud scores) | Remains ≥ 45% for POR/CRO, BEL/SEN, ESP/POR |
| Scoreline | BTTS-capable primary or alt when BTTS ≥ 45% |
| Fusion Δ fav | FRA/CRO ≤ +1.55; POR/CRO ≤ +0.30; no new blowout on ESP/POR |

### Competitive / reference (9–12)

| Guardrail | Target |
|-----------|--------|
| 1X2 probabilities | \|Δ\| ≤ 3 pp per outcome vs stable baseline |
| Total xG | \|Δ\| ≤ 0.15 |
| Fusion | t < 0.35 or inactive |
| Primary | Unchanged or ±1 goal only |

### City / context

| Setting | Expected |
|---------|----------|
| `use_match_context=false` | City change does not alter xG or primary |
| `use_match_context=true` | Effects bounded and logged; Houston-type swings explainable via weather_factor / xG delta |
| Altitude manual 1500 | Legacy xG unchanged; UI shows explicit manual mode |

---

## Measurement and Regression Plan

### Primary tool

```powershell
cd backend
py scripts/audit_stable_goliath_underdog_scoreline.py
py scripts/audit_stable_goliath_underdog_scoreline.py --quick
```

Save reports as `stable_goliath_underdog_scoreline_audit.{json,md}` (gitignored). Tag runs: `baseline_cff4c30`, `stage1_cap`, `stage2_foundation`, etc.

### Before/after table format

| Fixture | base xG | final xG | fusion Δ fav | dog P(score) | BTTS | primary | top BTTS candidate | flags |
|---------|---------|----------|--------------|--------------|------|---------|---------------------|-------|

### Metrics to extract (per fixture × scenario A)

- pre-fusion xG (from `fusion_blowout.xg_before` or diagnostics)
- post-fusion xG (`xg_after`)
- fusion Δ fav / Δ dog
- `blowout_t`, triggers, suppressed_by
- P(underdog scores), BTTS (Poisson from final xG or API field)
- primary, top 5 scorelines, raw modal if exposed
- clean-sheet probability of primary
- `gf_ga_source`, floor applied (add to audit if missing)
- attack/defense, power gap
- 1X2 raw vs final

### Proposed audit script enhancements (document only)

1. Column `floor_applied: bool` and `maher_gf_ga_source`.
2. Column `fusion_uplift_capped: bool` after Stage 1.
3. Export `top_btts_candidate` (best BTTS scoreline in top 5).
4. `--baseline-json` diff mode for CI-style regression.
5. Scenario filter `--scenario A` for fast CI.

### Regression gates

| Gate | Condition |
|------|-----------|
| G1 — Competitive safety | Fixtures 9–12: max \|Δ1X2\| ≤ 3 pp |
| G2 — Weak underdog relief | Fixtures 1–3: fusion Δ fav ≤ 1.05; dog P(score) ≤ 50% after Stage 2 |
| G3 — Strong underdog safety | Fixtures 4–8: away xG ≥ 0.75 |
| G4 — Scoreline coherence | After Stage 3: zero `CLEAN_SHEET_VS_HIGH_UD_SCORE_PROB` on 1–4 |
| G5 — Backend tests | `pytest` no new failures vs stable baseline (824 pass, 3 known) |

---

## Implementation Decision

### Answers to core questions

| # | Question | Answer |
|---|----------|--------|
| 1 | Start with Goliath cap only? | **Yes** |
| 2 | Cap together with adaptive floor? | **No** — separate stages |
| 3 | Scoreline guard wait until after xG fixes? | **Yes** — after Stage 2 |
| 4 | Maher fallback before or after adaptive floor? | **Same Stage 2 bundle** — floor logic must see confidence-adjusted Maher |
| 5 | Lowest risk / highest value? | **Stage 1 fusion favorite uplift cap** |
| 6 | Highest regression risk? | **Stage 2 attack/defense direct + floor + Maher** (triple interaction) |
| 7 | First implementation branch? | `fix/stable-fusion-favorite-uplift-cap` |

### Decision

**`IMPLEMENT_STAGE_1_ONLY`**

Foundation-first delays relief on the most visible bug (4.27 xG). Stage 1+2 together risks over-correction. Stage 1 delivers measurable, rollback-friendly improvement and clarifies remaining dog-xG inflation for Stage 2 tuning.

---

## First Recommended Implementation Prompt

Use this prompt on branch `fix/stable-fusion-favorite-uplift-cap` off `design/stable-prediction-unified-fix-strategy` (or `origin/main` after design merge):

```
Implement Stage 1 only from docs/STABLE_PREDICTION_UNIFIED_FIX_STRATEGY.md:

- Add FUSION_MAX_FAVORITE_UPLIFT config (default 1.00) in backend/config.py
- In apply_fusion_blowout(), after favorite uplift, clamp:
  fav_xg <= pre_fusion_fav_xg + FUSION_MAX_FAVORITE_UPLIFT
- Record uplift_capped in fusion diagnostics when clamp triggers
- Do NOT change dog_xg, Maher, floor, scoreline, mobile, standard blowout
- Add unit tests in test_fusion_blowout.py for cap at t=0.87 and t=0.13
- Run audit_stable_goliath_underdog_scoreline.py --quick before/after
- Verify fixtures 9-12: |Δ1X2| <= 3pp
- Commit: fix(prediction): cap fusion favorite xG uplift (stage 1)
- Do not push to main without approval
```

---

## Decision

**STABLE_PREDICTION_UNIFIED_FIX_STRATEGY_COMPLETE**

Design-only document. No production prediction code, mobile UI, Render, env, deploy, or push to `main` in this task.
