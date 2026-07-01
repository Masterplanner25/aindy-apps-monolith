---
title: "Masterplan SaaS - Canonical Definition & Evolution Plan"
last_verified: "2026-06-30"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Masterplan SaaS - Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Masterplan SaaS layer is A.I.N.D.Y.'s execution-strategy surface. It is not a
general automation SaaS. It is a **Masterplan trajectory engine** that:

- captures a strategic plan (Genesis -> MasterPlan)
- enforces lifecycle (draft -> lock -> activate)
- measures execution as time-compression against a declared target state
- prioritizes dependency resolution to compress downstream timelines

---

## 2. Core Lifecycle (Canonical Pipeline)

```text
Genesis -> MasterPlan -> Lock -> Activate -> Execute -> Measure -> Reproject
```

---

## 3. Core Components

### 3.1 Genesis (Plan Formation)

**Implementation:**
- `routes/genesis_router.py`
- `services/genesis_ai.py`
- `services/masterplan_factory.py`

**Current Capabilities:**
- guided strategic draft
- synthesis + audit
- lock into MasterPlan

---

### 3.2 MasterPlan Artifact

**Implementation:**
- `routes/masterplan_router.py`
- `db/models/masterplan.py`

**Current Capabilities:**
- versioned plan records
- posture classification
- activation state

---

### 3.3 Execution Tracking

**Implementation:**
- `routes/task_router.py`
- `services/task_services.py`
- `routes/analytics_router.py`

**Current Capabilities:**
- task tracking
- analytics ingestion
- basic dashboard overview

---

## 4. Current Implementation (Reality)

**Implemented:**
- Genesis session lifecycle (create -> message -> synthesize -> audit -> lock)
- MasterPlan creation and activation
- MasterPlan anchor fields and update endpoint
- ETA projection endpoint and dashboard panel
- Task CRUD + analytics ingestion
- dependency persistence and DAG-based blocking/unlock behavior
- MasterPlan-linked task generation and automation dispatch
- basic dashboards

**Missing or Drifted vs Masterplan Module docs:**
- ETA projection is now plan-scoped and cascade/critical-path aware (2026-06-30);
  the remaining gap is continuous-time / per-task-duration compression (tasks are
  count-based today)
- external automation connectors remain partial beyond the internal automation layer

---

## 5. Doc -> Code Parity Table

| Documented Capability | Evidence in Docs | Implementation Reality | Status | Primary Files |
| --- | --- | --- | --- | --- |
| Genesis -> MasterPlan lifecycle | Masterplan Genesis Module | Implemented | Implemented | `routes/genesis_router.py`, `services/masterplan_factory.py` |
| MasterPlan activation | Genesis Module | Implemented | Implemented | `routes/masterplan_router.py`, `client/src/components/MasterPlanDashboard.jsx` |
| Masterplan anchor / target state | Masterplan Plans doc | Anchor fields, endpoint, and UI are implemented | Implemented | `db/models/masterplan.py`, `routes/masterplan_router.py`, `client/src/components/MasterPlanDashboard.jsx` |
| ETA projection / timeline compression | Masterplan Plans doc | Plan-scoped, cascade/critical-path-aware projection (critical-path depth imposes a sequential floor over flat velocity); continuous-time duration modeling is still simplified | Implemented (cascade-aware) | `apps/masterplan/services/eta_service.py`, `apps/masterplan/routes/masterplan_router.py`, `client/src/components/app/MasterPlanDashboard.jsx` |
| Dependency cascade model | Masterplan Plans doc | Dependency metadata, DAG construction, blocked-task enforcement, and downstream unlock behavior exist | Implemented | `db/models/task.py`, `services/task_services.py` |
| Execution automation layer | Masterplan SaaS docs | MasterPlan can generate tasks and dispatch bound automation through the execution layer; external connectors remain partial | Partial | `routes/masterplan_router.py`, `services/masterplan_execution_service.py`, `routes/automation_router.py` |
| Execution analytics dashboard | SaaS docs | The MasterPlan surface now shows plan-scoped cascade execution metrics directly (basis, critical-chain depth, ready/blocked); a dedicated cross-plan execution/compression dashboard is still not built | Partial | `routes/analytics_router.py`, `routes/dashboard_router.py`, `client/src/components/app/MasterPlanDashboard.jsx` |

