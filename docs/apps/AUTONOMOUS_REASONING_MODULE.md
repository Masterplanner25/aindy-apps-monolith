# AUTONOMOUS REASONING MODULE (ARM)

> **Status update (2026-06-28).** Partly stale. The Infinity-loop decision logic
> was already cleanly separated as `infinity_loop._decide` (threshold branches +
> memory/system/goal/social weighting). **Phase 1 is now done**: that logic is
> extracted into a reusable, normalized, tested reasoning engine at
> `apps/analytics/services/reasoning/` (`state_evaluator` → `StateSnapshot`,
> `decision_engine.decide` → `ReasoningResult`); `infinity_loop._decide` is now a
> thin wrapper over it (behavior preserved). **Phase 2 is done**: a dedicated
> `reason()` service plus `strategy_selector` and `feedback_analyzer` compose the
> engine into one reusable "what should happen next?" entry, and the Infinity
> loop is now a *consumer* of it. **Phase 5 is done**: reasoning steps emit
> durable `reasoning.*` events via the runtime's registration/emission surface.
> **Phase 3 is done**: the agent planner consumes the reasoning recommendation
> (via the `analytics.reasoning_recommendation` job) and agent completion already
> triggers the orchestrator (now reasoning-backed), all through runtime
> registration hooks — no `AINDY/` edits.
>
> **Correction on "files to modify: `AINDY/...`".** The per-phase file lists below
> that name runtime files are an anti-pattern: apps extend the runtime through its
> registration surface (`AINDY.platform_layer.registry` — ~40 `register_*`/`emit*`
> hooks), they do not edit runtime code. Phases 3–5 are therefore **app-doable
> without touching `AINDY/`**: Phase 5 used `register_event_type` +
> `queue_system_event` (no `system_event_service.py` edit); Phase 3 uses
> `register_agent_planner_context` / `register_agent_completion_hook` /
> `register_agent_tool`; Phase 4 uses `register_flow` / `register_flow_strategy` /
> `register_execution_adapter`. Only a genuinely missing extension point would be
> a runtime feature request (added in `aindy-runtime`), never an app edit to
> runtime. The originally-listed memory-engine edits (`AINDY/runtime/memory/…`,
> `AINDY/memory/…`) are deferred to the runtime repo.

## 1. System Reality

### What this document means now

The existing codebase uses the name "ARM" for a code analysis and code generation subsystem exposed at `/arm/*` and implemented primarily in:

- `apps/arm/routes/arm_router.py`
- `apps/arm/services/deepseek/deepseek_code_analyzer.py`
- `apps/arm/services/arm_metrics_service.py`

That subsystem is real, but it is **not** the full autonomous reasoning layer A.I.N.D.Y. would need in order to decide what to do next across the system.

If "Autonomous Reasoning" is defined correctly as:

- evaluating system state
- interpreting memory and metrics
- selecting next actions
- adapting strategy over time

then the current system only implements this **partially**.

### What exists today

#### Implemented

- `apps/analytics/services/orchestration/infinity_orchestrator.py`
  - collects recent memory and KPI state
  - recalculates Infinity score
  - executes the loop decision step
  - emits `loop.started` and `loop.decision` events

- `apps/analytics/services/orchestration/infinity_loop.py`
  - contains the clearest existing system-level decision logic
  - evaluates recent feedback, KPI thresholds, incomplete tasks, and cooldown windows
  - outputs a `decision_type`, `adjustment_payload`, and `next_action`

- `AINDY/agents/agent_runtime.py`
  - generates plans for explicit user goals
  - injects Infinity KPI context into planning
  - triggers the Infinity orchestrator after successful completion

- `AINDY/runtime/flow_engine/runner.py`
  - contains lightweight strategy selection and strategy score updates for execution flows
  - compiles intent into executable internal flows

- `AINDY/runtime/memory/orchestrator.py`
  - performs memory retrieval strategy selection, scoring, and filtering
  - this is meaningful reasoning for memory recall, but not a general decision layer

