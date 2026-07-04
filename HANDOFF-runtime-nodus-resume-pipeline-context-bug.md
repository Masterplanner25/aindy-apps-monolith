# Bug report → aindy-runtime — nodus_vm resumed segment runs outside an ExecutionPipeline (RTR-1)

**From:** aindy-apps-monolith (RTR-1 §5 validation) · **Date:** 2026-07-04
**Runtime:** aindy-runtime **1.5.0** · **Backend:** `AINDY_AGENT_EXECUTION_BACKEND=nodus_vm` (opt-in)
**Severity:** blocks `nodus_vm` from ever becoming default; the resume/WAIT feature (RTR-1 Phase 2e) does not run to completion with the default execution contract enforced.

---

## Summary

Under `nodus_vm`, a plan that parks on a mid-plan WAIT step never runs to completion
after it is resumed. The scheduler dispatches the resume callback, but the **resumed
segment executes with no enclosing `ExecutionPipeline` context**. When the segment's
inner pipeline emits `execution.started`, the execution-contract guard
(`ENFORCE_EXECUTION_CONTRACT=True`, the default) raises, the exception is swallowed,
and the `AgentRun` is left stranded in `executing`.

This is independent of the client harness — it reproduces with a **live scheduler**
too. A running server fixes event *delivery* but not the missing *pipeline context*.

## Observed

```
RuntimeError: ExecutionContract violation:
  execution event 'execution.started' emitted outside pipeline
  at AINDY/core/system_event_service.py:453
  from AINDY/core/execution_pipeline/pipeline.py:326 (_safe_emit_event)
[Pipeline] EU->waiting eu_id=... wait_for=unknown   (core/execution_pipeline/shared/waits.py:81)
```

The run stays `status="waiting"` (test harness, no scheduler) or gets stranded in
`executing` then swept by `_recover_stuck_flow_runs` (live server).

## Reproduce

1. `AINDY_AGENT_EXECUTION_BACKEND=nodus_vm`, `AINDY_AGENT_WAIT_BEFORE_HIGH_RISK=true`,
   live Postgres.
2. Create an agent run whose plan has a high-risk step (e.g. the app `stub` planner's
   canned high-risk `memory.recall` step). `apply_wait_policy` inserts a
   `wait_for: agent.approval.granted` before it; the run parks at `status="waiting"`.
