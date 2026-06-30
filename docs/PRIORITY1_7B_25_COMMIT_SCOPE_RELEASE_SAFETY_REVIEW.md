# Priority 1.7B.25 — Commit Scope and Release Safety Review

## 1. Executive summary

**Review-only. No commit. No deploy. No activation.**

- Review status: **REVIEW_COMPLETE**
- Workspace dirty: **True**
- Commit recommended now: **False**
- Commit readiness: **MANUAL_HUNK_SELECTION_REQUIRED**

Do not activate. Do not deploy. Do not commit yet unless manual hunk selection is approved. P1.7B.23/P1.7B.24 code is safe in isolation; workspace hygiene requires git add -p on priority1_options.py and priority1_backtest.py before any commit.

## 2. Review-only scope

- No git add/commit/reset/restore/clean/stash
- No production file edits
- No activation or deploy

## 3. Current git state

- Tracked modified: **12** files
- Untracked: **182** files

## 4. P1.7B.23 safety summary

- Activation blocked: **True**
- Flag default false: **False**

## 5. P1.7B.24 verification summary

- Verification: **VERIFICATION_COMPLETE**
- API leak: **False**

## 6. File classification

See JSON `file_classifications` for full table.

## 7. Mixed hunk review

- Manual hunk selection required: **True**
- Hunk separation possible: **True**

## 8. Proposed commit strategy

Three-phase commit plan when user explicitly approves: Commit A (P1.7B.23 shadow wiring with manual hunk selection), Commit B (P1.7B.24 verification), Commit C (P1.7B.25 this review). Never include Commit E (production-path) or git add . Commit D (research artifacts) optional and separate.

## 9. Proposed commit groups

- **Commit A** — Shadow wiring implementation (P1.7B.23): include_now=False, risk=medium
- **Commit B** — Shadow wiring verification (P1.7B.24): include_now=False, risk=low
- **Commit C** — Commit scope review (P1.7B.25): include_now=False, risk=low
- **Commit D** — Prior P1.7B research artifacts (P1.7B.11–P1.7B.22): include_now=False, risk=medium
- **Commit E** — Pre-existing production-path work: include_now=False, risk=critical

## 10. Files safe for commit review

- `backend/core/commit_scope_release_safety_review.py`
- `backend/core/disabled_shadow_wiring_runtime.py`
- `backend/core/shadow_wiring_verification_diff_review.py`
- `backend/scripts/run_priority1_7b_23_disabled_shadow_wiring_implementation.py`
- `backend/scripts/run_priority1_7b_24_shadow_wiring_verification_diff_review.py`
- `backend/scripts/run_priority1_7b_25_commit_scope_release_safety_review.py`
- `backend/tests/test_commit_scope_release_safety_review.py`
- `backend/tests/test_disabled_shadow_wiring_runtime.py`
- `backend/tests/test_shadow_wiring_verification_diff_review.py`
- `docs/PRIORITY1_7B_23_DISABLED_SHADOW_WIRING_IMPLEMENTATION.md`
- `docs/PRIORITY1_7B_24_SHADOW_WIRING_VERIFICATION_DIFF_REVIEW.md`
- `docs/PRIORITY1_7B_25_COMMIT_SCOPE_RELEASE_SAFETY_REVIEW.md`

## 11. Files requiring manual review

- `backend/core/priority1_backtest.py`
- `backend/core/priority1_options.py`
- `backend/core/activation_readiness_gate_context_audit.py`
- `backend/core/conditional_spread_governance.py`
- `backend/core/controlled_activation_plan_draft.py`
- `backend/core/disabled_shadow_wiring_design.py`
- `backend/core/dual_regime_favorite_confidence_governance.py`
- `backend/core/dynamic_goals_bounded.py`
- `backend/core/dynamic_goals_v3.py`
- `backend/core/dynamic_goals_v3_gates.py`
- `backend/core/dynamic_goals_v3_rolling.py`
- `backend/core/favorite_confidence_curve_audit.py`
- `backend/core/favorite_confidence_curve_prototype.py`
- `backend/core/favorite_direction_root_cause_audit.py`
- `backend/core/favorite_direction_safety_gate.py`
- `backend/core/favorite_direction_safety_gate_validation.py`
- `backend/core/favorite_spread_too_small_decomposition.py`
- `backend/core/favorite_trust_calibration.py`
- `backend/core/favorite_trust_validation.py`
- `backend/core/final_activation_readiness_audit.py`

## 12. Files excluded from commit

- `backend/.env.example`
- `backend/api/main.py`
- `backend/api/schemas.py`
- `backend/config.py`
- `backend/core/market_xg_calibration.py`
- `backend/core/priority1_diagnostics.py`
- `backend/core/temporal_backtest.py`
- `backend/data/activation_large_shift_reviews.json`
- `backend/data/cache/nt_ratings.json`
- `docs/PRIORITY1_2_LOCAL_MARKET_XG_VALIDATION.md`
- `backend/data/cache/recent_form_fusion_cache.json.before_refresh`

## 13. Release safety gates

See JSON `release_safety_gates`.

## 14. Risk table

- **Dirty workspace causing accidental unrelated commit** — blocks_commit=True
- **Mixed hunks in priority1_backtest.py** — blocks_commit=True
- **Mixed hunks in priority1_options.py** — blocks_commit=True
- **API/config/env diffs accidentally included** — blocks_commit=True
- **git add . accidental commit** — blocks_commit=True
- **Shadow artifact accidentally exposed later** — blocks_commit=False
- **Default flag accidentally enabled later** — blocks_commit=False
- **Render/env activation later** — blocks_commit=False
- **Tests not rerun after hunk selection** — blocks_commit=True
- **Rollback not validated after commit** — blocks_commit=False
- **Pre-existing research artifacts mixed with production changes** — blocks_commit=True
- **P1.7B.23 safe code blocked by workspace hygiene** — blocks_commit=True

## 15. Rollback plan

- Set nr3_fcc_shadow_enabled=false (default)
- Remove _internal_diagnostics.nr3_fcc_shadow if present
- Verify served probabilities unchanged
- No env/Render changes required

## 16. What not to do

- Do not git add .
- Do not commit api/main.py, api/schemas.py, config.py, .env.example with shadow wiring
- Do not deploy
- Do not activate NR3+FCC
- Do not enable flag by default
- Do not mix Commit D research artifacts into Commit A

## 17. Required next step

Manual hunk selection / commit planning with explicit user approval. When approved: stage Commit A hunks only via git add -p, run tests, then commit.

## 18. Tests run

See JSON `tests_run`.

## 19. Files changed by P1.7B.25

- `backend/core/commit_scope_release_safety_review.py`
- `backend/scripts/run_priority1_7b_25_commit_scope_release_safety_review.py`
- `backend/tests/test_commit_scope_release_safety_review.py`
- `docs/PRIORITY1_7B_25_COMMIT_SCOPE_RELEASE_SAFETY_REVIEW.md`
- `backend/reports/priority1_7b_25_commit_scope_release_safety_review.json`

## 20. Final recommendation

Do not activate. Do not deploy. Do not commit yet unless manual hunk selection is approved. P1.7B.23/P1.7B.24 code is safe in isolation; workspace hygiene requires git add -p on priority1_options.py and priority1_backtest.py before any commit.