---

## 6. Gap -> File Mapping

| Gap | Impact | Files to Update |
| --- | --- | --- |
| ETA projection is flat velocity-based only — RESOLVED (2026-06-30): now plan-scoped + cascade/critical-path aware (`apps/masterplan/services/eta_service.py`). Remaining: continuous-time/duration-based compression (tasks are count-based today, no per-task durations) | Compression now reflects dependency depth, not just raw counts | `apps/masterplan/services/eta_service.py` |
| External automation connectors are still partial | Internal automation exists, but external social/CRM/payment surfaces are not fully connected | `routes/automation_router.py`, related automation services |

---

## 7. Risk Register

| Risk | Type | Failure Mode | Impact | Likely? |
| --- | --- | --- | --- | --- |
| Masterplan drift | Product | Plans exist without dependency-aware trajectory signal | Core value missing | High |
| Docs vs runtime mismatch | Product | SaaS docs understate implemented anchor/ETA features and overstate execution depth | Expectation gap | High |
| Projection still under-models dependency cascade | Technical | Mitigated (2026-06-30): ETA now uses critical-path depth (a sequential floor) and is plan-scoped; residual gap is per-task duration modeling | Weak projection quality | Low |
| External automation connectors are partial | Business | Execution SaaS promise is only partly fulfilled | Revenue risk | High |

---

## 8. System Classification

The Masterplan SaaS layer is currently:

> A strategic planning + activation system with dependency-aware task execution
> and internal automation binding, but still partial compression modeling and
> incomplete external automation surfaces.

---

## 9. Evolution Plan (System Roadmap)

### Phase v1 - Persist Dependency Structure
**Goal:** make execution order real  
**Actions:**
- persist task dependencies in the task model ✅
- carry dependencies through task creation and retrieval ✅

### Phase v2 - Timeline Compression Output
**Goal:** make TWR actionable  
**Actions:**
- compute dependency-aware ETA shift per task batch
- return updated projection from execution endpoints

### Phase v3 - Dependency Awareness
**Goal:** encode upstream constraint removal  
**Actions:**
- add dependency-aware task ordering ✅
- include cascade impact in projection and execution feedback

### Phase v4 - Automation Surface
**Goal:** convert planning into execution  
**Actions:**
- add automation integration layer (social, CRM, payments) — partial

---

## 10. Next Steps

### Step 1 - Deepen cascade impact in projection - DONE
**Files:** `apps/masterplan/services/eta_service.py` (+ `apps/analytics/services/scoring/infinity_service.py` consumes the output)  
**Outcome:** ETA is now **plan-scoped** (fixed a bug where it counted tasks
user-wide) and **cascade-aware**. `calculate_eta` pulls the dependency graph via
the existing `sys.v1.tasks.get_graph_context` syscall, scopes to the plan's tasks
by `masterplan_id`, and projects with `_project_days` = `max(remaining/velocity,
critical_depth / min(velocity, 1.0))` — so the longest remaining dependency chain
imposes a sequential floor that flat throughput can't beat. Completing a blocking
task shortens that chain (`critical_depth`) and shifts the projection earlier. The
result now also surfaces `critical_depth`, `blocked_tasks`, `ready_tasks`, and
`projection_basis` (`cascade` | `velocity` | `insufficient_data`). It degrades
gracefully to the legacy flat-velocity estimate when the graph is unavailable.
The infinity `masterplan_progress` KPI (which reads `plan.days_ahead_behind`)
improves for free — no change needed there.

**Tests:** `tests/unit/test_masterplan_eta_cascade.py` — cascade math, plan
scoping + critical-depth derivation, the integration path (cascade vs velocity
fallback), and missing-plan handling.

