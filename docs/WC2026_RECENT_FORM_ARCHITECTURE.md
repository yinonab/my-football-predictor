# WC 2026 Predictor — API-Backed Recent Form Architecture

## Purpose

This document defines the architecture for improving national-team recent-form data, especially for the `Underdog Goal Gate` used by scoreline selection.

The goal is to make underdog-goal decisions more credible by using real, recent match data when available, while keeping the prediction system stable, cache-first, and safe when external APIs fail.

This architecture must not break the existing prediction pipeline.

---

## Current State

The project currently has:

### Existing prediction pipeline

```text
Team selection
↓
Team strength / power calculation
↓
xG calculation
↓
Score matrix generation
↓
scoreline_decision
↓
representative_v1_gate
↓
underdog_goal_gate
↓
primary_predicted_score
```

### Existing accepted behavior

The current deployed system already supports:

* `football-data.org` fixture state provider
* completed match detection
* `venue_mode`
* real home advantage
* representative scoreline selection
* `Underdog Goal Gate`
* completed matches shown as historical / invalid predictions
* no automatic underdog goal
* no automatic 2-1 bias
* no automatic 1-0 bias

### Current weakness

The `Underdog Goal Gate` already has a recent-form concept, but recent form is often unavailable or medium confidence.

In production checks, diagnostics may show:

```text
RECENT_FORM_UNAVAILABLE
```

This means the gate often relies mostly on:

* underdog xG
* probability underdog scores at least once
* BTTS probability
* favorite strength class
* candidate comparison

That is acceptable as a conservative fallback, but not enough for high-confidence underdog goal decisions.

---

## Product Goal

We want the model to answer:

```text
Is the underdog actually likely to score recently, and especially against strong opponents?
```

This helps distinguish:

```text
Brazil 4-0 Haiti
```

from:

```text
Brazil 4-1 Haiti
```

or:

```text
Netherlands 2-0 Sweden
```

from:

```text
Netherlands 2-1 Sweden
```

The system should give the underdog a goal only when justified by a combination of:

* model probabilities
* xG
* BTTS probability
* candidate score closeness
* recent scoring form
* opponent/favorite strength

Recent form must improve confidence, not force goals.

---

## Core Principle

Separate two decisions:

### 1. Can the underdog plausibly score?

Inputs:

* underdog xG
* probability underdog scores at least once
* BTTS probability
* recent scoring form
* opponent/favorite strength
* scored vs similar-or-stronger opponents

### 2. Should the primary score include that underdog goal?

Inputs:

* clean-sheet candidate probability
* underdog-goal candidate probability
* exact probability gap
* representative score gap
* xG fit
* total-goals fit
* goal-difference fit
* gate level

Important:

Even if the underdog has a 45%–55% chance to score, the primary predicted score should not automatically include an underdog goal.

That only means underdog-goal candidates such as `2-1`, `3-1`, `1-1`, `1-2`, etc. are allowed to compete.

---

## Data Strategy

The system should not call external APIs live on every prediction.

The correct design is:

```text
External APIs
↓
Backend ingestion / lazy refresh
↓
Normalized recent-form cache
↓
Recent-form metrics
↓
Underdog Goal Gate
↓
Primary score selection
```

Prediction should use the normalized cache, not rely on external API availability at request time.

---

## Why Not Call APIs on Every Prediction?

Live API calls during `/api/predict` are risky because they can cause:

* slow responses
* rate limits
* flaky predictions
* failed predictions when APIs are down
* inconsistent results
* secret exposure risk
* unstable tests

Therefore:

```text
Prediction must be cache-first.
External APIs may refresh the cache.
The model must work even when external APIs fail.
```

---

## Source Priority

Recent-form data should be resolved by source priority.

### Priority 1 — Fresh API-backed cache

Highest confidence.

Examples:

* football-data.org historical/team match cache
* API-Football historical/team match cache
* another trusted fixture/result provider

