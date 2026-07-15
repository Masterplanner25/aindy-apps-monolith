---
title: "Build Plan — Shipping the Woken Decision Engine"
last_verified: "2026-07-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Build Plan — Shipping the Woken Decision Engine

## Where this comes from

This is the forward plan that follows the architecture review + validation pass
(2026-07-09 → 2026-07-15). Related material:

- **Strategic diagnosis** — the reconciled architecture map (artifact, v3): the
  built-vs-asleep ledger, the two re-tether frames, the agency ladder, and the
  validation band. It is the "why."
- **Code-structure reference** — [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md) (layers,
  boundaries, module list). It is the "what exists."
- This document is the "what we build next, in what order."

**One-line thesis.** A.I.N.D.Y. shipped a working Operator-grade *body* (execution,
continuity, orchestration) and left its reasoning *mind* dormant. This pass we
**woke the mind and proved it end-to-end**. The plan below ships that woken mind as a
first-class, user-facing capability and re-tethers the pillars back to the Infinity loop.

## The end state — "one face, delegated engines"

One conversational **face** in the product UI that routes user intent to the engines
behind it, rather than a chat that itself acts (cognition ≠ execution, per Agentics):

- *"form / revise my plan"* → the **Genesis** engine (plan-authoring state machine)
- *"do X"* → the **agent** engine (plan → approve → execute, streamed back)
- *"how am I doing"* → **Infinity** reads / the measurement surface
- later: social / freelance / search as callable capabilities

The face is the agent's mouth; Genesis / agent / Infinity are its faculties. Genesis
eventually folds in as a *mode* within the one conversation (it stays a structured
sub-flow — its state machine was a deliberate fix for the "infinite refinement loop").

## Validated foundation (2026-07-15) — what is already proven

The hard part is done and demonstrated, so the tracks below carry little backend risk:

- **The reasoner reasons** — flipping `AINDY_AGENT_PLANNER_BACKEND=anthropic_chat` yields a
  real multi-step, tool-diverse plan (6 steps) vs. the keyword heuristic's 1. (Tier 1 spike.)
- **Its plan executes to done** — a plan drives `register → create → approve → execute →
  completed` through `aindy-runtime serve` on Linux CI (the `serve-run-completion` /
  `runtime_local` green; the Claude planner reached `executing` in the in-process Tier 2).
- **The rails hold** — runtime **1.7.0** adopted; APP-DEPLOY-1 closed (`bootstrap-schema`
  deploy split + `ensure_pgvector`); the nodus wall-clock budget made tunable
  (`AINDY_NODUS_MAX_EXECUTION_MS`); standing CI guards (`deploy-bootstrap-guard`,
  `serve-run-completion`).
- **Honest edge** — the *Claude-planned* run to literal `completed` needs an environment
  with model egress + stable containers (self-hosted / cloud). GitHub-hosted runners cannot
  reach the LLM (RTR-1-NODUS-APPTOOL-500). The **mechanism** is proven; that last mile is
  infrastructure, not design.

## Tracks

### Track 1 — The face (MVP) ⭐ start here

A user-facing conversational/command surface in `client/` that dispatches to the agent
engine. Today the reasoner is **admin-only** (agent runs live in the `/platform` console);
a normal user has no way to talk to the mind we just woke. This closes that gap.

- **Backend: ready + proven.** `POST /apps/agent/run {goal}`, `GET /apps/agent/runs/{id}`,
  `POST /apps/agent/runs/{id}/approve`, `GET /apps/agent/runs/{id}/steps`,
  `GET /apps/agent/runs/{id}/events`, `GET /apps/agent/runs`. No new backend needed for the MVP.
- **Frontend: the build.** A console/chat in the *user* app (`client/src/…`, routed via
  `AppShell`, not `/platform`): submit a goal → render the plan → inline **approval gate** →
  stream steps + events → show the result. Envelope discipline: read outputs from `body.data`.
- **MVP interaction:** goal → `create` → show plan (`pending_approval`) → Approve → poll/stream
  `steps`/`events` to a terminal state → render result.
