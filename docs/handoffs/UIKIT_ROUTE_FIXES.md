---
title: "UI-Kit Route Fixes — handoff to @aindy/ui-kit"
last_verified: "2026-07-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# UI-Kit Route Fixes — handoff to `@aindy/ui-kit`

## What this is

A live-frontend verification of `client/` (2026-07-18) cross-checked all client route
definitions against the live backend surface. The client reaches the backend through
`@aindy/ui-kit`'s `ROUTES` object (this repo's `client/src/api/_routes.js` just
re-exports it), so any wrong path in `ROUTES` is a bug this app inherits and cannot fix
without an override.

**Result:** 117 of 135 client routes resolve to real backend endpoints; **18 do not** —
all in three `ROUTES` groups whose path values **omit the backend router's prefix
segment** (`compute` / `seo` / `platform`). One is a confirmed live break (the AI SEO
tool 404s).

## Root cause

`buildApiUrl` prepends `API_BASE` to a `ROUTES` value verbatim — there is no
domain-based routing. Routes with no intermediate prefix (`/tasks/list`, `/agent/run`,
`/memory/recall/v3`) resolve fine because the backend serves them directly. The three
families below sit behind a FastAPI router mount (`/compute`, `/seo`, `/platform/flows`)
that the `ROUTES` values dropped, so `buildApiUrl` produces a path the backend never
registers.

## The fix (18 `ROUTES` values)

Every corrected path below is verified present on the live backend
(`GET /openapi.json`, app-profile boot).

### `ROUTES.ANALYTICS.*` — add the `/compute` prefix (14)

| Key | Current (wrong) | Correct |
|---|---|---|
| `CALCULATE_TWR` | `/calculate_twr` | `/compute/calculate_twr` |
| `CALCULATE_ENGAGEMENT` | `/calculate_engagement` | `/compute/calculate_engagement` |
| `CALCULATE_AI_EFFICIENCY` | `/calculate_ai_efficiency` | `/compute/calculate_ai_efficiency` |
| `CALCULATE_IMPACT_SCORE` | `/calculate_impact_score` | `/compute/calculate_impact_score` |
| `CALCULATE_AI_PRODUCTIVITY_BOOST` | `/ai_productivity_boost` | `/compute/ai_productivity_boost` |
| `CALCULATE_ATTENTION_VALUE` | `/attention_value` | `/compute/attention_value` |
| `CALCULATE_BUSINESS_GROWTH` | `/business_growth` | `/compute/business_growth` |
| `CALCULATE_DECISION_EFFICIENCY` | `/decision_efficiency` | `/compute/decision_efficiency` |
| `CALCULATE_ENGAGEMENT_RATE` | `/engagement_rate` | `/compute/engagement_rate` |
| `CALCULATE_EXECUTION_SPEED` | `/execution_speed` | `/compute/execution_speed` |
| `CALCULATE_INCOME_EFFICIENCY` | `/income_efficiency` | `/compute/income_efficiency` |
| `CALCULATE_LOST_POTENTIAL` | `/lost_potential` | `/compute/lost_potential` |
| `CALCULATE_MONETIZATION_EFFICIENCY` | `/monetization_efficiency` | `/compute/monetization_efficiency` |
| `CALCULATE_REVENUE_SCALING` | `/revenue_scaling` | `/compute/revenue_scaling` |

### `ROUTES.SEARCH.*` (SEO) — add the `/seo` prefix (3)

| Key | Current (wrong) | Correct |
|---|---|---|
| `ANALYZE_SEO` | `/analyze_seo/` | `/seo/analyze_seo/` |
| `GENERATE_META` | `/generate_meta/` | `/seo/generate_meta/` |
| `SUGGEST_IMPROVEMENTS` | `/suggest_improvements/` | `/seo/suggest_improvements/` |

These target the backend's compat aliases (which exist). The backend also exposes
canonical shorter routes — `/seo/analyze`, `/seo/meta`, `/seo/suggest` — so if ui-kit
prefers those, point there instead; either resolves.

### `ROUTES.OPERATOR.FLOW_STRATEGIES` — add the `/platform` prefix (1)

| Key | Current (wrong) | Correct |
|---|---|---|
| `FLOW_STRATEGIES` | `/flows/strategies` | `/platform/flows/strategies` |

## Severity / blast radius (in this app)

- **`ANALYZE_SEO` / `GENERATE_META` / `SUGGEST_IMPROVEMENTS`** — **confirmed live break.**
  `AiSeoTool` (routed at `/search/seo`, mounted) calls all three; each request 404s.
- **`ANALYTICS.CALCULATE_*`** — consumed by the KPI panels (`AIEfficiencyPanel`,
  `EngagementPanel`, `DecisionEfficiencyPanel`, …), app components.
- **`OPERATOR.FLOW_STRATEGIES`** — the platform flows-strategies view.

## Verification the ui-kit maintainer can run

Resolve every `ROUTES.*` value through `buildApiUrl` and assert it matches a live
backend route. The app-side cross-check that found this (135 client routes vs the live
`/openapi.json` app-profile surface, structural match with `{param}` as wildcards and an
optional leading `/apps` stripped) drops from 18 mismatches to 0 once these land.

## App-side follow-on

None required beyond a `@aindy/ui-kit` version bump once the fix ships — this repo does
not vendor `ROUTES`. Tracked here as **UIKIT-ROUTE-DRIFT-1** in `TECH_DEBT.md`. If the
SEO break needs unblocking before ui-kit ships, the stopgap is an app-side `_routes.js`
that spreads `ROUTES` and overrides the 18 corrected values.