Requirements:

* real dates
* real scores
* source timestamp
* normalized teams
* cached locally or persisted
* no live dependency in tests

### Priority 2 — Stale but usable API-backed cache

Still valuable, but with freshness warning.

Example:

```text
API data fetched 7 days ago
```

### Priority 3 — Static bundled data with real dates

Examples:

* WC 2026 qualifiers
* other existing real-dated datasets in repo

### Priority 4 — Static bundled tournament data with synthetic dates

Examples:

* WC2018
* WC2022
* Euro2024
* Copa2024

Useful, but lower confidence if dates are synthetic or not fully precise.

### Priority 5 — Unavailable

No usable recent form.

Behavior:

```text
recent_form_confidence = unavailable
RECENT_FORM_UNAVAILABLE
conservative fallback
```

---

## Existing Sources to Audit

Cursor must inspect the repo for all available historical national-team result sources.

Potential sources:

```text
BUNDLED_NT_MATCHES
WC2018 data
WC2022 data
Euro2024 data
Copa2024 data
WC2026 qualifiers
backend/data/cache/nt_history_fetched.json
backend/data/cache/wc2026_live_matches.json
backend/data/cache/nt_ratings.json
football-data.org cached responses
API-Football cached responses
any build_all_matches() or equivalent helper
```

For each source, report:

* file/module path
* competitions covered
* team coverage
* date coverage
* real dates vs synthetic ordering
* goals for / goals against availability
* opponent identity availability
* home/away/neutral availability
* source reliability
* source freshness
* whether usable in offline tests
* whether persisted across deploys
* whether it is generated/cache or source-controlled data

---

## External API Strategy

### API usage should be backend-only

Mobile must never call football-data.org or API-Football directly.

Reasons:

* avoid exposing API keys
* avoid rate limits per device
* avoid mobile network failures affecting prediction
* keep prediction behavior centralized
* allow caching and fallback

Correct flow:

```text
Mobile app
↓
Backend API
↓
Backend recent-form resolver
↓
Cache / API refresh / fallback
```

---

## football-data.org

Currently used successfully for fixture status:

* scheduled / completed
* kickoff time
* actual score
* fixture source

Need to audit whether it can provide historical recent matches for national teams under the current plan.

Questions:

* Can it return recent matches by national team?
* Can it return WC / qualifier / friendly history?
* Does the current tier allow this?
* Are results complete enough for all WC 2026 teams?
* What are rate limits?
* Can results be cached safely?
* Can tests avoid live calls?

Do not assume football-data can provide all required history until verified.

---

## API-Football

Currently API-Football is unreliable / suspended in previous checks.

Do not make API-Football a required source.

It may remain:

```text
optional fallback
diagnostic source
future source if account works
```

But the architecture must work without it.

---

## Cache Architecture

### Recommended cache file

Initial implementation may use JSON:

```text
backend/data/cache/recent_form_cache.json
```

Future implementation may move to DB, but JSON is acceptable for MVP.

### Cache shape

Example:

```json
{
  "schema_version": 1,
  "last_updated_utc": "2026-06-20T00:00:00Z",
  "sources": {
    "football-data.org": {
      "last_success_utc": "2026-06-20T00:00:00Z",
      "status": "ok"
    }
  },
  "teams": {
    "Sweden": {
      "team": "Sweden",
      "normalized_team": "Sweden",
      "last_updated_utc": "2026-06-20T00:00:00Z",
      "source_priority": "api_cache_fresh",
      "source_confidence": "high",
      "matches": [
        {
          "date": "2026-06-14",
          "opponent": "Tunisia",
          "goals_for": 5,
          "goals_against": 1,
          "competition": "World Cup",
          "source": "football-data.org",
          "source_confidence": "high",
          "date_confidence": "high",
          "is_home": null,
          "is_neutral": null
        }
      ]
    }
  }
}
```

---

