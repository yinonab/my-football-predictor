# Staging Model Activation Runbook (Phase 3F)

This runbook covers **local and staging** enablement of the FIFA-points external anchor candidate. It does **not** approve production activation.

---

## 1. Current status

| Item | Value |
|------|--------|
| Release readiness (Phase 3E) | `READY_FOR_STAGING_ENABLEMENT` |
| Active candidate model version | `v2.2.0-fifa-points-anchor` |
| Baseline model version | `v2.1.3-baseline` |
| Active power candidate | `effective_external_current_formula` |
| External rating mode | `fifa_points_snapshot` |
| External rating strategy | `fifa_points_confidence_weighted` |
| Production FIFA snapshot | `wc2026_current` (48/48 teams) |
| `MODEL_ACTIVATION_ENABLED` (repo default) | `false` |
| `POWER_CANDIDATE_AFFECTS_PREDICTION` (repo default) | `false` |

Production `/api/predict` behavior is unchanged until both activation flags are set via **environment variables** on the running process (local or staging only).

---

## 2. Pre-enable checks

Run from the `backend` directory. All checks should pass before enabling on staging.

```powershell
cd backend

python -m pytest tests/ -q
python scripts/check_activation_readiness.py
python scripts/activation_qa_report.py --only-large-shifts
python scripts/smoke_local_activation_enabled.py
python scripts/smoke_activation_rollback.py
python scripts/release_readiness_report.py --markdown reports/release_readiness_report.md
```

**Expected:**

- Tests: all pass
- Readiness: `READY_WITH_WARNINGS` or `READY_FOR_LOCAL_ENABLEMENT` (approximate production snapshot `as_of` is acceptable)
- QA large shifts: Germany vs Haiti reviewed / explainable
- Enabled smoke: `PASS` (8 sample production matchups, no fallback)
- Rollback smoke: `PASS`
- Release report status: `READY_FOR_STAGING_ENABLEMENT`

---

## 3. Local / staging enable

Set environment variables **before starting** the API process. Do not change `config.py` defaults in the repo.

### PowerShell

```powershell
$env:MODEL_ACTIVATION_ENABLED="true"
$env:POWER_CANDIDATE_AFFECTS_PREDICTION="true"

# Start API (example)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Bash

```bash
export MODEL_ACTIVATION_ENABLED=true
export POWER_CANDIDATE_AFFECTS_PREDICTION=true

# Start API (example)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Both flags must be `true` for the candidate to affect `/api/predict`.

---

## 4. Verify after enable

### API smoke (curl or TestClient)

```powershell
curl -s -X POST http://127.0.0.1:8000/api/predict `
  -H "Content-Type: application/json" `
  -d '{"home_team":"Germany","away_team":"Haiti","neutral_ground":true}'
```

Or use the bundled smoke script (simulates flags without a running server):

```powershell
python scripts/smoke_local_activation_enabled.py
```

**Check `model_diagnostics` and response body:**

| Check | Expected |
|-------|----------|
| `model_diagnostics.model_version` | `v2.2.0-fifa-points-anchor` |
| `model_diagnostics.activation_enabled` | `true` |
| `model_diagnostics.fallback_to_baseline` | `false` |
| `model_diagnostics.active_candidate` | `effective_external_current_formula` |
| `probabilities_1x2` sum | ~100 (within 0.5pp) |
| `top_scores` | non-empty list |
| `home_xg`, `away_xg` | present |

### Expected sample behavior (vs baseline)

Compare disabled vs enabled on the same host (toggle env vars and restart):

| Matchup | Expected when enabled |
|---------|------------------------|
| Germany vs Haiti | Stronger Germany favorite (higher home win %, wider power/xG gap) |
| Argentina vs France | Stable (small delta, balanced top teams) |

Dry-run reference:

```powershell
python scripts/activation_dry_run.py --enable-candidate --sample-production
```

---

## 5. Rollback

Disable immediately by clearing or setting both flags, then **restart the API process**.

### PowerShell

```powershell
$env:MODEL_ACTIVATION_ENABLED="false"
$env:POWER_CANDIDATE_AFFECTS_PREDICTION="false"
```

### Bash

```bash
unset MODEL_ACTIVATION_ENABLED
unset POWER_CANDIDATE_AFFECTS_PREDICTION
# or explicitly:
export MODEL_ACTIVATION_ENABLED=false
export POWER_CANDIDATE_AFFECTS_PREDICTION=false
```

There is no persisted activation state in the repo; rollback is config/env only.

---

## 6. Post-rollback verify

```powershell
cd backend
python scripts/smoke_activation_rollback.py
```

**Live API check** (after restart with flags false):

```powershell
curl -s -X POST http://127.0.0.1:8000/api/predict `
  -H "Content-Type: application/json" `
  -d '{"home_team":"Brazil","away_team":"Morocco","neutral_ground":true}'
```

Confirm:

- `model_diagnostics.model_version` = `v2.1.3-baseline`
- `model_diagnostics.activation_enabled` = `false`
- Predictions match pre-enablement baseline behavior

---

## 7. Production note

**This runbook does not approve production activation.**

Production enablement requires separate:

- Explicit stakeholder approval
- Commit / deploy plan with reviewed config and env vars
- Documented rollback plan and monitoring
- Post-deploy verification on production traffic or canary

Until then, keep repo defaults and production deployment flags **disabled**.

---

## Related docs and scripts

| Resource | Purpose |
|----------|---------|
| `scripts/check_activation_readiness.py` | Production FIFA coverage + QA gates |
| `scripts/local_enablement_checklist.py` | Local enablement recommendation |
| `scripts/explain_activation_shift.py` | Large-shift explanation (e.g. Germany vs Haiti) |
| `scripts/review_large_activation_shifts.py` | Auto-review QA large shifts |
| `data/activation_large_shift_reviews.json` | Recorded shift review status |
| `reports/release_readiness_report.md` | Latest Phase 3E aggregate report |

See also README sections: Phase 3A–3E.
