# Stable Goliath / Underdog / Scoreline Diagnosis

**Stable commit:** `cff4c30c366980e75ad82f18fa96bfd0984c95f5`  
**Branch:** `diagnosis/stable-goliath-underdog-scoreline`  
**Mode:** Read-only diagnosis — no prediction math changes  
**Audit script:** `backend/scripts/audit_stable_goliath_underdog_scoreline.py`  
**Generated reports (local):** `backend/reports/stable_goliath_underdog_scoreline_audit.{json,md}`

---

## Current Stable Pipeline Map

| Step | Component | File | Served? | Notes |
|------|-----------|------|---------|-------|
| 1 | Team resolution | `data/live_data_manager.py` | Active | Alias → canonical name |
| 2 | Ratings / GF-GA / attack-defense | `core/team_ratings.py`, `data/database.py` | Active | Elo-derived attack/defense; history GF/GA |
| 3 | Power | `core/team_power.py` | Active | Composite power + optional altitude on **power** (legacy) |
| 4 | Maher xG | `core/maher.py`, `core/opponent_maher.py` | Active | GF/GA rates; zero history → `global_avg/2` fallback |
| 5 | Power blend | `maher.blend_maher_with_power` | Active | Maher weight 0.12–0.80 by gap |
| 6 | Underdog floor | `maher.floor_underdog_xg` | Active | gap>200 → min ~0.8 xG for underdog |
| 7 | Context | `core/context_adjustments.py` | Optional | `use_match_context` → xG delta + power mults |
| 8 | Altitude | `core/venue_environment.py` | Partial | Legacy: **power penalty only** if altitude>1200; NR3 served path has xG penalty (off by default) |
| 9 | Blowout branch | `api/main.py:575–594` | Active | Fusion ON → skip standard blowout pre-matrix |
| 10 | Dixon–Coles matrix | `core/math_engine.py` | Active | First matrix at pre-fusion xG |
| 11 | 1X2 pipeline | `core/probability_pipeline.py` | Active | Calibration; odds blend if enabled |
| 12 | **Goliath/Fusion** | `core/fusion_blowout.py` | If `fusion_blowout_enabled` | Post-matrix signal + xG uplift + matrix regen |
| 13 | Standard blowout | `core/blowout.py` | If fusion OFF | Pre-matrix gap-based uplift |
| 14 | Scoreline | `core/scoreline_decision.py` | Active | Representative utility; clean-sheet gate |
| 15 | Underdog narrative | `mobile/underdog_scoring_narrative.dart` | Display | UI only |

**NR3 FCC served** (`NR3_FCC_SERVED_ENABLED`) is **off** in default stable deploy → audit reflects **legacy Maher→power→fusion** path.

---

## Goliath/Fusion ON Over-Amplification

**Classification: CONFIRMED**

### Formula (`fusion_blowout.py`)

```
margin_t = clamp((margin_pp - 20) / 55)
market_t = clamp((m_prob - fav_prob) / 25)  # if market agrees
power_t  = clamp(|power_gap| / 220) × 0.45
blowout_t = clamp((0.58×margin_t + 0.27×market_t + power_t) × weather_factor)
if fav_prob < 58: blowout_t ×= 0.5
Active if blowout_t >= 0.08
```

**Uplift when active:**
```
fav_target = 2.75 + t × 2.05
fav_xg += t × max(0, fav_target - fav_xg)
dog_floor = 0.45 + 0.35×t
dog_xg = max(dog_floor, dog_xg × (1 - 0.12×t))
```

**No hard cap** on favorite final xG beyond implicit `fav_target` interpolation.

### Argentina vs Cape Verde (Scenario A: Goliath ON, fusion off odds, alt 0)

| Stage | Home (ARG) | Away (CPV) |
|-------|------------|------------|
| Maher raw | 1.30 | 1.30 |
| After blend + floor (base) | 2.37 | 0.80 |
| Pre-fusion (matrix input) | 2.37 | 0.80 |
| Post-fusion (final) | **4.27** | **0.76** |
| Δ favorite | **+1.90** | — |

