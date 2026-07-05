# Hybrid / Four-Level Underdog xG Cap

**Branch:** `fix/hybrid-underdog-tier-continuous-cap`  
**Model:** `v2.3.0-nr3-fcc-served`  
**Scope:** Post-fusion underdog xG cap only.

## Why 3 tiers were not enough

The first hybrid implementation (commit `440c267`) used **ultra_weak / medium_weak / strong**. It fixed Haiti and Cape Verde but left a coarse ladder:

| Team | 3-tier ud xG | Issue |
|------|--------------|-------|
| Haiti | 0.41 | Good |
| Cape Verde | 0.45 | Good |
| Curaçao | 0.61 | Only −0.02 vs old |
| Paraguay | 0.61 | Same as Curaçao |
| DR Congo | 0.67 | Uncapped (gap / attack source) |

Large jump ultra → medium; no **weak** step between ultra and medium.

## Four-level design (data-driven, not by country name)

Tier is chosen from **`attack_used`** + matchup gap. Country names are validation examples only.

| Level | attack_used | Gap floor | Cap band | Cap? |
|-------|-------------|-----------|----------|------|
| **ultra_weak** | ≤ 0.15 | > 130 | 0.35–0.52 | yes |
| **weak** | 0.16–0.30 | > 115 | 0.48–0.62 | yes |
| **medium_underdog** | 0.31–0.50 | > 200 | 0.60–0.75 | yes |
| **strong_underdog** | > 0.50 | — | none | no |

**Gap floors rationale:**
- Ultra 130: large mismatches only; avoids competitive pairs.
- Weak **115**: explicitly enables DR Congo (gap ~120) when `attack_used` resolves to weak (0.27).
- Medium **200**: mild cap only for large favorites vs medium sides (France–Paraguay/Curaçao).

**Attack source rule:**
- If `|raw − history| ≥ 0.15` **or** `gf_ga_fallback` → use `min(raw, history)` (`min_source_conflict` / `min_conservative`).
- Diagnostics: `attack_used`, `raw_attack`, `history_attack`, `attack_source`, `attack_source_conflict`.

**Monotonicity:** Cap band ordering guarantees `ultra_max < weak_max < medium_max` at the formula level. Small final-xG overlap can occur when pre-cap NR3 xG differs (cap is a maximum, never raises).

**Tier boundary cliffs:** Documented at 0.15 / 0.30 / 0.50 — tests cover boundaries.

## DR Congo decision

| Signal | Value |
|--------|-------|
| raw_attack | 0.27 |
| history_attack | 0.58 |
| attack_used | **0.27** (conflict → conservative min) |
| tier | **weak** |
| gap | 119.7 > weak floor **115** |
| **Decision** | **Capped** as weak underdog (~0.59 ud xG) |

Previously (3-tier): tier `medium_weak` label but **uncapped** (gap < 180). Now explicitly weak + capped.

## Before / current / amended tables

Settings: NR3 served, Goliath on, neutral, no context.

### Ultra

| Fixture | A origin | B 3-tier | C 4-level |
|---------|----------|----------|-----------|
| France vs Haiti ud xG | 0.57 | 0.41 | **0.41** |
| Haiti P(sc) | 41.9% | 32.7% | **32.7%** |
| Haiti primary | 2-0 | 2-0 | **2-0** |
| Argentina vs Cape Verde ud xG | 0.58 | 0.45 | **0.45** |
| Cape Verde P(sc) | 41.6% | 34.5% | **34.5%** |
| Cape Verde primary | 3-0 | 3-0 | **3-0** |

### Weak / medium

| Fixture | A | B 3-tier | C 4-level | Tier (C) |
|---------|---|----------|-----------|----------|
| DR Congo ud xG | 0.67 | 0.67 | **0.59** | weak |
| Curaçao ud xG | 0.63 | 0.61 | **0.58** | medium_underdog |
| Paraguay ud xG | 0.62 | 0.61 | **0.57** | weak* |

\*Paraguay `attack_used=0.28` (conservative min vs raw 0.33) → weak tier; still above Haiti/Cape Verde.

### Strong (unchanged)

| Fixture | ud xG (all) | Cap |
|---------|-------------|-----|
| Croatia | 0.65 | no |
| Portugal | 0.80 | no |
| Senegal | 0.71 | no |
| Austria | 0.65 | no |

**Favorite xG:** unchanged across A/B/C for all audited fixtures.

**Exact scoreline:** no primary changes vs B; vs A only xG-driven tail shifts (no primary 4-0/5-0).

## Risks

| Risk | Mitigation |
|------|------------|
| Tier boundary cliffs | Tests at 0.15/0.30/0.50 |
| DR Congo over/under | Documented weak + gap 115 rule |
| Paraguay as weak not medium | Data-driven from attack_used 0.28 |
| 4-0 tail in top-5 | No primary 4-0/5-0 |

## Rollback

- `ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED=false`
- Or revert branch commits

## Scoreline picker

**Not modified.** Only underdog xG cap after fusion.

## Audit

```powershell
cd backend
$env:NR3_FCC_SERVED_ENABLED="true"
py scripts/audit_hybrid_underdog_cap.py
```

Output: `backend/reports/four_level_cap_audit_<sha>.json`
