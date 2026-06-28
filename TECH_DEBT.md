# Technical Debt

## LINT-VERSION-GAP-1: eslint trails @aindy/ui-kit by one major version

**Status:** RESOLVED (2026-06-27, PR #4). `eslint` ^9.36 → ^10.4, `@eslint/js` → ^10.0.1,
`eslint-plugin-react-hooks` ^5.2 → ^7.1.1 (required for eslint 10 — 5.x peers cap at eslint 9),
`react-refresh` → 0.4.24. Frontend lint is now gated in CI (`npm run lint` in the Frontend Unit
Tests job) and `main` is branch-protected requiring it.

The upgrade surfaced a pre-existing, un-enforced lint debt (frontend lint had never been green or
CI-gated): 612 problems at the start. Errors were driven to zero — notably **94 rules-of-hooks**
violations fixed by extracting the bodies of 7 admin-gated platform pages into inner components so
hooks run unconditionally (behavior preserved; 121 unit tests + production build pass). Two new
react-hooks 7.x rules and the HMR-only `only-export-components` rule were set to `warn` rather than
adopted wholesale, per the original scoping below. Residual non-blocking warnings are tracked as
**LINT-WARNINGS-RESIDUAL-1**.

Original context retained below for history.

**Context:** `aindy-apps-monolith` is on `eslint@^9.36.0`. The `@aindy/ui-kit` library it consumes is on `eslint@^10.4.0`. Both use flat config; shared plugin overlap is `eslint-plugin-react-hooks` (this repo on `^5.2.0`, ui-kit on `^7.1.1` — independent version tracks).

**Posture:** Consumer trails library by one major version. The library's choice to lead is structurally correct; this entry is the consumer's side of the same finding.

**Cross-ref:** Same finding tracked in `aindy-runtime/TECH_DEBT.md` as LINT-VERSION-GAP-1 (runtime side, covering ui-kit).

**Upgrade scope when triggered:**
1. Bump `eslint` from `^9.36.0` to `^10.x` in `client/package.json`.
2. Verify `eslint-plugin-react-refresh@^0.4.22` is compatible with eslint 10 — this is the plugin most likely to require a coordinated bump.
3. Verify `eslint-plugin-react-hooks@^5.2.0` continues to work under eslint 10 (it should — react-hooks 5.x supports both eslint 9 and 10).
4. Verify the custom `no-restricted-syntax` rule enforcing `safeMap()` over `.map()` still parses under eslint 10's rule-config schema (flat config shape is stable across 9 → 10, low risk).
5. Run lint against the full `client/` source. Fix any new rule findings or silence with documented inline disables.

**Reopen trigger:** (a) any maintenance pass in this repo with budget for ~30 minutes of side-task work, OR (b) a desired ui-kit rule or react-hooks rule becomes eslint-10-only and back-pressures the upgrade.

**Estimated effort:** ~30 minutes assuming no plugin breakage. Add 30–60 minutes if `eslint-plugin-react-refresh` requires its own upgrade for compatibility.

**Out of scope for this entry:**
- Adopting `eslint-plugin-react-hooks@^7.x` is independent of the eslint version bump and should be evaluated separately. Hooks 7.x dropped support for eslint 8, so it's only available after this upgrade lands.
- Porting the `safeMap()` invariant to ui-kit was considered and rejected — ui-kit's `"strict": true` TypeScript config handles the bug class the rule guards in plain-JS apps-monolith code.

---

## LINT-WARNINGS-RESIDUAL-1: frontend lint passes with 68 deferred warnings

**Status:** Tracked, accepted. Address opportunistically; no single forcing event.

**Context:** The eslint 10 upgrade (LINT-VERSION-GAP-1) drove lint errors to zero, but three
rule categories were set to `warn` rather than fixed wholesale, leaving `npm run lint` green
(exit 0) with 68 warnings. These are intentionally non-blocking — the CI lint gate fails only
on errors.

**Breakdown:**
- `react-hooks/set-state-in-effect` (38) — new in react-hooks 7.x. Flags `setState` called
  synchronously inside an effect body (mostly mount-time data-loading effects: `useEffect(() =>
  { load() }, [load])`). Fixing each requires per-effect review; some are legitimate. Adopt
  incrementally.
- `react-hooks/exhaustive-deps` (17) — pre-existing missing-dependency warnings (existed under
  react-hooks 5.x; never enforced because frontend lint wasn't gated until now).
- `react-refresh/only-export-components` (11) — HMR-only DX rule. Context/primitive files
  (`AuthContext`, `SystemContext`, `SurfacePrimitives`, `button`, `AdminApiErrorBoundary`)
  co-locate a hook/helper with a component. "Fixing" means splitting files — churn for no
  runtime benefit.
- `react-hooks/immutability` (2) — new in react-hooks 7.x; flags mutating values defined
  outside a component (e.g. `window.location.href = …` in a redirect component).

**Reopen trigger:** (a) a render-performance issue traced to a `set-state-in-effect` cascade,
(b) a stale-closure bug traced to a missing dependency, or (c) a deliberate pass to ratchet any
of these rules back to `error` (would pair well with `--max-warnings 0` in the CI lint step).

**Estimated effort:** `exhaustive-deps` and `immutability` are small (~1–2h). `set-state-in-effect`
is the bulk (38 sites, each needs judgment); budget a half-day if driving to zero.

---

## DOCS-MIGRATION-1: app-owned docs recovered from pre-split archive

**Status:** RESOLVED (2026-06-27). 18 docs moved + path-fixup sweep complete. Residuals noted below.

**Context:** When `aindy-runtime` and `aindy-apps-monolith` were split out of the original combined
repo (`masterplan-infiniteweave-monday-node-2025-0411`), 18 app-owned docs were left behind in the
archive. They were copied into this repo on 2026-06-27, preserving subtree paths, per the ownership
map in `aindy-runtime/docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`:

- `docs/apps/`: `RIPPLETRACE.md`, `AUTONOMOUS_REASONING_MODULE.md`, `SEARCH_SYSTEM.md`,
  `SOCIAL_LAYER.md`, `FREELANCING_SYSTEM.md`, `INFINITY_ALGORITHM{,_CANONICAL,_FORMALIZATION,_SUPPORT_SYSTEM}.md`,
  `ABSTRACTED_ALGORITHM_SPEC.md`, `FORMULA_AND_ALGORITHM_OVERVIEW.md`
- `docs/architecture/`: `PUBLIC_SURFACE_AUDIT.md`, `PUBLIC_SURFACE_CONTRACTS.md`,
  `PUBLIC_SURFACE_MIGRATION_GUIDE.md`, `USER_ID_AUDIT.md`
- `docs/api/API_REFERENCE.md`, `docs/platform/engineering/IMPLEMENTATION_DOCS_AUDIT.md`,
  `docs/platform/governance/MASTERPLAN_SAAS.md`

**Fixup performed (2026-06-27):** The pre-split docs referenced a flat monolith layout
(`services/foo.py`, `routes/foo.py`, `db/models/foo.py`, `AINDY/services/foo.py`). Every code-path
token was Glob-verified against the current tree and rewritten:
- app modules → `apps/<domain>/...` (e.g. `services/infinity_service.py` →
  `apps/analytics/services/scoring/infinity_service.py`; the flat `apps/analytics/services/*.py`
  files are compat shims — docs point at the canonical `scoring/`/`orchestration/`/`calculations/`
  implementations).
- runtime modules → confirmed in sibling `aindy-runtime` and written as their real `AINDY/...`
  paths (e.g. `services/agent_runtime.py` → `AINDY/agents/agent_runtime.py`).
- The architecture docs (`PUBLIC_SURFACE_*`, `USER_ID_AUDIT`) and `API_REFERENCE`,
  `IMPLEMENTATION_DOCS_AUDIT`, `MASTERPLAN_SAAS`, `ABSTRACTED_ALGORITHM_SPEC` were already clean
  (no stale flat paths) — left untouched.

**Also fixed in the same pass — AGENTICS.md:** `docs/apps/AGENTICS.md` was already present before the
migration (one of the original 3 app docs, not part of the 18 moved) but carried the same stale flat
paths. It got the identical Glob-verified rewrite — mostly runtime-owned (`AINDY/agents/...`,
`AINDY/routes/...`), with `db/models/agent_run.py`/`agent_event.py` → `apps/agent/models/...`.

**Residuals (intentionally left, annotated inline in the docs):**
- `services/deepseek_arm_service.py` (FORMULA) and `db/models/agent_run_event.py` (ARM) resolve to no
  file in either repo (renamed/merged or never standalone) — carry `_(path unverified after split)_`.
- "Files to create" / roadmap tokens (e.g. `services/freelance/intake_service.py`,
  `services/reasoning/*`, `db/models/client_account.py`, `services/infinity_state_service.py`) carry
  `_(planned; not yet present)_` or sit under explicit "Potential files to create" headings — they
  describe future work, not moved code.
- Note: `services/flow_engine.py` (the most common stale token, ~13 refs) WAS resolved — the flow
  engine is a package, not a `flow_engine.py` basename; all refs now point at
  `AINDY/runtime/flow_engine/runner.py` (home of `PersistentFlowRunner`).

**Reopen trigger:** Any doc relying on an unverified residual token above, or live-code verification
of the `deepseek_arm_service` / `agent_run_event` references.

---

## DOCS-MIGRATION-2: shared pre-split docs — triaged and app slice extracted

**Status:** App-facing slice DONE (2026-06-27). Runtime-owned + deferred buckets recorded below.

**Context:** Beyond the 18 clearly app-owned docs (DOCS-MIGRATION-1), the archive held 17 docs that
the boundary review treated as "shared." A per-doc content analysis showed most are **runtime-owned**,
not app-owned — the apps-monolith slice was small. Disposition:

- **Bucket A — runtime-owned (NOT this repo; belong in `aindy-runtime`):** `architecture/DATA_MODEL_MAP.md`,
  `architecture/MODEL_OWNERSHIP_POLICY.md`, `platform/governance/AGENT_WORKING_RULES.md`,
  `platform/governance/ERROR_HANDLING_POLICY.md`, `platform/governance/CHANGELOG.md`, and all 4
  `tutorials/*` (they teach runtime primitives — memory bridge, flow WAIT/RESUME, scheduler, Nodus —
  no app-domain workflow). Tracked as a future `aindy-runtime` task; out of scope here.
- **Bucket B — stale/archive-only:** `platform/governance/NEXT_PHASE_PLAN.md` (completed pre-split
  sprint narrative). Not migrated.
- **Bucket C — app-facing slice extracted into this repo (DONE):**
  1. `docs/platform/engineering/TECH_DEBT.md` → the app-domain debt items it carried (a real
     tracking gap) migrated below as **APP-DEBT-MIGRATED-1**.
  2. `docs/architecture/ANALYTICS_BOUNDARY.md` → added as the app-owned half of the analytics boundary.
  3. `docs/api/CHANGELOG.md` → app-route (`/apps/*`, `/masterplans/*`, `/bridge/*`) history extracted
     into this repo's `docs/api/CHANGELOG.md`; runtime routes (`/platform/*`, `/agent/*`,
     `/observability/*`) left to the runtime changelog.
- **Bucket D — living governance (triaged 2026-06-27; author fresh, not copy-split):**
  - `platform/GOVERNANCE_INDEX.md` → **AUTHORED** fresh as `docs/GOVERNANCE_INDEX.md` (indexes
    only docs this repo owns; runtime contracts referenced as upstream authority).
  - `architecture/SYSTEM_SPEC.md` → **SKIP (redundant)** — app-facing content already covered by
    `ARCHITECTURE_MAP` + `BOOT_PROFILES` + `PLUGIN_REGISTRY_PATTERN` + `APPS_MONOLITH_REPO_SHAPE`;
    runtime content belongs to `aindy-runtime`.
  - `platform/governance/release_notes.md` → **ARCHIVE-ONLY** — completed pre-split sprint history;
    app release tracking starts fresh from the split (git history + `docs/api/CHANGELOG.md`).
  - `platform/governance/EVOLUTION_PLAN.md` → **PRODUCT CALL, deferred** — an app-domain roadmap is
    a human prioritization decision, not something to synthesize from a stale archive. Author fresh
    when app priorities are set.

**Status:** DOCS-MIGRATION-2 complete except the deferred **app EVOLUTION_PLAN** (product call) and the
**Bucket A** relocation task on `aindy-runtime` (handed off separately).

**Reopen trigger:** Deciding to author the app evolution plan/roadmap, or follow-up on Bucket A.

---

## APP-DEBT-MIGRATED-1: domain debt recovered from the pre-split register (2026-06-27)

**Status:** Tracked. Migrated from the pre-split `docs/platform/engineering/TECH_DEBT.md`
(triaged 2026-04-25) under DOCS-MIGRATION-2 Bucket C. These app-domain items were never carried into
this repo's register — a genuine tracking gap. Runtime/infrastructure items from the same source stay
with `aindy-runtime`. Verify each against current code before acting; the source triage is ~2 months old.

### APP-DEBT-MIGRATED-1a: Genesis session locking enforced only in application logic (production-blocking)

**Severity:** High  **Effort:** M  **Files:** `apps/masterplan/services/masterplan_factory.py`,
`apps/masterplan/masterplan.py`

`create_masterplan_from_genesis()` prevents double-locking by reading `GenesisSessionDB.status` in
application code, but the schema enforces no DB-level uniqueness/lock invariant for the
lock/plan-creation transition. Concurrent lock requests can create duplicate or inconsistent
masterplan state from one genesis session — a correctness bug in a primary planning workflow.
Fix: move the invariant into the DB transaction boundary (explicit constraint or row-locking).
Note: the constraint/migration surface may touch runtime-owned tooling — coordinate the
transaction-boundary contract with `aindy-runtime`.

### Deferred app-domain items

| Item | Domain | Effort | When to revisit |
|------|--------|--------|-----------------|
| Search orchestration not fully unified — LeadGen full-generation persistence, SEO meta generation, and richer provider-backed ranking still split from the shared `search_service` layer | search | M | before expanding search-heavy workflows or adding search providers |
| Freelance commercial workflow incomplete — payments/refunds/webhooks/idempotency exist, but broader fulfillment and subscription automation are not end-to-end | freelance | M | before exposing freelance as a primary revenue path |
| RippleTrace productization incomplete — execution-causality, graph edges, and UI exist; deeper insight generation, scenario coverage, and hardening do not | rippletrace | L | before using RippleTrace as a primary incident/audit surface |
| Masterplan dependency cascade + execution automation incomplete — anchor/ETA debt is closed; dependency-cascade modeling and execution automation are not | masterplan | L | before treating Masterplan as an autonomous planner |
| ARM low-risk config suggestions require manual apply — `auto_apply_safe` remains advisory, not auto-applied | arm | S | before positioning ARM as a self-tuning service |
| Infinity loop autonomy still shallow — memory-weighted and feedback-aware, but no deep threshold/weight learning and not a bounded autonomous controller | analytics | M | before enabling autonomous optimization decisions |
| Identity inference rules-only — observation exists; probabilistic/model-driven inference does not | identity | M | before expanding identity-driven personalization |
| SYLVA reserved agent namespace inactive — scaffolding only, agent unimplemented | agent | S | when the reserved agent is activated or removed |

**Reopen trigger:** Per-item "when to revisit" above, or substantial work in the named domain.