- **Dependency:** none. Works with either planner (heuristic or Claude); Track 2 makes it *reason*.
- **Status:** scoped + building (MVP). See the [Track 1 MVP build scope](#track-1--mvp-build-scope) appendix.

### Track 2 — Reasoner first-class (default)

Make the Claude planner the default instead of opt-in, with a cost/latency posture.

- Flip `AINDY_AGENT_PLANNER_BACKEND` default `runtime_local → anthropic_chat` in the deployed
  env; set `AINDY_CLAUDE_PLANNER_MODEL`; confirm the deploy image installs `anthropic`.
- **Dependency:** an environment with LLM egress (self-hosted runner / cloud). The face
  (Track 1) works regardless; this is what makes it actually reason for real users.
- **Status:** blocked on the egress env, not on code.

### Track 3 — Re-tether the pillars to Infinity

Restore the explicit "this feeds the loop" wiring the review found eroded/lost:

- Search's yield loop and Freelance's real revenue no longer flow into canonical Infinity;
  `analytics` (which *is* Infinity) is flagged `IS_CORE_DOMAIN=False`.
- Make `pillar → Infinity` and `app → runtime` lines explicit; do **not** un-generalize the
  platform — restore purpose, don't undo the split.
- **Dependency:** independent; can proceed in parallel.
- **Status:** not started; scoped per-pillar later.

### Track 4 — Quick wins (orphaned UI)

Wire the already-built-but-unrouted frontend the review surfaced: `InfiniteNetwork`,
`ProfileView`, `GenesisDraftPreview` (built, no route/importer). Cheap; independent.

### Track 5 — Fold Genesis behind the face

Move Genesis from standalone `/genesis` to a *mode* within the one conversation, keeping its
structured state machine (explore → confirm → draft → LOCK). Do this **last**, after Track 1
is proven — its logic survives; only its packaging dissolves.

## Sequencing

```
Track 1 (face MVP) ──► Track 5 (fold Genesis in)
      │
      └─ Track 2 (reasoner default)  — gated on an egress env
Track 3 (re-tether) ── parallel, independent
Track 4 (quick wins) ── parallel, cheap, anytime
```

**Recommended order:** Track 1 → (Track 4 alongside) → Track 2 when an egress env exists →
Track 3 in parallel → Track 5 last.

## Open decisions

- **Egress env for Track 2** — self-hosted GitHub runner vs. a cloud Linux box (both give the
  stable Docker + Anthropic egress the literal Claude loop needs).
- **Face surface shape** — dedicated console page vs. a persistent global command bar.
- **Streaming** — poll the run/steps endpoints for the MVP, or add SSE/websocket later.

## Track 1 — MVP build scope

The agent HTTP backend **and the frontend API client are already built** — `client/src/api/agent.js`
exposes `createAgentRun`, `getAgentRun`, `approveAgentRun`, `rejectAgentRun`, `getAgentRunSteps`,
`fetchRunEvents` (the admin `/platform` `AgentConsole.jsx` uses them). Track 1 is therefore a pure
frontend build over a proven, wired client — no new backend, no new API layer.

**Changes — one new file + two insertions:**

| File | Change |
|---|---|
| `client/src/components/app/Assistant.jsx` *(new)* | The face component — the whole MVP |
| `client/src/App.jsx` | `lazy(() => import("./components/app/Assistant"))` + a `<Route path="/assistant">` (mirrors `Genesis` / `TaskDashboard`) |
| `client/src/components/shared/AppShell.jsx` | Add `{ to: "/assistant", label: "Assistant" }` to the **user** nav group (`/agent` is taken by the `external` admin console) |

**Interaction (state machine):**

```
[goal] → createAgentRun({ goal })
  → poll getAgentRun(runId) until pending_approval → render the PLAN (steps + risk)
  → [Approve] approveAgentRun(runId)  /  [Reject] rejectAgentRun(runId)
  → poll getAgentRunSteps + fetchRunEvents → stream step statuses
  → terminal (completed / failed) → render result
```

Reuse `AgentConsole.jsx` + `AgentApprovalInbox.jsx` as the pattern reference. **Envelope
discipline:** read outputs from `body.data`, not the top level. Get the approve path right — the
"run stuck in `pending_approval` with no inbox entry" gap in `LIVE_VERIFICATION_SCOPE.md` is exactly
this path.

**Out of MVP scope** (later): SSE/websocket streaming (poll for now), tools browser, Infinity
"how am I doing" reads, Genesis-as-a-mode (Track 5).

**Definition of done:** a signed-in user visits `/assistant`, types a goal, sees the plan, approves
it, watches steps run, and sees the result — without touching `/platform`. Works today with
`runtime_local`; flip to Claude (Track 2) in an egress env and it *reasons*.

## References

- Reconciled architecture map (artifact, v3) — the strategic diagnosis + validation.
- [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md) — code-structure reference.
- [PLUGIN_REGISTRY_PATTERN.md](./PLUGIN_REGISTRY_PATTERN.md) — how apps extend the runtime.
- `TECH_DEBT.md` — APP-DEPLOY-1 (closed), RTR-1-NODUS-APPTOOL-500 (egress), NODUS-WARMPOOL-1.
