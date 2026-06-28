---
title: "App HTTP REST API Changelog"
last_verified: "2026-06-27"
api_version: "1.0"
status: current
owner: "apps-team"
---
# App HTTP REST API Changelog

Tracks **breaking and additive changes** to the **app-owned** HTTP REST surface in
this repo — the domain route families under `/apps/*` plus the app-domain routes
`/masterplans/*` and `/bridge/*`. Extracted from the pre-split monolith changelog
during DOCS-MIGRATION-2.

Runtime-owned routes (`/platform/*`, `/agent/*`, `/observability/*`, `GET /api/version`)
are documented in the `aindy-runtime` changelog, not here. For the programmatic
syscall ABI, see the runtime syscalls changelog.

## Breaking Change Policy
- **Breaking change**: removing an endpoint, removing a required field, changing a field type,
  changing an auth requirement, changing a status code for an existing success path, or renaming a path.
- **Additive change**: new endpoint, new optional field, new optional response key.
- API versioning is shared with the runtime: breaking changes require a major version increment
  surfaced through `GET /api/version` and the `X-API-Version` response header (both runtime-owned).
- Clients can detect compatibility risk by calling `GET /api/version` and by watching
  `X-Version-Warning` when they send `X-Client-Version`.

## Unreleased

Changes merged but not yet documented in a tagged API contract release.

*(none)*

---

## [1.0.0] - 2026-04-26

App-route surface verified against the live route tree on 2026-04-26.

### Added

- `POST /masterplans/lock` — locks a synthesized genesis draft into a masterplan.
- `POST /masterplans/{plan_id}/activate-cascade` — evaluates task dependencies and activates ready
  tasks. Response includes `activated`, `count`, and `masterplan_id`.

### Breaking

- `GET /masterplans/` — response shape changed from a bare JSON list to `{"plans": [...]}`.
  Migration: update clients to read `response.plans` instead of treating the response body as the list.

### Deprecated

- Legacy routes exposed without the `/apps` compatibility prefix are transitional only when
  `AINDY_ENABLE_LEGACY_SURFACE=true`.
  Migration: move integrations to the documented `/apps/...` paths.
  Removal timeline: not yet scheduled; do not build new integrations on the legacy surface.

### Security

- JWT authentication is now **required** for the primary domain route families `/apps/tasks/*`,
  `/apps/leadgen/*`, `/apps/genesis/*`, and `/apps/analytics/*`. Unauthenticated requests return `401`.
  Migration: add `Authorization: Bearer <token>` to existing integrations.
- The remaining app routers — ARM, RippleTrace, Freelance, Authorship, search/SEO, research results,
  dashboard, and social — now also require JWT authentication.
  Migration: add `Authorization: Bearer <token>` to existing integrations.
- `POST /bridge/nodes`, `GET /bridge/nodes`, and `POST /bridge/link` now require JWT authentication.
  `POST /bridge/user_event` requires API-key authentication (the configured service key).
  Migration: add the Bearer token for interactive bridge calls and the service API key for
  `POST /bridge/user_event`.
