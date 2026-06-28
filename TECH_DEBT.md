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

## DOCS-MIGRATION-2: ~14 shared pre-split docs still need an editorial split

**Status:** Tracked, deferred (intentionally not moved in the 2026-06-27 pass).

**Context:** Beyond the 18 clearly app-owned docs (DOCS-MIGRATION-1), the archive holds ~14 docs that
span both runtime and app concerns and were flagged by `RUNTIME_DOCSET_BOUNDARY.md` for a deliberate
editorial split rather than a clean move: `architecture/{DATA_MODEL_MAP,ANALYTICS_BOUNDARY,MODEL_OWNERSHIP_POLICY,SYSTEM_SPEC}.md`,
`api/CHANGELOG.md`, `tutorials/*` (4), and several `platform/governance/*` files
(`AGENT_WORKING_RULES`, `CHANGELOG`, `ERROR_HANDLING_POLICY`, `EVOLUTION_PLAN`, `NEXT_PHASE_PLAN`,
`release_notes`, `GOVERNANCE_INDEX`). Each needs its app-facing portion extracted into this repo and
its runtime-facing portion left to / reconciled with `aindy-runtime`.

**Reopen trigger:** When one of these surfaces is needed app-side (e.g. an app-owned data model map
or analytics boundary reference), split that doc on demand rather than batch-migrating all 14.

**Estimated effort:** Per-doc; varies. Not a single sitting.