- `AINDY/core/system_event_service.py`
  - provides durable event emission so some loop decisions are observable

#### Partially implemented

- Memory-informed decision making
  - the Infinity orchestrator reads recent memory before making a loop decision
  - the agent planner uses KPI context
  - ARM analysis uses memory recall and writes memory back
  - however, there is no dedicated reasoning service that treats memory as a first-class decision input across the platform

- Adaptive strategy selection
  - flow strategies and memory retrieval strategies exist
  - they are local optimization mechanisms, not a unified system-level reasoning engine

- Observability for decisions
  - some decisions are emitted as `SystemEvent`s
  - there is no dedicated reasoning event schema, no consistent explanation model, and no full trace of why decisions were made

#### Not implemented

- a dedicated autonomous reasoning service or module
- a normalized system-state evaluator
- a reusable decision engine that can choose actions for agents, loops, and workflows
- structured strategy selection beyond hard-coded heuristics
- reasoning output as a standard contract consumable by Agent Runtime and Nodus
- reasoning-driven Nodus workflow selection or compilation
- explicit reasoning events across all decision points

## 2. What the Current "ARM" Actually Is

The current `/arm` subsystem is best described as:

- a code analysis and generation engine
- backed by `DeepSeekCodeAnalyzer`
- instrumented with ARM-specific metrics
- connected to memory capture and Infinity score recalculation

It is **not** the platform's general autonomous reasoning layer.

That distinction matters:

- ARM today: reason about source code and return analysis or generated code
- Autonomous Reasoning target: reason about system state and choose what A.I.N.D.Y. should do next

The name has drifted away from the actual architecture.

## 3. Corrected Architecture

### Layer boundaries

#### Autonomous Reasoning Layer

Purpose:

- decide what should happen next
- evaluate current state, memory, metrics, and feedback
- choose next actions, priorities, and strategies

Target components:

- `state_evaluator`
- `decision_engine`
- `strategy_selector`
- `feedback_analyzer`
- `reasoning_event_emitter`

#### Execution Layer

Purpose:

- perform the work chosen by reasoning

Current execution components:

- `AINDY/agents/agent_runtime.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/runtime/nodus_adapter.py`
- `AINDY/runtime/nodus_execution_service.py`

#### Memory Layer

Purpose:

- provide recall, suggestions, outcomes, and learned signals

Current memory components:

- `AINDY/runtime/memory/orchestrator.py`
- `AINDY/memory/memory_capture_engine.py`
- `AINDY/memory/nodus_memory_bridge.py`

#### Event Layer / RippleTrace

Purpose:

- make decisions and execution visible as durable events

Current event components:

- `AINDY/core/system_event_service.py`
- `AINDY.db.models.system_event`
- `db.models.agent_run_event` _(path unverified after split)_

### Integration map

#### Autonomous Reasoning -> Agent Runtime

Target:

- reasoning selects or adjusts agent goals, priorities, and execution strategies

Current reality:

- limited
- `agent_runtime.generate_plan()` uses Infinity KPI context
- `agent_runtime.execute_run()` receives a post-execution `next_action` from the Infinity orchestrator
- agents are still mostly goal executors, not reasoning-driven autonomous actors

#### Autonomous Reasoning -> Nodus Execution Layer

Target:

- reasoning emits workflow intents or plans that compile into Nodus execution paths

Current reality:

- effectively absent
- `AINDY/runtime/nodus_adapter.py` is an internal flow adapter around `PersistentFlowRunner`, not primary Nodus VM orchestration
- `AINDY/runtime/nodus_execution_service.py` executes restricted embedded Nodus source, but this is isolated and not driven by a reasoning engine

#### Autonomous Reasoning -> Infinity Loop

Target:

- Infinity loop becomes one consumer of a reusable reasoning engine

Current reality:

- the Infinity loop is the main place where system-level reasoning currently lives
- its logic is rule-based and tightly coupled to loop execution and task adjustment