### Step 2 - Expose MasterPlan execution metrics directly - DONE
**Files:** `client/src/components/app/MasterPlanDashboard.jsx`,
`client/src/components/app/TaskDashboard.jsx`,
`client/src/context/MasterplanProjectionContext.jsx`, `client/src/App.jsx`  
**Outcome:** the active plan's ETA panel now surfaces the Step-1 cascade metrics
directly on the MasterPlan surface rather than relying on generic dashboard views.
The projection endpoint (`get_masterplan_projection` → `calculate_eta`
pass-through) already returns the cascade fields, so surfacing them is purely the
consuming UI: the `ETAProjectionPanel` renders a **`cascade`** basis chip when the
projection is dependency-aware, a **critical-chain depth** line (`{critical_depth}
deep`, shown only when the chain is longer than one), and a **`{ready} ready ·
{blocked} blocked`** line — alongside the existing velocity / ahead-behind
metrics. It degrades cleanly on the velocity fallback (no chip, no critical-chain
line).

The panel also consumes the **Step-3 completion-response projection reactively**.
Task completion returns the recomputed cascade projection under
`orchestration.masterplan_projection`, but the task surface and MasterPlan surface
are separate lazily-loaded routes that never mount together, so that projection
was previously discarded until the panel refetched on its own. A small
`MasterplanProjectionProvider` context (mounted above the app shell, so it
survives navigation between `/tasks` and `/masterplan`) now carries it: the task
surface publishes the projection on completion, and the ETA panel adopts it — a
pushed projection takes precedence over the panel's own fetched baseline, with no
refetch.

**Tests:** `client/src/test/masterplan-dashboard.test.jsx` — cascade metrics
render on the active plan, and the chip + critical-chain line are omitted on the
velocity fallback. `client/src/test/masterplan-projection-reactive.test.jsx` —
completing a task reactively updates the MasterPlan panel to the fresh cascade
projection (no second projection fetch), and leaves it untouched when completion
carries no reprojection.

### Step 3 - Return MasterPlan reprojection from task completion flows - DONE
**Files:** `apps/tasks/services/task_service.py`  
**Outcome:** task completion now returns the refreshed MasterPlan projection.
`orchestrate_task_completion` already recomputed the active plan's ETA but
discarded it; it now captures the (cascade-aware, Step 1) projection via the
extracted `_recalculate_active_masterplan_eta` helper and includes
`masterplan_id` + `masterplan_projection` in its result. That result already
propagates to the `/tasks/complete` response under `task_orchestration` (the
`task_orchestrate` flow node merges the syscall data via `output_patch`, and
`_flow_envelope` returns the full flow data), so **no flow/route changes were
needed** — completing a task surfaces fresh projection data (velocity, ETA,
days ahead/behind, critical_depth, projection_basis) for the MasterPlan surface
to consume.

**Tests:** `tests/unit/test_task_completion_reprojection.py` — the capture helper
(active plan / no plan / no anchor / failure) and the orchestration return
contract carrying the projection keys.

### Step 4 - Extend external automation connectors
**Files:** `routes/automation_router.py`, related automation services/models  
**Outcome:** the existing MasterPlan-linked automation layer reaches external social/CRM/payment surfaces rather than remaining mostly internal.

---

## 11. Technical Debt

Masterplan layer debt is tracked in:
- `docs/platform/engineering/TECH_DEBT.md`

---

## 12. Governance Notes

- This document is the canonical reference for the Masterplan SaaS layer.
- Any changes must also update:
  - `docs/architecture/SYSTEM_SPEC.md`
  - `docs/interfaces/API_CONTRACTS.md`
  - `docs/apps/EVOLUTION_PLAN.md`

---

## 13. Summary (Operational Truth)

The Masterplan SaaS layer currently implements **planning, locking, activation,
anchor setting, dependency-aware task execution, plan-scoped cascade/critical-path
ETA projection, and internal automation binding**. The remaining gaps are
**continuous-time (per-task-duration) compression modeling** and complete external
automation coverage. The system's core promise (execution as timeline
compression) is now represented concretely through dependency-aware projection,
though duration-based modeling and external connectors are not yet complete.