## Normalized Match Model

Create a normalized internal model for recent matches.

Suggested module:

```text
backend/core/recent_match_history.py
```

Suggested record fields:

```text
date
team
opponent
goals_for
goals_against
competition
source
source_priority
source_confidence
date_confidence
is_home
is_neutral
opponent_power_proxy
opponent_strength_confidence
raw_source_id
```

Requirements:

* normalize team names
* deduplicate matches
* sort by date descending
* support `before_date`
* support limit, usually 10
* prefer real-dated API/cache matches over synthetic static matches
* avoid future leakage
* avoid using completed future tournament matches when predicting a match before that date

---

## Team Name Normalization

Must support common aliases:

```text
USA / United States
Czechia / Czech Republic
DR Congo / Congo DR / Democratic Republic of the Congo
Ivory Coast / Côte d'Ivoire
Bosnia and Herzegovina / Bosnia-Herzegovina
Curacao / Curaçao
South Korea / Korea Republic
Iran / IR Iran
Saudi Arabia / Saudi Arabia
Cape Verde / Cabo Verde
New Zealand
```

Use a centralized alias map where possible.

Do not scatter alias logic across scripts.

---

## Recent Form Metrics

Create or improve:

```text
get_recent_scoring_form(team, before_date=None, opponent_context=None)
```

Expected output:

```json
{
  "team": "Sweden",
  "matches_found": 10,
  "requested_match_count": 10,
  "before_date": "2026-06-20",
  "last_10_scored_rate": 0.7,
  "last_10_goals_for_avg": 1.5,
  "last_10_goals_against_avg": 0.9,
  "last_10_failed_to_score_rate": 0.3,
  "scored_vs_similar_or_stronger_opponents_rate": 0.45,
  "recent_form_confidence": "high",
  "recent_form_source": "api_cache_fresh",
  "source_breakdown": {
    "football-data.org": 8,
    "bundled_qualifiers": 2
  },
  "reason_codes": [
    "RECENT_FORM_HIGH_CONFIDENCE",
    "RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED"
  ]
}
```

---

## Confidence Rules

### High confidence

```text
8–10 usable matches
real dates
real scores
source is API cache or reliable real-dated static source
```

### Medium confidence

```text
6–7 matches
or 8–10 matches with mixed real/synthetic dates
or partial source uncertainty
```

### Low confidence

```text
3–5 matches
```

### Unavailable

```text
0–2 matches
```

Missing recent form must not count as positive evidence.

---

## Source Weighting

Recent form should have variable influence depending on source quality.

Recommended maximum influence:

```text
Fresh API cache:          up to 25–30 support points
Stale API cache:          up to 20 support points
Real-dated static data:   up to 15 support points
Synthetic/partial static: up to 8–10 support points
Unavailable:             0 support points
```

This reflects the product principle:

```text
Network/API-backed recent data should carry more weight than partial static data.
```

But even high-quality API form must not force goals by itself.

---

## Lazy Refresh Strategy

The backend should support lazy refresh without making prediction fragile.

### Case 1 — Cache fresh

```text
Use cache immediately.
No refresh needed.
```

### Case 2 — Cache stale but usable

```text
Use stale cache for prediction.
Trigger lazy refresh in background if possible.
Return diagnostics:
RECENT_FORM_STALE_CACHE_USED
```

### Case 3 — Cache missing

Two acceptable strategies:

#### Option A — Short blocking refresh

```text
Try refresh with strict timeout, e.g. 2–3 seconds.
If successful, use new data.
If failed, fallback.
```

#### Option B — Non-blocking refresh

```text
Return prediction using fallback immediately.
Trigger refresh for next request.
```

Recommended MVP hybrid:

```text
If no data at all:
    try short blocking refresh if safe and enabled
If stale data exists:
    use stale data and refresh in background
If refresh fails:
    fallback without breaking prediction
```

---

## Scheduled Refresh Strategy

