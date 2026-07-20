---
title: "Frontend Walk Log — live user-path walkthrough"
last_verified: "2026-07-19"
api_version: "1.0"
status: current
owner: "app-team"
---

# Frontend Walk Log

Running record of the live frontend walkthrough — clicking the app as a real user, on the
real stack, and writing down what a user would actually experience.

This is deliberately broader than a bug list. It captures three kinds of finding:

- **Defect** — something is broken and should be fixed.
- **Design** — the app behaves as built, but the behavior is worth a decision.
- **Papercut** — small friction that isn't wrong, just costs the user something.

Entries stay here until they are fixed, filed upstream, or explicitly declined.

**Environment:** `aindy-runtime==1.10.2` · native `docker.io` in WSL2 Ubuntu · pgvector/pg16 ·
client on Vite dev server at `localhost:5173` proxying to the API at `localhost:8000`.

---

## Open

| # | Kind | Area | Item | Status |
|---|---|---|---|---|
| 1 | Design | Genesis | AI interrogates but never contributes ideas | decision needed |
| 2 | Papercut | Genesis chat | Enter inserts a newline instead of sending | ready to fix |
| 3 | Defect | masterplan / memory | A 404 surfaces to the user as "Internal Server Error" | diagnosed, unfixed |
| 4 | Defect | network | `InfiniteNetwork` calls `/api/users`, which no route serves | diagnosed, unfixed |
| 5 | Defect | Genesis | Leaving the page abandons the session; transcript is never stored | diagnosed, decision needed |

---

### 1. Genesis asks, but never offers — `Design`

**Observed:** working through Genesis, the user has to think of everything. The AI prompts
and probes, but never proposes options or contributes ideas back.

**Why:** this is written into `GENESIS_SYSTEM_PROMPT`
(`apps/masterplan/services/genesis_ai.py`). Its only three behavioral rules are:

```
- Responses must be 2–4 lines maximum.
- Ask clarifying questions when mechanism logic is missing.
- Extract structured signals from user input.
```

Nothing authorizes proposing or suggesting. The 2–4 line cap is the binding constraint —
there is no room to offer options *and* ask a question, so even a model inclined to
contribute gets squeezed into asking.

**Structural shape:** contribution isn't missing, it's *back-loaded*. `SYNTHESIS_SYSTEM_PROMPT`
does all the generating (phases, success criteria, risk factors, ambition score). The design is
**conversation = extraction, synthesis = generation**. The felt problem is that all generative
value sits behind a wall the user only reaches at the end.

**The part that looks unintentional:** before every turn `call_genesis_llm` recalls prior
strategic memories via `MemoryOrchestrator`, plus ARM and identity context, and injects it all
into the system prompt — but the prompt never tells the model to *use* that context to
contribute. Retrieval is paid for, and its only sanctioned use is asking a better question.
That is where the plumbing and the prompt disagree.

