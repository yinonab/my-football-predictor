# Hybrid Tier + Continuous Weak Underdog Cap

**Branch:** `fix/hybrid-underdog-tier-continuous-cap`  
**Model:** `v2.3.0-nr3-fcc-served`  
**Scope:** Post-fusion underdog xG cap only — scoreline picker untouched.

## What changed

Replaced the single-band weak-underdog cap (attack ≤ 0.40, gap > 200, cap 0.55–0.65) with **hybrid tier + continuous cap**:

| Tier | Attack | Gap floor | Cap band |
|------|--------|-----------|----------|
| ultra_weak | ≤ 0.15 | > 150 | **0.35–0.52** |
| medium_weak | 0.16–0.40 | > 180 | 0.55–0.70 |
| strong | > 0.40 | — | no cap |

Within each tier, cap scales continuously with attack (weaker → lower cap). Additional tightening:

- Favorite defense (continuous above baseline 0.55)
- GF/GA fallback penalty (−0.03)
- Ultra-tier gap penalty for very large mismatches
- Attack source: `min(raw, history)` when sources conflict by ≥ 0.15, or when GF/GA is fallback

**Wired:** `home_gf_ga_fallback` / `away_gf_ga_fallback` and raw database attack into NR3 served cap path.

## Why ultra band is lower than diagnosis draft (0.50–0.58)

User feedback: Haiti / Cape Verde vs elite favorites should score **less** than the prior ~0.57–0.58 xG (~43–44% P(score)). The new ultra band **0.35–0.52** targets ~33–40% P(score) while keeping primaries at 2-0 / 3-0 (no 5-0 runaway).

## Before / after fixture matrix

Settings: NR3 served, Goliath on, neutral, no context/altitude.  
**Before** = `origin/main` @ 9132ca4 (diagnosis audit). **After** = this branch.

### Ultra-weak

| Fixture | | ud xG | P(sc) | Primary | Cap |
|---------|---|-------|-------|---------|-----|
| France vs Haiti | Before | 0.57 | 43.5% | 2-0 | yes |
| | **After** | **0.41** | **33.6%** | 2-0 | yes |
| Argentina vs Cape Verde | Before | 0.58 | 44.0% | 3-0 | yes |
| | **After** | **0.45** | **36.2%** | 3-0 | yes |

### Medium-weak

| Fixture | | ud xG | P(sc) | Primary | Tier | Cap |
|---------|---|-------|-------|---------|------|-----|
| France vs Curaçao | Before | 0.63 | 46.7% | 3-0 | — | yes |
| | **After** | **0.61** | **45.7%** | 3-0 | medium_weak | yes |
| France vs Paraguay | Before | 0.62 | 46.2% | 3-0 | — | yes |
| | **After** | **0.61** | **45.7%** | 3-0 | medium_weak | yes |
| England vs DR Congo | Before | 0.67 | 48.8% | 3-0 | — | no |
| | **After** | 0.67 | 48.8% | 3-0 | medium_weak | no (gap 120 < 180) |

### Strong (unchanged)

| Fixture | ud xG | P(sc) | Cap |
|---------|-------|-------|-----|
| France vs Croatia | 0.65 | 47.8% | no |
| Spain vs Portugal | 0.80 | 55.1% | no |
| Belgium vs Senegal | 0.71 | 50.8% | no |
| Spain vs Austria | 0.65 | 47.8% | no |

## Risks

| Risk | Status |
|------|--------|
| Reintroduce 5-0 / 4-0 for ultra-weak | Not observed — primaries stay 2-0 / 3-0 |
| Weak P(sc) > 50% | Ultra-weak now ~34–36%; medium ~46% |
| Over-suppress Paraguay/Curaçao | Mild cap only; 0.61 vs Haiti 0.41 |
| Hurt Croatia/Portugal/Senegal | No change |
| DR Congo still high | Gap 120 < medium floor 180; tier now medium_weak in diagnostics |

## Rollback

Set `ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED=false` or revert to legacy single-band env vars (`MAX_XG_LOW/HIGH`, `POWER_GAP_THRESHOLD=200`).

Tier tuning via env:

- `ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA_CAP_MIN/MAX`
- `ACTIVE_MODEL_WEAK_UNDERDOG_MEDIUM_CAP_MIN/MAX`
- `ACTIVE_MODEL_WEAK_UNDERDOG_ULTRA/MEDIUM_POWER_GAP_THRESHOLD`

## Scoreline picker

**Not modified.** xG changes flow into the existing Dixon-Coles matrix and scoreline decision unchanged.

## Reproduce audit

```powershell
cd backend
$env:NR3_FCC_SERVED_ENABLED="true"
py scripts/audit_hybrid_underdog_cap.py
```

Output: `backend/reports/hybrid_underdog_cap_audit.json`
