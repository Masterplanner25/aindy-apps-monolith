---
title: "Runtime Feature Requests — handoff to aindy-runtime"
last_verified: "2026-07-17"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime Feature Requests — handoff to `aindy-runtime`

## What this is

Four items surfaced during the apps-monolith build that are **runtime-owned** — they
require editing `AINDY/` (the runtime), which this repo does not own. Per the split,
apps extend the runtime only through `register_*` hooks; a need the runtime doesn't
expose is a feature request against `aindy-runtime`, built + published there, then
adopted here.

Each request below is self-contained (a runtime dev needs no apps-monolith context to
act on it). **How to use:** file each as an issue in `aindy-runtime`, or fold into
`aindy-runtime/TECH_DEBT.md`. The `App-side adoption` section is the contract this repo
will consume once the runtime ships the capability — treat it as the acceptance target.

Cross-referenced from this repo's `TECH_DEBT.md` (the IDs match). Priority order:
**FR-3 (Next-Action) > FR-1 (connectors) > FR-2 (Nodus) > FR-4 (docs)**.

---

## FR-1 — Connector registration hook + capability-enforced outbound I/O

**apps-monolith ref:** `MASTERPLAN-CONNECTOR-RUNTIME-1` · **Priority:** Medium (hardening; delivery works today)

### Today (the limitation)
External automation connectors (`social`, `crm`, `email`, `webhook`, `stripe`,
`subscription`) are dispatched by a **hardcoded `if/elif` ladder** in a single app
service, `apps/automation/services/automation_execution_service.py::execute_automation_action`.
Each connector builds its own outbound HTTP/SMTP with stdlib (`urllib`/`smtplib`) and
wraps it in the runtime's `perform_external_call`
(`AINDY.platform_layer.external_call_service`) — which is an **observability wrapper
only**: it emits `external.call.started|completed|failed` and times the call, but does
**not** authorize, allow-list, rate-limit, sandbox, or vault credentials. There is no
`register_connector`-style hook in `AINDY.platform_layer.registry`.

### The ask (runtime)
1. **Connector registration hook** — `register_connector(connector_type: str, handler)`
   in the platform registry, pluggable like `register_router` / `register_syscall` /
   `register_job`, so connectors are runtime-dispatched and multiple apps can contribute
   types. Suggested handler shape: `handler(action: dict, ctx) -> dict`.
2. **Capability-enforced outbound boundary** — a real gate around external calls:
   per-user authorization, endpoint allow-lists, credential vaulting, and rate-limiting.
   Either `perform_external_call` grows enforcement, or a new `authorized_external_call`
   primitive layered above it.
3. **Shared outbound HTTP client** with retry + circuit-breaking, replacing app-side raw
   `urllib`.

### App-side adoption (the contract)
The app deletes its `if/elif` ladder and registers each connector via the hook; outbound
calls become authorized / allow-listed / rate-limited by the runtime; credentials are
resolved from a runtime vault rather than app config. No behavior change to *delivery* —
this is enforcement + pluggability.

### References
- App: `apps/automation/services/automation_execution_service.py` (dispatch ladder),
  `tests/unit/test_automation_connectors.py`.
- Runtime: `AINDY/platform_layer/external_call_service.py`, `AINDY/platform_layer/registry.py`.

---

## FR-2 — `register_nodus_workflow` hook for app-defined Nodus `.nd` workflows

**apps-monolith ref:** `APP-DEBT-MIGRATED-1` (Nodus-native reasoning row) · **Priority:** Medium/Low (only when Nodus is the primary substrate)

### Today (the limitation)
Nodus is the runtime's native workflow VM (it backs the `nodus_vm` agent-execution
backend, this monolith's default). Apps can register **Python flows** via `register_flow`,
and reasoning `execution_intent` runs through the flow engine. But there is **no
app-facing registration surface for native Nodus `.nd` workflow definitions** — apps
cannot contribute Nodus-native workflows, so reasoning/automation cannot execute on the
Nodus VM directly, only through the Python flow-engine path.

### The ask (runtime)
A `register_nodus_workflow(name: str, definition)` (or path-based) registration hook,
symmetric to `register_flow`, so an app can contribute a `.nd` workflow the runtime
compiles and executes through the Nodus VM. The registered workflow should be reachable
from the same intent-execution path apps already use (e.g. via a flow strategy or an
execution_intent target).

### App-side adoption (the contract)
The analytics reasoning layer (and any domain) registers a `.nd` workflow and routes a
reasoning/automation `execution_intent` to it, getting **Nodus-native, VM-executed,
durable** execution instead of the Python flow engine. Adopted behind the app's existing
`register_flow_strategy("reasoning", …)` seam.

### References
- App: `apps/analytics/services/reasoning/` (reasoning `execution_intent`),
  `apps/analytics/bootstrap.py::_register_flow_strategies` (the `register_flow` analog).
- Runtime: `AINDY/runtime/nodus_execution_service.py`, `AINDY/runtime/flow_engine/`,
  `register_flow` (the existing symmetric hook).

---

## FR-3 — Next-Action engine primitive: record-first → autonomous pre-dispatch

