# Data Parity — Audit Baseline Modes

Calibration audits (cap, scoreline, elite matchups) should compare **local vs production** on the same team Elo baseline. Local dev machines often have `backend/data/cache/elo_overrides.json` (gitignored) from past `POST /api/elo-update` runs. Production typically uses **FIFA registry Elo** when Gist has no overrides.

## Modes

| Mode | `AUDIT_ELO_BASELINE` | `load_elo_overrides()` | Use when |
|------|----------------------|--------------------------|----------|
| **local-with-overrides** | unset (default runtime) | Reads `elo_overrides.json` if present | Normal API/dev; post-match Elo patches |
| **production-parity** | `production` or `fifa` | Returns `{}` — FIFA baseline only | Calibration audits, local↔prod comparison |

Production-parity does **not** delete or modify `elo_overrides.json`; it only skips loading it in processes that set the env flag.

## Why production-parity for calibration

Stale local overrides (e.g. Haiti `1626.7` vs FIFA `1265`, Curacao `908.3` vs FIFA `1270`) change power, xG, and primary scorelines. Audits without parity mode report false local/prod gaps.

## Do not push local overrides to production

`save_elo_overrides()` can push to GitHub Gist when `GITHUB_GIST_TOKEN` is set. Local override files are **not** verified production policy. Do not sync them to Gist or Render without explicit review and approval.

## Scripts using production-parity by default

These set `AUDIT_ELO_BASELINE=production` before importing the API:

- `backend/scripts/audit_hybrid_underdog_cap.py`
- `backend/scripts/audit_scoreline_realism.py`
- `backend/scripts/audit_scoreline_decision.py`

Other `backend/scripts/audit_*.py` files still run **local-with-overrides** until updated. Set the env var manually when running those for parity.

## Example (PowerShell)

```powershell
cd backend
$env:PYTHONIOENCODING = "utf-8"
$env:AUDIT_ELO_BASELINE = "production"
$env:NR3_FCC_SERVED_ENABLED = "true"
$env:ACTIVE_MODEL_WEAK_UNDERDOG_CAP_ENABLED = "true"
py scripts/audit_hybrid_underdog_cap.py
```

Calibration scripts above already default to production-parity; the explicit `$env:AUDIT_ELO_BASELINE` is optional but documents intent.

## Implementation

`core.elo_store.load_elo_overrides()` checks `AUDIT_ELO_BASELINE`. Normal `uvicorn` / production startup is unchanged when the flag is absent.