Do not require scheduled infrastructure immediately.

Phased approach:

### Phase A — Manual refresh script

```text
python scripts/refresh_recent_form_cache.py
```

### Phase B — Lazy refresh on prediction

```text
If cache is missing/stale, backend attempts refresh safely.
```

### Phase C — Scheduled refresh

If hosting supports it:

```text
daily refresh
12-hour refresh during tournament
extra refresh on match days
```

If hosting does not support background workers, keep manual/lazy refresh.

---

## Feature Flags

Add feature flags to keep the system safe.

Suggested:

```text
RECENT_FORM_API_ENABLED=true
RECENT_FORM_LAZY_REFRESH_ENABLED=false
RECENT_FORM_AFFECTS_SCORELINE=false
RECENT_FORM_CACHE_TTL_HOURS=24
RECENT_FORM_REFRESH_TIMEOUT_SECONDS=3
```

Recommended rollout:

### Stage 1 — Diagnostics only

```text
RECENT_FORM_API_ENABLED=true
RECENT_FORM_AFFECTS_SCORELINE=false
```

Collect cache and show diagnostics, but do not affect the scoreline.

### Stage 2 — Shadow influence

Compute gate with and without API-backed recent form and compare.

### Stage 3 — Active influence

```text
RECENT_FORM_AFFECTS_SCORELINE=true
```

Only after coverage and QA are acceptable.

---

## Integration with Underdog Goal Gate

The `Underdog Goal Gate` should receive recent-form metrics.

It should use them like this:

### Strong recent scoring support

Examples:

```text
last_10_scored_rate >= 0.70
high confidence
API-backed or real-dated source
```

Effect:

```text
Can move WEAK_ALLOW → ALLOW
Can move ALLOW → STRONG_ALLOW
Only if xG/matrix/candidate closeness also support it
```

### Moderate support

```text
last_10_scored_rate 0.50–0.69
```

Effect:

```text
Supports underdog goal, but does not force it
```

### Weak support

```text
last_10_scored_rate 0.30–0.49
```

Effect:

```text
Small support only
```

### Negative signal

```text
last_10_scored_rate < 0.30
or failed_to_score_rate high
```

Effect:

```text
Can move ALLOW → WEAK_ALLOW
Can move WEAK_ALLOW → BLOCK
```

### Unavailable

```text
No positive support
Conservative fallback
Diagnostics explain missing form
```

---

## Candidate Comparison Must Remain Mandatory

Recent form must not override candidate probability.

Even if recent form is strong:

```text
If 3-0 = 8.5% and 3-1 = 4.2%,
do not choose 3-1 unless gate is STRONG_ALLOW and xG fit is materially better.
```

If candidates are close:

```text
2-0 = 9.5%
2-1 = 8.7%
```

Then strong recent form can justify `2-1`.

---

## Diagnostics

Extend diagnostics under:

```text
scoreline_decision.underdog_goal_gate
```

Fields:

```text
recent_form_available
recent_form_source
recent_form_source_priority
recent_form_freshness_hours
recent_form_confidence
matches_found
requested_match_count
last_10_scored_rate
last_10_goals_for_avg
last_10_goals_against_avg
last_10_failed_to_score_rate
scored_vs_similar_or_stronger_opponents_rate
recent_form_source_breakdown
recent_form_reason_codes
```

Reason codes:

```text
RECENT_FORM_HIGH_CONFIDENCE
RECENT_FORM_MEDIUM_CONFIDENCE
RECENT_FORM_LOW_CONFIDENCE
RECENT_FORM_UNAVAILABLE
RECENT_FORM_STALE_CACHE_USED
RECENT_FORM_API_CACHE_USED
RECENT_FORM_STATIC_REAL_DATES_USED
RECENT_FORM_STATIC_SYNTHETIC_DATES_USED
RECENT_FORM_OPPONENT_STRENGTH_PROXY_USED
RECENT_FORM_OPPONENT_STRENGTH_UNAVAILABLE
RECENT_FORM_STRONG_SCORING_SUPPORT
RECENT_FORM_MODERATE_SCORING_SUPPORT
RECENT_FORM_WEAK_SCORING_SUPPORT
RECENT_FORM_NEGATIVE_SCORING_SIGNAL
RECENT_FORM_REFRESH_FAILED
RECENT_FORM_REFRESH_SKIPPED_RATE_LIMIT
```