- **t ≈ 0.87** — triggers: `BLENDED_MARGIN_WIDE`, `STRONG_FAVORITE_PROB`, `POWER_GAP_ELEVATED`
- **Primary:** 4-0 | **P(CPV scores):** 53% | **BTTS:** ~45%
- **Flags:** `CLEAN_SHEET_VS_HIGH_UD_SCORE_PROB`, `BTTS_ELEVATED_BUT_CLEAN_SHEET_PRIMARY`

User-reported jumps (1.74→2.85, 1.92→3.54) are **directionally consistent**; exact pre-fusion values depend on blend/floor state. Audit shows **2.37→4.27** on current stable data.

### Comparison Goliath OFF vs ON (Argentina vs Cape Verde)

| Mode | Final xG | Primary |
|------|----------|---------|
| Goliath OFF (standard blowout) | 4.40 / 0.95 | 4-0 |
| Goliath ON (fusion) | 4.27 / 0.76 | 4-0 |

Both paths produce **blowout-level** favorite xG. Fusion is not the only amplifier — **standard blowout** when OFF is also aggressive on this fixture.

---

## Fixture Summaries (Scenario A — Goliath ON)

| Fixture | Base xG | Final xG | t | Δ fav | Primary | P(ud scores) | Flags |
|---------|---------|----------|---|-------|---------|--------------|-------|
| Argentina vs Cape Verde | 2.37/0.80 | 4.27/0.76 | 0.87 | +1.90 | 4-0 | 53% | CS+BTTS |
| France vs Haiti | 2.00/0.80 | 3.80/0.73 | 0.77 | +1.80 | 4-0 | 52% | CS+BTTS |
| France vs Curaçao | 2.22/0.80 | 4.10/0.74 | 0.84 | +1.88 | 4-0 | 52% | CS+BTTS |
| France vs Croatia | 1.92/0.68 | 3.40/0.68 | 0.67 | +1.48 | 3-0 | 49% | CS |
| Portugal vs Croatia | 1.62/0.98 | 1.81/0.96 | 0.13 | +0.19 | 2-0 | 62% | CS+BTTS |
| Belgium vs Senegal | 1.77/0.83 | 2.42/0.79 | 0.37 | +0.65 | 2-0 | 55% | CS+BTTS |

---

## Weak Underdog xG Inflation

**Classification: CONFIRMED (pre-Goliath floor + Maher fallback); PARTIALLY CONFIRMED (post-Goliath)**

### Weak underdogs (attack ≤ 0.33, GF/GA fallback)

| Fixture | Away attack | GF/GA | Maher away | Base away xG | Final away xG | P(score) |
|---------|-------------|-------|------------|--------------|---------------|----------|
| France vs Haiti | 0.10 | fallback | 1.30 | **0.80** | 0.73 | 52% |
| France vs Curaçao | 0.33 | fallback | 1.30 | **0.80** | 0.74 | 52% |
| Argentina vs Cape Verde | 0.10 | fallback | 1.30 | **0.80** | 0.76 | 53% |

### Strong underdogs (attack ≥ 0.52)

| Fixture | Away attack | Base away xG | Final away xG | P(score) |
|---------|-------------|--------------|---------------|----------|
| France vs Croatia | 0.67 | 0.68 | 0.68 | 49% |
| Portugal vs Croatia | 0.67 | 0.98 | 0.96 | 62% |
| Belgium vs Senegal | 0.62 | 0.83 | 0.79 | 55% |
| Spain vs Austria | 0.52 | 0.78 | 0.73 | 54% |
| Spain vs Portugal | 0.74 | 1.15 | 1.15 | 68% |

