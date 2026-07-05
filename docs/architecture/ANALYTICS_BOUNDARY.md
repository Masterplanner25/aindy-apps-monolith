---
title: "Analytics Boundary (app-owned)"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---

# Analytics Boundary

This is the **app-owned half** of the analytics ownership boundary, extracted from the
pre-split monolith doc during DOCS-MIGRATION-2. It defines what belongs to the
`apps/analytics` domain in this repo. The platform-observability half
(`AINDY/analytics/` — domain-agnostic execution/request/latency metrics) is
runtime-owned and lives in `aindy-runtime`.

## `apps/analytics/` — Domain analytics (this repo)

Contains: user KPI snapshots, Infinity scoring, per-user calculations, score
history, adaptive KPI weighting, policy adaptation, ARM-linked scoring,
task/masterplan/social-derived analytics, analytics routes, analytics syscalls,
and the analytics public contracts consumed by other apps (see
`apps/analytics/public.py` and
[PUBLIC_SURFACE_CONTRACTS](./PUBLIC_SURFACE_CONTRACTS.md)).

Rule: All user-facing analytics logic belongs here. New analytics features go in
`apps/analytics/services/`.

## What does NOT belong here — `AINDY/analytics/` (runtime-owned)

Domain-agnostic platform observability only: execution metrics, request counts,
latency tracking, infrastructure health. Code on the runtime side must not import
from `apps/`, and app analytics (user scores, KPI logic, masterplan/task-derived
business metrics) must not be added to the runtime observability layer.

This split is the authoritative boundary; the runtime repo owns and documents its
side. See also [CROSS_DOMAIN_COUPLING](./CROSS_DOMAIN_COUPLING.md) for how other
domains consume analytics through declared public contracts and syscalls rather
than reaching into `apps/analytics` internals.