#### Autonomous Reasoning -> Memory Bridge

Target:

- memory is a primary input into state evaluation and strategy selection

Current reality:

- partial
- the Infinity orchestrator reads recent memory
- ARM analysis uses memory recall heavily
- memory retrieval itself has strategy selection
- there is no platform-wide reasoning contract that consumes memory uniformly

#### Autonomous Reasoning -> RippleTrace / SystemEvent

Target:

- every significant reasoning step emits observable, queryable decision events

Current reality:

- partial
- loop start and loop decisions are emitted
- many planning and selection decisions remain opaque or embedded in service-local logic

## 4. Relationship to Major Systems

### A. Agent Runtime

Reasoning influences agent execution only indirectly.

What is real:

- planner prompts include KPI context from Infinity scores
- approval and capability checks constrain execution
- completed agent runs trigger the Infinity orchestrator, which may return a `next_action`

What is missing:

- no dedicated reasoning service selecting agent goals
- no persistent strategy model influencing future agent plans
- no standardized reasoning output attached to agent runs before execution starts

### B. Nodus

Nodus is currently an execution concern, not a reasoning consumer.

What is real:

- embedded Nodus execution exists through `AINDY/runtime/nodus_execution_service.py`
- memory bridge functions are exposed to Nodus runtime

What is missing:

- no reasoning-to-Nodus plan contract
- no autonomous selection of `.nd` workflows
- no Nodus-first execution path for reasoning outputs

### C. Infinity Loop

The Infinity loop is the current de facto reasoning layer.

What is real:

- threshold-based decision rules
- feedback-aware branch selection
- task reprioritization and next-action generation
- throttling against repeated decisions

What is missing:

- modular reasoning components
- explainable state evaluation beyond simple rules
- reusable output for other orchestration paths

### D. Memory Bridge

Memory affects behavior, but not yet as a unified decision substrate.

What is real:

- recent memory is fed into the Infinity orchestrator
- memory retrieval uses strategy and scoring
- ARM recalls memory and records outcomes

What is missing:

- structured memory summaries for system-level decision making
- explicit memory-derived features for planning and action selection
- closed-loop learning from decision outcomes at the reasoning layer

### E. RippleTrace / SystemEvent

Decision observability exists, but only in fragments.

What is real:

- loop decisions are emitted as events
- execution events and failures are durable

What is missing:

- a reasoning event vocabulary
- decision explanation fields normalized across services
- traceability from observed state -> chosen strategy -> chosen action -> outcome

## 5. Gap Analysis

### Missing reasoning components

- dedicated autonomous reasoning service
- normalized state evaluator
- strategy selection service for system actions
- feedback analyzer tied to future decision policy
- reasoning output schema
- reasoning event schema

### Duplicated or scattered logic

- next-action logic in `apps/analytics/services/orchestration/infinity_loop.py`
- KPI-driven planning influence in `AINDY/agents/agent_runtime.py`
- strategy selection in `AINDY/runtime/flow_engine/runner.py`
- memory strategy selection in `AINDY/runtime/memory/orchestrator.py`
- ARM-specific suggestion logic in `apps/arm/services/arm_metrics_service.py`

These all represent local reasoning fragments, but they are not composed into a single reasoning layer.

### Implicit reasoning that is not formalized

- threshold evaluation of KPI health
- task reprioritization based on execution/focus conditions
- memory retrieval strategy choice
- strategy score updates in the flow engine
- ARM configuration suggestions from performance data

### Architectural inconsistencies

- "ARM" refers to a code-analysis subsystem, not the real platform reasoning layer
- the Infinity loop contains decision logic that should live in a reusable reasoning service
- Nodus exists as execution infrastructure but is not integrated with reasoning outputs
- reasoning decisions are only partially visible in RippleTrace/SystemEvent

## 6. The True Autonomous Reasoning Layer

The correct long-term design is a dedicated layer between state collection and execution.

### Inputs