---

## Fallback Behavior

Prediction must never fail because recent-form data is unavailable.

Failure cases:

```text
external API down
rate limit
invalid response
missing API key
cache missing
cache corrupt
team alias mismatch
network timeout
```

Required behavior:

```text
Prediction still returns.
Underdog Goal Gate uses conservative fallback.
Diagnostics explain why.
No exception is exposed to the user.
```

---

## API / Endpoint Design

Optional backend endpoints may be added later.

### Warmup endpoint

```text
POST /api/recent-form/warmup
```

Purpose:

```text
Trigger recent-form refresh for likely teams.
```

Should require no secrets in request.

### Status endpoint

```text
GET /api/recent-form/status
```

Returns:

```text
cache age
source status
team coverage
last refresh status
```

### Team endpoint

```text
GET /api/recent-form/team/{team}
```

Returns recent form diagnostics for one team.

These are optional and should not be required for the initial architecture spike.

---

## Mobile Behavior

Mobile should not call external providers directly.

Possible future mobile behavior:

```text
App startup
↓
Call backend warmup endpoint
↓
Backend refreshes cache lazily
```

But prediction must work even if the warmup never happens.

No football-data/API-Football token should ever exist in the mobile app.

---

## Rollout Plan

### Phase 4R — Architecture + Coverage Audit

No prediction behavior change.

Tasks:

* audit available sources
* audit API capabilities
* define normalized schema
* define cache strategy
* produce coverage report
* produce implementation plan

Output:

```text
recent_form_architecture_report.md
recent_form_coverage_audit.md
recent_form_coverage_audit.csv
```

### Phase 4R.1 — Normalized Recent Form Store

Build:

```text
backend/core/recent_match_history.py
backend/core/recent_form_store.py
backend/scripts/audit_recent_form_coverage.py
```

Behavior:

```text
offline/static sources only initially
no live API dependency
diagnostics only or low-risk integration
```

### Phase 4R.2 — API-Backed Cache Ingestion

Build:

```text
backend/scripts/refresh_recent_form_cache.py
API-backed fetchers
cache writer
TTL/freshness logic
source priority
```

Feature flag protected.

### Phase 4R.3 — Lazy Refresh

Add:

```text
cache stale/missing detection
short timeout refresh
background refresh if possible
fallback behavior
```

Feature flag protected.

### Phase 4R.4 — Active Gate Integration

Only after coverage is acceptable.

Enable:

```text
RECENT_FORM_AFFECTS_SCORELINE=true
```

Use high-confidence API-backed recent form in active underdog goal decisions.

---

## Testing Requirements

Tests must not require API keys or live network.

Required test areas:

### Normalization tests

* aliases normalize correctly
* duplicate matches deduplicate correctly
* date sorting works
* before_date prevents leakage
* synthetic date confidence handled correctly

### Metric tests

* scored rate correct
* failed-to-score rate correct
* goals-for average correct
* goals-against average correct
* confidence rules correct
* source breakdown correct

### Cache tests

* fresh cache selected first
* stale cache selected with warning
* static fallback works
* corrupt cache fails safely
* missing cache fails safely

### Gate integration tests

* strong API-backed form supports underdog goal
* weak form suppresses underdog goal
* unavailable form remains conservative
* candidate comparison still wins over form when probability gap is too large
* elite favorite remains strict
* balanced matches are not over-blocked

### Regression tests