**apps-monolith ref:** `INFINITY-RUNTIME-1` Gap 4 (runtime board) · **Priority:** Medium/High (gates real autonomy)

### Today (the limitation)
The runtime is **record-first** for Next-Action. When an agent run completes, the app's
completion hook (`apps/agent/agents/runtime_extensions.py::handle_agent_run_completed`)
returns a runtime-coercible NextAction; the runtime **records** it as a `NEXT_ACTION_CHOSEN`
ledger event but does **not** autonomously dispatch it. So the Infinity loop can *decide*
"do X next," but nothing acts on that decision without a human. The engine primitive lives
runtime-side (`AINDY/core/next_action.py`). This is Gap 4 of the runtime's own
`INFINITY_LOOP_AUDIT.md` (the 5 structural loop-closure gaps).

### The ask (runtime)
A Next-Action **engine** that can, under a bounded policy, **autonomously dispatch** the
recorded next action (pre-dispatch control) — turning the record-first ledger into an
acting loop. It should expose:
1. a **policy/gate surface** so autonomous acting is bounded, opt-in, and auditable
   (aligns with the autonomy-controller pattern already used for scheduled triggers);
2. an **app-consumable dispatch-outcome contract** so the app can read what the runtime
   did with a chosen next action (from the `NEXT_ACTION_CHOSEN` → dispatch → outcome chain).

### App-side adoption (the contract)
The app returns a next action from its completion hook and, under the runtime policy, the
runtime executes it autonomously; the app reads the dispatch outcome from the ledger. This
unblocks the app's **Infinity autonomous-acting phase** (the `AINDY_NEXT_ACTION_ACTING`
frontier) and lets the app align its completion-hook return to the runtime NextAction
contract.

> **Disambiguation:** this is a *different* "Phase 2" from the learned-recursion Phase 2
> (which makes a learned model *drive canonical scoring* and is gated on the app-side
> **3b-full** values decision — see `docs/architecture/INFINITY_LEARNED_RECURSION_SCOPE.md`).
> FR-3 gates the **autonomous-acting** frontier, not learned scoring.

### References
- Runtime: `AINDY/core/next_action.py`, `docs/runtime/INFINITY_LOOP_AUDIT.md` (Gap 4),
  the `INFINITY-RUNTIME-1` entry in `aindy-runtime/TECH_DEBT.md`.
- App (context, resolved): `INFINITY-COMPLETION-HOOK-BOUNDARY-1` in this repo's
  `TECH_DEBT.md` (the boundary-preserving completion-hook contract shipped in
  aindy-runtime 1.6.1), `apps/agent/agents/runtime_extensions.py`.

---

## FR-4 — Docs relocation: Bucket A + the runtime half of `INVARIANTS.md`

**apps-monolith ref:** `DOCS-MIGRATION-2` · **Priority:** Low (hygiene; zero functional impact)

### Today (the limitation)
When the combined repo (`masterplan-infiniteweave-monday-node-2025-0411`) was split into
`aindy-runtime` + `aindy-apps-monolith`, a set of runtime-owned pre-split docs were
triaged but not yet relocated **into `aindy-runtime`**. They currently live only in the
pre-split archive.

### The ask (runtime)
Relocate/author into `aindy-runtime`, per the ownership map in
`aindy-runtime/docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`:

- **Bucket A (relocate as-is):** `architecture/DATA_MODEL_MAP.md`,
  `architecture/MODEL_OWNERSHIP_POLICY.md`, `platform/governance/AGENT_WORKING_RULES.md`,
  `platform/governance/ERROR_HANDLING_POLICY.md`, `platform/governance/CHANGELOG.md`, and
  all four `tutorials/*` (they teach runtime primitives — memory bridge, flow WAIT/RESUME,
  scheduler, Nodus — no app-domain workflow).
- **Runtime invariants (author):** the runtime half of `INVARIANTS.md` —
  PostgreSQL/UTC/session-isolation/memory-graph/embedding/schema-drift invariants. The
  **app-domain** half already lives in this repo at
  `docs/platform/governance/INVARIANTS.md` (original section numbers preserved for
  traceability); author the runtime half upstream and cross-link.

### App-side adoption (the contract)
None functional — once the runtime docset holds these, update the reciprocal cross-links.
This repo's `GOVERNANCE_INDEX.md` already references runtime contracts as upstream authority.

### References
- App: `DOCS-MIGRATION-2` in this repo's `TECH_DEBT.md` (full triage + bucketing).
- Runtime: `docs/runtime/RUNTIME_DOCSET_BOUNDARY.md` (ownership map), the pre-split archive.

---

## Coming back to apps-monolith

Once any of these ship in `aindy-runtime` (and the pin here is bumped if a floor change
is involved), the app-side adoption is the follow-on work in this repo:
- **FR-1** → replace the connector `if/elif` ladder with `register_connector` calls.
- **FR-2** → register the reasoning `.nd` workflow(s) behind the existing flow-strategy seam.
- **FR-3** → align the completion-hook return + build the app-side autonomous-acting phase
  (currently unscoped; scope it after the primitive lands).
- **FR-4** → update reciprocal doc cross-links.