- recent memory and memory summaries
- Infinity KPI snapshots
- task and workflow state
- recent `SystemEvent` and `AgentEvent` history
- execution outcomes and feedback
- capability and approval constraints

### Core components

#### State Evaluator

Responsibilities:

- aggregate KPIs, memory summaries, recent outcomes, pending work, and event context
- produce a normalized system-state snapshot

Primary files to introduce or refactor toward:

- `services/autonomous_reasoning_service.py` _(path unverified after split)_
- `services/reasoning/state_evaluator.py` _(path unverified after split)_

#### Decision Engine

Responsibilities:

- map state snapshots to a recommended next action
- support both deterministic rules and later learned policies

Primary files:

- `services/reasoning/decision_engine.py` _(path unverified after split)_

#### Strategy Selector

Responsibilities:

- choose execution strategy, workflow type, or escalation path
- unify concepts currently split across flow strategies and memory retrieval strategies

Primary files:

- `services/reasoning/strategy_selector.py` _(path unverified after split)_

#### Feedback Analyzer

Responsibilities:

- learn from outcomes, rejections, failures, task completion quality, and user feedback
- update decision policy inputs without embedding that logic separately in each service

Primary files:

- `services/reasoning/feedback_analyzer.py` _(path unverified after split)_

#### Reasoning Event Emitter

Responsibilities:

- emit observable reasoning records with:
  - input summary
  - chosen strategy
  - chosen action
  - explanation
  - confidence

Primary files:

- `services/reasoning/reasoning_events.py` _(path unverified after split)_
- `AINDY/core/system_event_service.py`

### Outputs

- `next_action`
- `decision_type`
- `priority_changes`
- `strategy_selection`
- `execution_intent`
- `explanation`
- `confidence`

## 7. Completion Plan

### Phase 1. Extract reasoning from the Infinity loop - DONE

Objective:

- separate decision logic from loop orchestration and persistence

**What shipped (2026-06-28):**

- New reusable engine `apps/analytics/services/reasoning/`:
  - `types.py` — `StateSnapshot` (normalized inputs + derived `kpi_health`) and
    `ReasoningResult` (`decision_type` + `payload`, with `reason`/`next_action`
    accessors and `to_tuple()`/`as_dict()`).
  - `state_evaluator.py` — `evaluate_state(...)` normalizes raw orchestrator
    context (KPI snapshot, feedback, memory/system/goal/social signals, KPI
    thresholds) into a `StateSnapshot`.
  - `decision_engine.py` — `decide(snapshot) -> ReasoningResult` holds the
    threshold/feedback branch logic + the memory/system/goal/social weighting
    refiners (extracted verbatim; behavior preserved).
- `infinity_loop._decide` is now a thin wrapper over `evaluate_state` + `decide`,
  preserving the legacy `(decision_type, payload)` contract; the loop keeps
  cooldown, persistence, and the DB-bound strategy-accuracy pass.

**Tests:** `tests/unit/test_infinity_reasoning.py` — characterization tests that
pin the legacy `_decide` behavior across every branch and weighting pass (so the
extraction is provably behavior-preserving), plus tests for the new
`evaluate_state`/`decide`/`ReasoningResult` contract.

Success criteria — met:

- loop decisions are generated by shared reasoning code (the engine), not
  service-local branching
- output is a normalized reasoning result object (`ReasoningResult`)

**Deferred:** the strategy-accuracy weighting stays in the loop (needs a DB
lookup) — a candidate for the Phase 2 `strategy_selector`/`feedback_analyzer`.
This engine is the foundation Freelancing Phase 5 and the broader reasoning layer
were gated on.

### Phase 2. Create a dedicated reasoning service - DONE

Objective:

- establish Autonomous Reasoning as a first-class system layer

**What shipped (2026-06-28):**

- `apps/analytics/services/reasoning/autonomous_reasoning_service.py` —
  `reason(...)`, the dedicated, input-driven "what should happen next?" entry. It
  composes `evaluate_state` + `decide` (Phase 1) with feedback analysis and
  strategy selection, and is reusable by any caller (not tied to the loop).