**Tradeoff (why this isn't an obvious fix):**

- *Keep extractive:* if the AI proposes a mechanism, users anchor on it, and a plan you were
  led to isn't one you own. Worse, mid-conversation suggestions would contaminate
  `state_update` — the model would extract signals it authored as though the user said them,
  inflating `confidence` on its own ideas. Synthesis is currently the only place inference is
  labelled as inference (`synthesis_notes`).
- *Add contribution:* Genesis is one-time, high-stakes onboarding. A user who doesn't know
  what's possible can't answer "what's your mechanism?", and if they stall there they never
  reach synthesis at all.

**Proposed middle path (if changed):** contribute only when the user is stuck, and don't
launder it as theirs — offer 2–3 options when `confidence` hasn't moved across turns, mark them
as the AI's, and don't write suggested content into `state_update` unless the user affirms it.
Preserves ownership and provenance. Cost: a prompt change plus a small state-update guard.

**Status:** design decision for the owner. Not scheduled.

---

### 2. Enter doesn't send in the Genesis chat — `Papercut`

**Observed:** pressing Enter in the chat box drops to a new line instead of sending. Sending
requires clicking SEND.

**Why:** `client/src/components/app/Genesis.jsx` renders a bare `<textarea>` with **no
`onKeyDown` handler** (~line 225). Enter therefore does its native newline, and the form only
submits via the SEND button. Not a bug — nothing is broken — but it breaks the chat convention
users arrive with.

**Fix:** `Enter` submits, `Shift+Enter` newlines — the standard for chat inputs. Guard on
`loading` so Enter can't double-submit mid-request, and keep the multi-line affordance since
Genesis answers are often long.

**Status:** ready to fix, small and self-contained.

---

### 3. A 404 surfaces as "Internal Server Error" — `Defect`

**Observed:** hitting a stale/absent masterplan or memory-trace link returns a 500 rather than
a not-found.

**Why:** app routes that raise `HTTPException` *before* entering the execution pipeline have
their status replaced. The runtime's `route_execution_guard` catches every exception —
including `fastapi.HTTPException`, which is legitimate control flow — and converts it into a
`RouteExecutionViolation` (500) when no execution context was entered. The runtime's own log
names the condition: `endpoint raised HTTPException before pipeline entry`.

The runtime is enforcing its ExecutionContract correctly; the violation is app-side. Within
`masterplan_router.py` the patterns are inconsistent — `lock_from_genesis` uses the pipeline,
while `get_masterplan` calls `_run_flow_masterplan` → `run_flow()` directly and never enters it.

**Confirmed affected:** `/apps/masterplans/{plan_id}`, `/apps/memory/traces/{trace_id}`.
Contrast (correct, inside the pipeline): `/apps/agent/runs/{id}` → 400,
`/apps/freelance/metrics/latest` → 404.

Three further routes 500 on malformed UUIDs rather than 422:
`/apps/rippletrace/event/{id}/upstream`, `.../downstream`,
`/apps/coordination/runs/{id}/children`.

**Note:** file-level static analysis cannot enumerate these — every file that raises
`HTTPException` *also* contains pipeline usage, so the violation is per-route. The empirical
sweep is the reliable detector.

**Status:** diagnosed, unfixed. Cosmetic for the happy path; misleading when hit.

---

### 4. `InfiniteNetwork` calls a route that doesn't exist — `Defect`

**Observed:** `/network` surface fails to load users.

**Why:** `client/src/components/app/InfiniteNetwork.jsx` falls back to `"/api/users"` when
`VITE_NETWORK_API_URL` is unset. No backend route serves `/api/users` — the only user-listing
route is `/platform/admin/users`, which is admin-gated. This is independent of the dev-proxy
prefix handling; it 404s either way.

**Status:** diagnosed, unfixed. Needs a decision: point at a real route, gate the surface, or
require the env var.

---

### 5. Genesis doesn't survive leaving the page — `Defect`

**Observed:** navigated away from Genesis and back. It asked to initialize again, the whole
chat was gone, and no plan had been created.

Three separate problems sit underneath that, and they need separate answers.

**a) `POST /genesis/session` always creates a new session — it never resumes.**
Verified: two POSTs for the same user returned `session_id=7` then `session_id=8`, and the DB
now holds *two rows both `status=active`* for that user. So returning to the page orphans the
previous session and starts over. Duplicate active sessions also accumulate silently, which is
a data-integrity problem independent of the UX.

```
 id | status | synthesis_ready | has_state
----+--------+-----------------+-----------
  7 | active | f               | t
  8 | active | f               | t
```

**b) The progress itself was NOT lost — only orphaned.** Session 7 still holds its extraction:

```json
{"vision_summary": "Run an AI consulting studio", "time_horizon": "5 years", ...}
```

`GET /apps/genesis/session/7` returns it intact (`status`, `summarized_state`,
`synthesis_ready`, `draft_json`). So the plan state survives a page change today — it is simply
unreachable, because nothing resumes it.

**c) The transcript is genuinely unrecoverable.** `genesis_sessions` has no message column at
all — `id, user_id, status, summarized_state, synthesis_ready, draft_json, locked_at,
created_at, updated_at`. Only the *distilled* state is persisted, never the conversation. No
client fix can restore the messages; that needs a schema change.

**Client side:** `getGenesisSession()` exists in `client/src/api/masterplan.js` but is **never
called anywhere**. The client also never persists `session_id`, and there is no
"get my active session" route — so resuming needs either client-side id storage or a new
backend lookup.

**Fix options, cheapest first:**

1. **Make session creation idempotent** — return the user's existing `active` session instead
   of creating another. Restores progress on return, stops orphan accumulation, and needs no
   schema change or client state. Highest value per unit of risk.
2. **Resume on mount client-side** — call `getGenesisSession()` and rehydrate the extracted
   state, so the user sees what Genesis already knows rather than a blank slate.
3. **Persist the transcript** — a `messages` JSON column or a child table. Only this restores
   the chat itself. It is a real decision, not just plumbing: it means storing verbatim
   personal life-planning conversation, with the retention and privacy implications that
   carries, where today the design deliberately keeps only the distillation.

**Recommendation:** do (1) and (2) — they recover the plan, which is the part that matters —
and treat (3) as a deliberate product/privacy decision rather than an implied bug fix.

**Status:** diagnosed. (1) and (2) ready to build on approval; (3) needs a decision.

---

## Resolved during this walk

| Area | Item | PR |
|---|---|---|
| identity | Signup initialization never ran — no account was ever provisioned | #131 |
| client | Dev proxy stripped `/api`, 404ing `/api/version` | #132 |
| client | App routes missing the `/apps` mount — 90 of 101 routes 404ing | #133 |
| client | No scrollbar anywhere: `body{overflow:hidden}` + unbounded shell height | #133 |
| client | Freelance dashboard treated its empty state as a hard error | #133 |
| client | A tripped route error boundary poisoned every subsequent page | #133 |

**Upstream:** the `/apps` mount omission belongs in `@aindy/ui-kit`; corrected app-side in
`client/src/api/_routes.js` and logged against `UIKIT-ROUTE-DRIFT-1`.