* top_scores unchanged
* top_exact_score_overall unchanged
* completed matches unchanged
* venue_mode unchanged
* no calibration or odds behavior changes

---

## Success Criteria

The architecture is successful if:

```text
1. Prediction does not depend on live API availability.
2. Recent form is more available and higher confidence.
3. API-backed data gets higher weight than partial static data.
4. Missing data falls back safely.
5. Underdog goals are better justified.
6. There is no automatic 2-1 bias.
7. There is no return to automatic 1-0 bias.
8. Diagnostics clearly explain recent-form usage.
9. Tests remain offline and stable.
10. No secrets are committed or exposed.
```

---

## Product Examples

### Brazil vs Haiti

If Haiti has weak/unavailable recent scoring form:

```text
Brazil 4-0 or 3-0 should be preferred.
```

If Haiti has strong recent scoring form, including scoring vs strong opponents:

```text
Brazil 4-1 can be considered.
```

But it should never be automatic.

### Netherlands vs Sweden

If Sweden has good recent scoring form and 2-1 is close to 2-0:

```text
2-1 is legitimate.
```

If Sweden form is weak or unavailable:

```text
2-0 should remain preferred.
```

### Tunisia vs Japan

If Tunisia scoring form is weak:

```text
0-2 or 0-1 should remain preferred.
```

If Tunisia has strong recent scoring support and candidate closeness:

```text
1-2 can be selected.
```

### Switzerland vs Canada

More balanced match.

If Canada xG and form support scoring:

```text
2-1 or 1-1 can be legitimate.
```

But clean-sheet outcomes should remain possible when candidate comparison favors them.

---

## Non-Goals

This architecture does not aim to:

* rewrite Maher
* rewrite Dixon-Coles
* change xG model
* change 1X2 probabilities
* change venue/home advantage
* change football-data fixture provider
* revive API-Football as required source
* enable odds influence
* enable calibration
* expose provider tokens to mobile
* make prediction depend on live API calls
* force underdog goals

---

## Cursor Implementation Rules

For any implementation prompt based on this document:

* Do not commit/push/deploy unless explicitly approved.
* Do not include secrets.
* Do not include reports/cache/build artifacts.
* Do not alter mobile unless specifically scoped.
* Do not alter calibration/odds.
* Do not break completed-match behavior.
* Do not require live API in tests.
* Provide coverage reports before changing active scoreline behavior.
* Prefer feature flags and diagnostics-first rollout.

---

## Related Code (as of Phase 4Q.1)

Current implementation baseline to extend:

* `backend/core/recent_scoring_form.py` — bundled/static recent form (Phase 4Q.1)
* `backend/core/underdog_goal_gate.py` — gate levels and support scoring
* `backend/core/scoreline_decision.py` — `representative_v1_gate` integration
* `docs/PREDICTION_INTELLIGENCE_ARCHITECTURE.md` — broader prediction intelligence context

### Phase A — Sofascore adapter (not wired to predict/fusion)

* `backend/data/sofascore.py` — read-only RapidAPI client (`sofascore.p.rapidapi.com`)
* Match enrichment endpoints require **`matchId`** (not `eventId`)
* Verified fields: aggregate `expectedGoals` in statistics; shot-level `xg` / `xgot` in shotmap
* Provider team IDs are namespaced as `provider_ids["sofascore"]` (e.g. Brazil men → 4748)
* Not connected to `/api/predict` or scoreline flags

### Phase B — Sofascore fusion refresh (cache-only on predict path)

* `collect_sofascore_candidates()` in `recent_form_fusion.py` — last-matches → fusion candidates
* Provider string: `sofascore_recent_form` (priority 98, below API-Football/football-data)
* Refresh via `refresh_recent_form_fusion_cache.py --provider sofascore` when `SOFASCORE_ENABLED=true`
* Audit: `summarize_sofascore_fusion_coverage()` in store/sources audit scripts