- `apps/analytics/services/reasoning/strategy_selector.py` —
  `apply_strategy_accuracy(...)`, the pure strategy-accuracy adjustment
  (penalize/boost/neutral) extracted from the loop's
  `_apply_strategy_accuracy_weighting` (the DB lookup stays with the caller).
- `apps/analytics/services/reasoning/feedback_analyzer.py` —
  `summarize_feedback(...)`, recent feedback rows → the standardized feedback
  context the engine reads.
- The Infinity loop is now a **consumer**: `run_loop` fetches context + the
  DB-backed strategy-accuracy history and calls `reason(...)`; the loop's
  `_get_recent_feedback_context` delegates to `summarize_feedback`. The removed
  `_apply_strategy_accuracy_weighting` now lives (pure) in `strategy_selector`.

**Runtime-owned (out of scope here):** the originally-listed edits to
`AINDY/runtime/memory/orchestrator.py` and `AINDY/memory/memory_capture_engine.py`
belong to the runtime repo; standardizing memory-derived signals at that layer is
deferred there.

**Tests:** `tests/unit/test_reasoning_service.py` — strategy selector
(unknown/penalize/boost/neutral), feedback analyzer (polarity, latest text, ORM &
dict rows), and the `reason()` service, including an equivalence test proving
`reason(...)` equals `decide(...)` then `apply_strategy_accuracy(...)` (so routing
the loop through the service is behavior-preserving).

Success criteria — met:

- one service (`reason`) answers "what should happen next?" for multiple callers
- score, feedback, memory, system, goal, and social inputs are consumed through
  one common interface (`StateSnapshot` via `evaluate_state`)

### Phase 3. Integrate with Agent Runtime - DONE

Objective:

- make reasoning influence agent execution before and after runs

**What shipped (2026-06-28) — app-side via registration hooks, no runtime edits:**

- Pre-execution: the app-owned planner-context provider
  (`apps/agent/agents/runtime_extensions.build_planner_context`, registered via
  `register_planner_context_provider`) now appends a **Reasoning Recommendation**
  block built from the `reason()` service, so plan generation is informed by
  reasoning outputs (not just raw KPI scores). It consumes the new
  `analytics.reasoning_recommendation` job through the job registry — decoupled,
  no cross-app import.
- The recommendation bridge: `apps/analytics/services/reasoning/recommendation.py`
  (`recommend_next_action`) maps a user's KPI snapshot to a compact reasoning
  recommendation; registered as the `analytics.reasoning_recommendation` job.
- Post-run: agent completion already runs through the app-owned completion hook
  (`handle_agent_run_completed`, `register_agent_completion_hook`) → the Infinity
  orchestrator, which is now reasoning-backed (Phases 1–2) and emits `reasoning.*`
  events (Phase 5). So the "what next action was derived afterward" trace exists.

**Tests:** `tests/unit/test_reasoning_recommendation.py` — the bridge
(stable/low-focus/no-snapshot), the job registration, and the planner block
formatting/empty-fallbacks.

Success criteria — met: plan generation uses reasoning outputs; post-run feedback
flows into the reasoning layer; the reasoning rationale is observable as events.

**Deferred (optional follow-up):** a `reasoning.evaluate` *agent tool* so an agent
can query reasoning mid-run. Skipped for now because a new tool requires a granted
capability (per `apps/agent/agents/capabilities.py`); without a grant, plans
referencing it would fail validation. This is a small, additive follow-up, still
app-side (`register_tool` + a capability grant).

### Phase 4. Integrate with Nodus workflows

Objective:

- make reasoning outputs drive Nodus-oriented execution rather than only internal flows

Files to modify:

- `AINDY/runtime/nodus_adapter.py`
- `AINDY/runtime/nodus_execution_service.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/memory/nodus_memory_bridge.py`

Potential files to introduce:

- `services/reasoning/nodus_compiler_adapter.py` _(path unverified after split)_
- `runtime/nodus/` _(path unverified after split)_ integration helpers if execution contracts need to be separated from existing services

Expected behavior:

- reasoning can output an execution intent that selects a Nodus workflow or compiles into one
- Nodus becomes a primary execution consumer of reasoning results rather than an isolated utility path

Success criteria:

- at least one autonomous reasoning outcome can execute through a Nodus-first path with durable traceability

### Phase 5. Add reasoning observability - DONE

Objective:

- make reasoning decisions inspectable through RippleTrace / SystemEvent

**What shipped (2026-06-28) — app-side only, no runtime edits:**

- `apps/analytics/services/reasoning/reasoning_events.py`: reasoning event type
  constants + `build_reasoning_records(...)` (pure) + `emit_reasoning_records(...)`
  (best-effort, never raises into the decision path, injectable queue).
- The four event types are registered via `register_event_type` in
  `apps/analytics/bootstrap.py`:
  - `reasoning.state_evaluated`
  - `reasoning.feedback_applied`
  - `reasoning.strategy_selected`
  - `reasoning.action_selected`
- The Infinity orchestrator emits the `state -> [feedback] -> [strategy] ->
  action` reasoning trace via `queue_system_event` right after `loop.decision`
  (no edit to `AINDY/core/system_event_service.py` — emission uses the runtime's
  existing surface). `feedback_applied` / `strategy_selected` are emitted only
  when those inputs shaped the decision.

**Tests:** `tests/unit/test_reasoning_events.py` — record building (presence/order,
loop-context summary, action fields), the injectable-queue emitter (kwargs,
counts, defensive on failure), and that the event types are registered at
bootstrap.

Success criteria — met:

- operators can trace state -> decision (-> execution -> outcome via the existing
  `loop.decision` / execution events) through durable `reasoning.*` events.

**Not done here (runtime repo):** richer reasoning emission from inside the agent
runtime / Nodus adapter is part of Phases 3–4; a dedicated reasoning event *model*
(vs. `SystemEvent` payload) is unnecessary for now.

## 8. Distinction Between Reasoning, Execution, Memory, and Events

### Reasoning

Decides:

- what to do next
- why that action should be chosen
- what strategy should be used

### Execution

Performs:

- workflows
- tool calls
- step completion
- task mutation

### Memory

Supplies:

- context
- prior outcomes
- reusable patterns
- recall candidates and suggestions

### Events / RippleTrace

Records:

- what was evaluated
- what was decided
- what was executed
- what happened afterward

## 9. Alignment with Other Roadmaps

### AGENTICS.md

This document aligns with `docs/apps/AGENTICS.md`:

- Agentics currently has execution infrastructure and a partial decision loop
- the reasoning layer is not complete
- Nodus is not yet the primary execution path for autonomous system behavior

### EVOLUTION_PLAN.md

This document aligns with `docs/apps/EVOLUTION_PLAN.md`:

- the platform can progress toward autonomous operation only after a real reasoning layer exists
- the reasoning layer should become the bridge between system state and execution

### TECH_DEBT.md

This document aligns with `docs/platform/engineering/TECH_DEBT.md`:

- reasoning debt is currently architectural, not cosmetic
- the main debt is fragmentation: decision logic is spread across loop logic, planner prompts, flow strategy code, and memory orchestration

## 10. Final Assessment

Autonomous Reasoning is **partially real**, but not as a formal module.

What is real today:

- a rule-based decision loop in `apps/analytics/services/orchestration/infinity_loop.py`
- KPI-informed orchestration in `apps/analytics/services/orchestration/infinity_orchestrator.py`
- local reasoning fragments in memory retrieval, flow strategy selection, and ARM-specific analytics

What is not real today:

- a dedicated, reusable autonomous reasoning layer
- reasoning-driven Nodus workflow execution
- full observability of decision rationale

The current `/arm` subsystem should be treated as a specialized code reasoning product surface, not as proof that the broader Autonomous Reasoning layer already exists.