3. Approve, then POST the resume action (publishes `agent.approval.granted` scoped to
   the run's correlation).
4. The resume callback is dispatched, the segment raises the RuntimeError above, and
   the run never completes.

Full app-side harness: `aindy-apps-monolith` →
`tests/integration/test_nodus_vm.py::TestNodusVmWaitResume` +
`.github/workflows/nodus-vm-integration.yml` (currently `xfail`ed on this bug), and
`TECH_DEBT.md` → `RTR-1-NODUS-COMPLETION`.

## Root cause (file:line, runtime 1.5.0)

The resume path is scheduler-driven and never establishes a pipeline/async context:

- `kernel/event_bus.py:516-557` — `publish_event` → `notify_event(..., broadcast=True)`.
- `kernel/scheduler/waits.py:74-143` — `notify_event` matches waiters and
  **enqueues** `_enqueue_resume(run_id, callback, entry)` (line 120); does not run it.
- `kernel/scheduler/core.py:57-95` — `_enqueue_resume` → `enqueue` appends a
  `ScheduledItem`.
- `kernel/scheduler/dispatch.py:14-85` — `SchedulerEngine.schedule()` drains the queue
  and calls `_dispatch(stub, item.run_callback, context)` (line 57).
- `core/execution_dispatcher.py:386-456` — `dispatch()`. For the resume
  `_ResumedEUStub(type="agent")`, `_decide_mode` (136-201) returns **INLINE** (unless
  `AINDY_ASYNC_HEAVY_EXECUTION=1`), so `handler_fn()` is called directly (line 424)
  with **no pipeline wrapper and no context activation**. The ASYNC branch
  (445-456) uses `copy_context().run` on a thread pool and also sets no
  pipeline/async marker.
- `runtime/nodus_execution_service.py:538-621` — the callback `_resume` claims the run
  (`waiting → executing`, 566-571) then calls `_execute_agent_segment_chain` (602);
  `711-853` — chain → `_run_agent_segment_flow` (751) → `run_nodus_script_via_flow`
  (482) → `get_dispatcher().dispatch("sys.v1.nodus.execute", ...)` (239).
  **None of `_resume` / `_execute_agent_segment_chain` / `_run_agent_segment_flow`
  call `set_pipeline_active`, `activate_async_execution_context`, or
  `execute_with_pipeline`.**

Contrast the **initial** run, which enters through the route →
`core/execution_helper.py:46-47` `ExecutionPipeline().run(ctx, handler)` (via
`execution_service.py:68`), so `pipeline_active` is set for the whole initial call tree.

The guard and why it fires:

- `core/system_event_service.py:448-454` — for `execution.*` events:
  `if not is_pipeline_active() and not is_async_execution_active() and
  settings.ENFORCE_EXECUTION_CONTRACT: raise RuntimeError(...)` (453).
- Both flags are **ContextVars** (`platform_layer/trace_context.py:10,56-65`;
  `platform_layer/async_execution_context.py:5-22`) — not visible to a
  scheduler-dispatched callback that starts a fresh logical context.
- Ordering quirk: `ExecutionPipeline.run` emits `execution.started`
  (`core/execution_pipeline/pipeline.py:109-114`) **before** it sets `pipeline_active`
  (line 116). So a *root* pipeline's own `execution.started` passes the guard only if
  an **enclosing** pipeline already set `pipeline_active`, or `is_async_execution_active()`
  is True. The resumed segment has neither.
- `ENFORCE_EXECUTION_CONTRACT` defaults **True** (`config.py:283`) and the validator
  does **not** relax it for tests (`config.py:189-192`).
- Swallowed: `nodus_execution_service.py:851-853` catches and returns
  `{"status":"FAILED"}` **without updating `AgentRun`** → stranded in `executing` →
  later swept by `_recover_stuck_flow_runs` (`platform_layer/scheduler_service.py:256-304`).

## Why a live server does NOT fix it

A live server (`ENV=production`, `AINDY_ENABLE_BACKGROUND_TASKS=true`) starts the 1s
scheduler heartbeat (`platform_layer/scheduler_service.py:192-200,355-365`), so the
queued resume callback **is** dispatched — fixing delivery. But the callback still runs
INLINE in the heartbeat thread with no enclosing pipeline (above), so the guard still
fires. The only config that "works" today is `ENFORCE_EXECUTION_CONTRACT=false`, which
downgrades the guard to a warning — not an acceptable default.

## Proposed fix

Wrap the resumed segment in an `ExecutionPipeline` / `execute_with_pipeline` (or
activate the async-execution context) so the continuation runs *inside pipeline*, the
same way the initial run does. Candidate seam: `_build_agent_resume_callback._resume`
or `_execute_agent_segment_chain` in `runtime/nodus_execution_service.py` — establish
the context before `execution.started` is emitted by the inner segment pipeline.

Secondary: on failure, `_execute_agent_segment_chain` (851-853) should mark the
`AgentRun` failed rather than leaving it in `executing`, so stranded runs surface
promptly instead of waiting for the stuck-run sweep.

## Validated on the app side (for context)

The rest of the RTR-1 §5 surface is confirmed working on live Postgres (runtime 1.5.0):
plan generation under `nodus_vm`, WAIT parking (`status="waiting"` with
`wait_state`/`correlation_id`/`granted_tools`), the app-owned resume route publishing
`agent.approval.granted`, and **app-tool resolution inside the nodus_worker
subprocess** (no `"tool not found"` — the app manifest loads there). Only
execute-to-completion is blocked, by this bug.