**Findings:**
1. `floor_underdog_xg` enforces **~0.8 minimum** away xG when power gap > 200 — affects Haiti/Curaçao/Cape Verde equally before Goliath.
2. Maher with **zero GF/GA** → symmetric **1.30/1.30** for all teams in audit (half of 2.6).
3. Strong underdogs retain higher base away xG (0.68–1.15) but weak underdogs are **floored**, not suppressed by attack rating in legacy path.
4. Goliath **slightly reduces** underdog xG via `dog_xg × (1 - 0.12×t)` but `dog_floor` prevents collapse.

---

## Attack/Defense Signal Usage

**Classification: PARTIALLY CONFIRMED — indirect only on legacy served path**

| Signal | In legacy served xG? | How |
|--------|-------------------|-----|
| `attack` / `defense` ratings | **Indirect** | Feed `team_power` composite only |
| GF/GA per game | **Direct** | Maher `estimate_xg_pair` |
| Opponent-aware Maher | **Direct** | H2H blend when matches exist |
| Strength-based xG | **No** | Only when `NR3_FCC_SERVED_ENABLED=true` |

Goliath/Fusion uses **blended 1X2 + power_gap** — does **not** read attack/defense directly.

Weak attack (Haiti 0.10) does **not** reduce Maher below fallback half; floor then sets 0.8 away xG.

---

## Maher and GF-GA Fallback Analysis

**Classification: CONFIRMED flattening**

- Missing/zero GF/GA → Maher uses `global_avg/2 = 1.30` per team (`maher.py:21–27`).
- Audit: **all 12 fixtures** show `away_gf_ga_source=fallback_zero` for weak teams; Maher pair **1.30/1.30** before blend.
- Croatia/Senegal/Portugal share same Maher fallback when GF/GA absent — differentiation comes from **power blend** and **floor**, not Maher alone.
- Opponent-aware index may help when H2H exists; not sufficient for Haiti/Cape Verde in audit.

---

## Scoreline Clean-Sheet Bias

**Classification: CONFIRMED**

Mechanisms (`scoreline_decision.py`):
- Representative picker favors favorite goal target `floor(xg+0.5)` on clear favorites.
- `gate_candidate_adjustment` can **boost** clean-sheet lines (+0.04 utility).
- `_realism_penalty` exists but warnings (`PRIMARY_CLEAN_SHEET_WITH_UNDERDOG_XG_HIGH`) are **display-only**.

**Argentina vs Cape Verde:** Primary **4-0** with P(CPV scores) **53%**. Representative method, not raw modal scoreline. BTTS alternatives (3-1, 4-1) penalized vs clean sheet in utility.

**Goliath does not** check underdog scoring probability before scoreline selection.

---

## Altitude 1500m Investigation

**Classification: PARTIALLY CONFIRMED — manual 1500 stored but legacy xG unchanged**

| Probe | Input alt | Resolved | Final ARG/CPV xG |
|-------|-----------|----------|------------------|
| manual_0 | 0 | — | 4.27/0.76 |
| manual_1500 | 1500 | 1500 | 4.27/0.76 |
| auto Houston | 0 + auto | 15 | 4.27/0.76 |
| auto Miami | 0 + auto | 3 | 4.27/0.76 |

- **Backend default:** `altitude=0`, `auto_stadium_altitude=True` (`schemas.py`).
- **Mobile default:** `altitude: 0`, `autoStadiumAltitude: true` — user may persist **1500** in SharedPreferences.
- Legacy path: altitude affects **power** via `team_power.apply_environmental_modifiers`, **not** direct xG penalty.
- **1500 appearing in UI** is likely **persisted manual setting** or user toggle, not backend default.

---

## City and Venue Sensitivity

**Classification: CONFIRMED when `use_match_context=true`**

Argentina vs Cape Verde, Goliath ON:

| City | Context OFF | Context ON (final xG) | Primary |
|------|-------------|----------------------|---------|
| (none) | 4.27/0.76 | 4.27/0.76 | 4-0 |
| Houston | 4.27/0.76 | **2.89/0.69** | **3-0** |
| Miami | 4.27/0.76 | 4.27/0.76 | 4-0 |

Houston + context ON materially reduces xG and Goliath intensity (weather/travel). City alone without context: **no change** in audit.

---

## External Data and Fallback Effects

**Classification: PARTIALLY CONFIRMED**

| Source | `odds_affect_prediction=false` | Effect on Goliath |
|--------|-------------------------------|-------------------|
| Odds market | Skips 1X2 blend | Market still read; `market_t` in fusion signal if odds present |
| API-Football fixture | Lookup fails (suspended in logs) | Context falls back; no xG change if `use_match_context=false` |
| GF/GA history | N/A | Zero → Maher half fallback |

---

## Root Cause Classification

| # | Root cause | Status |
|---|------------|--------|
| 1 | Goliath/Fusion over-amplification | **Confirmed** |
| 2 | Weak-underdog xG inflation before Goliath | **Confirmed** (`floor_underdog_xg` + Maher fallback) |
| 3 | Weak-underdog inflation after Goliath | **Partially confirmed** (floor offsets reduction) |
| 4 | Weak vs strong underdog differentiation | **Partially confirmed** (power blend helps; floor hurts weak) |
| 5 | Attack/defense inactive in legacy xG | **Confirmed** (power only) |
| 6 | Maher/GF-GA fallback flattening | **Confirmed** |
| 7 | Scoreline clean-sheet bias | **Confirmed** |
| 8 | Altitude 1500 stale/default | **Partially confirmed** (persisted/manual; legacy xG insensitive) |
| 9 | City/context sensitivity | **Confirmed** (with context ON) |
| 10 | Odds/market indirect on fusion t | **Partially confirmed** (market_t when odds fetched) |
| 11 | API-Football/context fallback | **Partially confirmed** (diagnostics only when context off) |
| 12 | Standard Blowout when Goliath OFF | **Confirmed** (also aggressive; lower priority) |

---

## Recommended Fix Strategy (do not implement here)

| Priority | Fix | Benefit | Risk | Files |
|----------|-----|---------|------|-------|
| 1 | Cap `blowout_t` or max Δfav xG (e.g. +1.0) | Stops 2.4→4.3 jumps | May understate true mismatches | `fusion_blowout.py` |
| 2 | Adaptive `floor_underdog_xg` by attack rating | Lowers Haiti/CPV floor | May over-suppress mid underdogs | `maher.py` |
| 3 | Reduce Maher trust when GF/GA fallback | Less 1.30 symmetry | Needs confidence flag | `maher.py`, `opponent_maher.py` |
| 4 | Scoreline guard: no CS primary if P(ud)≥45% | UX coherence | Changes primary only | `scoreline_decision.py` |
| 5 | Fusion considers underdog P(score) before uplift | Coherent blowout | More complex signal | `fusion_blowout.py` |
| 6 | Wire attack/defense into Maher blend (legacy) | Better weak/strong split | Production xG change | `maher.py`, `main.py` |
| 7 | Altitude: reset mobile default / show resolved alt | Fixes 1500 confusion | UX only | `mobile/` |
| 8 | Standard blowout cap (Goliath OFF path) | Parity when toggle off | Lower priority | `blowout.py` |

Each fix needs: fixture backtest (12 audit fixtures), NR3 parity if served enabled, rollback via config flag.

---

## How to Reproduce

```powershell
cd backend
py scripts/audit_stable_goliath_underdog_scoreline.py
# Optional faster run (skips city matrix):
py scripts/audit_stable_goliath_underdog_scoreline.py --quick
```

---

## Decision

**STABLE_GOLIATH_UNDERDOG_SCORELINE_DIAGNOSIS_COMPLETE**

No prediction code, mobile UI, Render, or env vars were changed. Reports are generated locally and gitignored.
