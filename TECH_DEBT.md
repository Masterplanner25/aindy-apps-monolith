# Technical Debt

## SOCIAL-IDENTITY-1: social profile ↔ canonical user (username bound; metrics/lifecycle deferred)

**Status:** Username-binding slice DONE (2026-06-28). Remaining items deferred (below).

**Context:** Three stores key off the same user UUID — `users` (SQL, runtime-owned:
`id`, `email`, unique-but-nullable `username`), `UserIdentity` (SQL, runtime-owned:
inferred behavioral prefs — *not* a profile), and `SocialProfile` (Mongo, social app:
username, tagline, bio, `metrics_snapshot`, tags). The social username and the
denormalized post `author_username` were set independently of the canonical
`users.username` and could drift/collide.

**Done (apps-only):** `users.username` is now the source of truth. On profile upsert
and post creation the social username is sourced from it (lazy reconcile on write);
when `users.username` is null the social value is kept and flagged
`username_verified=false`. The social app never writes the runtime-owned `users`
table. See `apps/social/services/identity_binding_service.py`.

**Deferred:**
1. **Metrics duplication** — `SocialProfile.metrics_snapshot` (written directly to
   Mongo by `apps/tasks/services/task_service.py`) duplicates analytics `UserScore`.
   Make it a read-through projection of `apps/analytics/public` and retire the direct
   write.
2. **Profile lifecycle** — no `SocialProfile` is created at signup (only `users` +
   `UserIdentity`). Ensure one exists per user; coordinate with the runtime signup
   path (`signup_initialization_service`).
3. **Full canonical profile (cross-repo)** — a runtime-owned canonical profile both
   social and identity project from; requires `aindy-runtime` changes.

**Reopen trigger:** any of the three deferred items, or a runtime task to make
`users.username` non-nullable / guaranteed at signup (which would let the social
layer drop the unverified path).

---

## TASK-TIME-SPENT-UNITS-1: `Task.time_spent` is seconds, not hours (documented; normalization deferred)

**Status:** Documented (2026-06-30). The column stays in **seconds**; the misleading
"hours" comment and a name-colliding metric were corrected. True-hours
normalization is deferred (below).

**Context:** `apps/tasks/models.py::Task.time_spent` was commented `# in hours` but
the write path accrues **seconds** (`time_spent += (now - start_time).total_seconds()`
in `task_service.py`), and every consumer already treats it as seconds — the client
shows `time_spent / 60` as minutes, and completion memory labels it `"s"` /
`"time_spent_seconds"`. There is no live miscalculation: the analytics TWR/effort
formulas read `TaskInput.time_spent` (a **caller-supplied API payload in hours**), a
separate path that never touches the DB column; and the Infinity `execution_speed`
KPI is a 0-100 velocity score computed in `infinity_service.py`, unrelated.

**Done (2026-06-30):** Corrected the model comment to state seconds and cross-ref
`duration` (estimated **hours**, added for continuous-time ETA) and the analytics
hours input; added a clarifying note to `TaskInput`; renamed the completion-time
`save_calculation` metric from `"Execution Speed"` (collided with the KPI) to
`"Task Time Spent (seconds)"`. No behavior/data change.

**Deferred (Option B — normalize to true hours):** convert the write path to hours
(`/ 3600`), update the client display (drop the `/60` minutes rendering), fix the
completion memory labels, and add an Alembic migration converting existing rows
seconds→hours. User-visible and touches the integration-tier timing path (not
app-profile testable), so it was not taken now.

**Reopen trigger:** any consumer needing `Task.time_spent` in hours (e.g. feeding
it into the analytics TWR/effort formulas), or a decision to unify the effort unit
across `duration` (hours) and `time_spent` (seconds).

---

## RTR-1-NODUS-COMPLETION: nodus_vm execute-to-completion — RESOLVED (aindy-runtime 1.5.3)

**Status:** **RESOLVED in aindy-runtime 1.5.3 (2026-07-05).** nodus_vm execute-to-completion
was blocked by two stacked, PG-only, transaction-poisoning runtime bugs (SQLite masked both);
both are now fixed and published, and Gate 2 of `tests/integration/test_nodus_vm.py`
hard-asserts the resumed run reaches a terminal state (pin floor `aindy-runtime>=1.5.3,<2.0`):

1. **#152** (PR #155, v1.5.2) — `ExecutionPipeline.run()` emitted its own `execution.started`
   *before* marking itself active, so the nested flow-runner pipeline reached during a
   scheduler-driven resume tripped the ExecutionContract guard at `system_event_service.py:453`
   ('execution.started emitted outside pipeline'); the swallowed error poisoned the PG txn.
   Fixed by setting `pipeline_active` before the first emit. Verified: zero occurrences in CI
   run 28734012605 on 1.5.2.
2. **#157 / RTR-1-NODUS-IDEMPOTENCY-UUID** (PR #158, v1.5.3) — with #152 cleared, the syscall
   dispatcher's **idempotency gate** cast the run-scoped `execution_unit_id` (`run_<uuid>`, e.g.
   `run_897ef792-...`) to the `ExecutionUnit.id` UUID column
   (`psycopg2.errors.InvalidTextRepresentation`, `syscall_dispatcher.py:511`); the caught error,
   lacking a savepoint, left the txn aborted, so the subsequent `INSERT INTO flow_runs` failed
   with `InFailedSqlTransaction` (`syscall_dispatcher.py:591` → `nodus_execution_service.py:871`)
   and the run never completed. Fixed by only looking up bare-UUID ids and SAVEPOINT/rollbacking
   the lookup. Reproduced on CI runs 28734012605 + 28734198382 (1.5.2); closed in 1.5.3.

**Remaining thread (separate):** Gate 1 (app-tool via `anthropic_chat`) is still blocked by a
planner **create-500** — **RTR-1-NODUS-APPTOOL-500** below; independent of the completion path.

**History (the reopened-then-fixed arc for #152):** on 1.5.1 the symptom looked gone on
the passive re-run (run 28727775436) only because, with no scheduler heartbeat, the
resume callback was never dispatched. Driving the scheduler in-process
(`get_scheduler_engine().schedule()`, run 28728594828, 2026-07-05) actually RAN the
resumed segment — and it **still raised** `execution.started emitted outside pipeline`
(`pipeline.py:326` → `system_event_service.py:453`). The 1.5.1 fix wrapped the resume
*callback* in an async-execution context (`nodus_execution_service.py:617-631`), but the
inner **flow-runner pipeline** that emits `execution.started` ran in a context that did
not inherit it. 1.5.2 closed exactly that gap — and surfaced the idempotency-gate bug
above.

**Context:** RTR-1 shipped the opt-in `nodus_vm` agent-execution backend
(`AINDY_AGENT_EXECUTION_BACKEND=nodus_vm`). §5 asked whether tools registered via
this repo's plugin manifest resolve **and execute** inside the `nodus_worker`
subprocess. The first live-Postgres CI run (2026-07-04, runtime 1.5.0) established:

- ✅ Plan generation under nodus_vm (stub + `anthropic_chat` planners).
- ✅ WAIT parking — `AINDY_AGENT_WAIT_BEFORE_HIGH_RISK` inserts an approval WAIT before
  the first high-risk step; the run parks at `status="waiting"` with `wait_state` /
  `correlation_id` / `granted_tools` set.
- ✅ The app-owned resume route (`POST /apps/agent/runs/{id}/resume`, §4) returns 200
  and publishes `agent.approval.granted` scoped to the run's correlation.
- ✅ No tool-resolution failure surfaced in the subprocess (no `"tool not found"`),
  i.e. the app manifest loaded there.
- ❌ **Execute-to-completion does not run under the TestClient integration harness.**
  After resume the run stays `waiting`, and the runtime repeatedly raises
  `RuntimeError: ExecutionContract violation: execution event 'execution.started'
  emitted outside pipeline` (`AINDY/core/system_event_service.py:453`, from
  `AINDY/core/execution_pipeline/pipeline.py:326`). The plan continuation appears to
  run outside the ExecutionPipeline wrapper.

**Root cause (confirmed — runtime-owned bug):** the resumed segment is dispatched by
the scheduler and runs **inline with no enclosing `ExecutionPipeline` context**
(`AINDY/runtime/nodus_execution_service.py` `_execute_agent_segment_chain` never calls
`execute_with_pipeline` / `set_pipeline_active` / `activate_async_execution_context`,
unlike the initial run which enters via `ExecutionPipeline().run`). When the resumed
segment emits `execution.started`, the guard at `AINDY/core/system_event_service.py:453`
sees neither `is_pipeline_active()` nor `is_async_execution_active()` and, with the
default `ENFORCE_EXECUTION_CONTRACT=True`, raises. A live server (scheduler running)
fixes event *delivery* but **not** this — the callback still runs without a pipeline
context. This is not a harness limitation; it is an `aindy-runtime` defect.

**Filed:** `aindy-runtime` issue **#152** (full file:line diagnosis and repro). Local
report: `HANDOFF-runtime-nodus-resume-pipeline-context-bug.md`.

**Partial fix in aindy-runtime 1.5.1 (INCOMPLETE):** the resume callback now wraps
`_execute_agent_segment_chain` in `activate_async_execution_context()`
(`AINDY/runtime/nodus_execution_service.py:617-631`, comment cites #152). But the
`execution.started` that raises is emitted one layer deeper — the inner flow-runner
`ExecutionPipeline` reached via `run_nodus_script_via_flow` → `sys.v1.nodus.execute`
(`nodus_execution_service.py:482,239`) — and that pipeline runs in a context where
`is_async_execution_active()` is still False, so the guard at
`system_event_service.py:453` fires. The async context must be established at (or
propagated into) the inner flow-runner emission, not only around the outer callback.
Empirically shown by driving the scheduler (run 28728594828). **Reopened upstream.**

**Current handling:** `test_nodus_vm.py` Gate 2 (deterministic `stub` planner →
`memory.recall`) hard-asserts parking + resume acceptance + delivery
(`waiters_notified>=1`), then drives the scheduler in-process to run the resumed segment
and **hard-asserts** it reaches a terminal status. On `aindy-runtime>=1.5.3` (both #152
and #157 fixed) this passes end-to-end; a regression of either fix would poison the run's
PG transaction and fail it red. Tool *resolution* in the subprocess and
execute-to-completion are both now proven.

**Open thread — RTR-1-NODUS-APPTOOL-500:** Gate 1 would prove an **app-manifest** tool
(`task.create`, no runtime default) executes in the subprocess, driven by the
`anthropic_chat` LLM planner — but `POST /apps/agent/run` returns a generic **500**
`{"message":"Failed to generate plan"}` (`AINDY/agents/runtime_api.py:146` — `create_run`
returned falsy), so it `skip`s.

**ROOT CAUSE (confirmed 2026-07-05, runtime 1.5.3, CI run 28743569180):** the create-500
is `anthropic.APIConnectionError` — **the CI runner cannot open an outbound HTTPS
connection to `api.anthropic.com`.** The exact skip-surfaced reason:
`AnthropicPlannerError: Anthropic API connection error for model 'claude-opus-4-8':
Connection error.` The SDK already retries connection errors twice by default, so this is
a hard egress block, not a transient blip. The app backend IS entered, constructs the
client (key present, else `_make_client` raises a different error), and the outbound call
fails.

**The prior subprocess-boundary hypothesis is WRONG.** Runtime trace (aindy-runtime 1.5.3):
`create_run` → `compat.generate_plan` runs plan generation **in-process** on the request
thread (`AINDY/agents/agent_runtime/creation.py:36`); the execution backend only affects
`apply_wait_policy` **after** the plan is generated (`planning.py:307`). Plan-gen for
`anthropic_chat` therefore never enters the `nodus_worker` subprocess, and this 500 would
occur identically under `agent_flow` — it is **not** nodus_vm-specific.

**Why the reason stayed invisible across three sessions (triple blind spot):**
1. `generate_plan` catches all backend exceptions and stores the reason on a
   `threading.local` (`_plan_failure`, `AINDY/agents/agent_runtime/shared.py:19`), set on
   the FastAPI threadpool worker and unreadable from the test thread.
2. Its backup `required` `agent_plan_generation` SystemEvent (`creation.py:39-49`) can be
   lost to the `system_events_user_id_fkey` violation observed in the same runs.
3. pytest discards captured logs for **skipped** tests, so the app backend's entry-log
   (PR #48) never displayed — which is why "backend never entered" was recorded, wrongly.

The model id (`claude-opus-4-8`) and forced-tool request shape are valid (claude-api
reference: current `/v1/messages` model; `planner_anthropic.py` omits the
`temperature`/`top_p`/`budget_tokens` that 400 on Opus 4.8). Gate 2's `stub` planner works
because it needs no key/network; `anthropic_chat` needs egress the runner doesn't have.

**Diagnostic in place:** `test_nodus_vm.py::_diagnose_anthropic_planner` calls the app
backend directly, in the test thread, on a 500 and folds the real exception (with
`__cause__`) into the skip reason — permanently surfacing the cause even for a skipped
test. Test-only branch `test/nodus-apptool-500-diagnosis`.

**Reopen trigger / next step:** (a) **RTR-1-NODUS-APPTOOL-500** is now a **CI-runner egress
matter, not a code bug** — Gate 1 can only pass where the runner can reach
`api.anthropic.com`. Options: allow-list `api.anthropic.com` egress on the runner (if org
policy blocks it); OR run Gate 1 on a runner with internet egress; OR accept that the
LLM-driven app-tool proof isn't runnable in this environment and drop Gate 1 to a
deterministic app-tool goal under the `stub` planner (proves app-manifest execution in the
subprocess without any network — the original §5 intent). (b) any move to make `nodus_vm`
the default (`AINDY_AGENT_EXECUTION_BACKEND`) still wants an app-manifest execute proof —
satisfiable via the stub-based Gate 1 above without egress. (c) any regression of the
execute-to-completion path — Gate 2 hard-asserts it, so a runtime regression fails CI red.

---

## MASTERPLAN-CONNECTOR-RUNTIME-1: automation connectors lack a first-class registration + capability-enforcement surface (runtime-owned)

**Status:** Deferred (2026-06-30). App-side connector coverage is complete
(MASTERPLAN_SAAS Step 4); the residual is runtime work in `aindy-runtime`.

**Context:** External automation connectors (social, crm, email, webhook, stripe,
subscription) are dispatched by a hardcoded `if/elif` ladder in one app service,
`apps/automation/services/automation_execution_service.py::execute_automation_action`.
Each connector builds its own outbound HTTP/SMTP with stdlib (`urllib`/`smtplib`)
and wraps it in the runtime `perform_external_call`, which is an **observability
wrapper only** (`AINDY.platform_layer.external_call_service`): it emits
`external.call.started|completed|failed` events and times the call, but does **not**
authorize, allow-list, rate-limit, sandbox, or vault credentials. There is no
`register_connector`-style hook in `AINDY.platform_layer.registry`.

**Gaps (runtime-owned):**
1. **Connector registration hook** — replace the app-side `if/elif` ladder with a
   runtime `register_connector(type, handler)` surface so connectors are pluggable
   like routers/syscalls/jobs, and so multiple apps can contribute connector types.
2. **Capability-enforced outbound I/O** — a runtime boundary that gates external
   calls (per-user authorization, endpoint allow-lists, credential vaulting,
   rate-limiting) rather than the by-convention `perform_external_call` observe-only
   wrapper.
3. **Shared HTTP client / retry-circuit** — apps use raw `urllib` today;
   consolidating outbound transport + retry/circuit-breaking belongs in the runtime.

**Not blocked:** connector *delivery* works today (app-owned). This is hardening,
not capability. Per the app/runtime split, these are `aindy-runtime` features; the
app would adopt them via the new registration hook once published.

**Reopen trigger:** a runtime release exposing a connector-registration and/or
outbound-capability surface, or a security requirement for enforced outbound I/O.

---

## MONGO-DB-NAME-1: social layer split across two Mongo databases (RESOLVED)

**Status:** RESOLVED (2026-06-27). Code unified; no data migration required
(production runs `MONGO_DB_NAME=aindy_social_layer`, confirmed with the owner).

**Context:** The social layer selected its Mongo database two different ways. The
`social_router` endpoints (profile/post/feed/interact/comments) used the runtime
dependency `get_optional_mongo_db`, which yields `client[MONGO_DB_NAME]`
(`MONGO_DB_NAME` defaults to `aindy_default`). Four services instead hardcoded
`client["aindy_social_layer"]`: `social_performance_service`,
`social_metrics_history_service`, `automation_execution_service` (apps/automation),
and `task_service` (apps/tasks). `MONGO_DB_NAME` was never set in the repo and
undocumented in `.env.example`.

**Impact (when `MONGO_DB_NAME` is unset):** `posts` and `profiles` were written
and read under two different databases — analytics read an empty
`aindy_social_layer.posts` while user posts lived in `aindy_default.posts`;
masterplan-automation posts and task-completion profile velocity bumps landed in
`aindy_social_layer` but were invisible to the router serving `aindy_default`.
The system only worked if an operator separately knew to set
`MONGO_DB_NAME=aindy_social_layer`.

**Fix:** All four call sites now resolve `client[MONGO_DB_NAME]` (single source of
truth, matching the router). Safe in both directions: with the prod value
`aindy_social_layer` it is a no-op; if unset, services now agree with the router on
`aindy_default`. `MONGO_DB_NAME` is documented in `.env.example`.

**Residual / reopen trigger:** If any environment historically ran with
`MONGO_DB_NAME` unset *and* accumulated Mongo data, that data is split across
`aindy_default` and `aindy_social_layer` and needs a one-time merge of the `posts`
and `profiles` collections. Production was confirmed on `aindy_social_layer`, so no
merge is needed there; revisit only if a split-data environment surfaces.

---

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

## SEARCH-RANKING-EMBEDDINGS-1: hybrid semantic (embedding) ranking — RESOLVED

**Status:** RESOLVED (2026-06-28). The hybrid embedding seam scoped here is now implemented:
semantic relevance via the runtime embedding stack, opt-in, with automatic lexical fallback. The
v3 Ranking Unification (PR #16) had intentionally shipped lexical-only with this pluggable seam;
this pass wired the seam.

**Context (original):** Phase v3 of the Search System (`docs/apps/SEARCH_SYSTEM.md`) added a shared
ranking layer: `lexical_relevance()` + `composite_score()` in
`apps/search/services/search_scoring.py`, applied by `rank_items()` in
`apps/search/schemas/search_schema.py` so every surface (leadgen, research, SEO) ranks
`SearchResponse.results` on one composite axis (0.6 relevance / 0.4 surface quality). Lexical
relevance (token-overlap + saturating term-frequency) captures lexical overlap but not **semantic**
similarity (synonyms, paraphrase, query intent).

**Resolution — what shipped (all four scoped items):**
1. `embedding_relevance()` and the caching `EmbeddingRelevanceProvider` in `search_scoring.py`
   compute cosine similarity over the runtime embedding stack the app already reaches
   (`AINDY.memory.embedding_service.generate_query_embedding` / `cosine_similarity`) — the same
   backend behind `search_service.search_memory`. No new external dependency on the app side.
2. `rank_items()` gained a `relevance_fn` parameter and defaults to `default_relevance_provider()`:
   lexical unless the `AINDY_SEARCH_EMBEDDING_RANKING` flag opts into embeddings. The embedding
   provider degrades to lexical on its own when the backend is unavailable, so the default is
   always safe and the surface adapters required no changes.
3. Determinism preserved: the seam is off by default, and even when enabled the runtime embedding
   service returns a zero vector under `settings.is_testing` (no OpenAI client) — detected by
   `_is_zero_vector()` and routed to lexical. SQLite/app-profile/CI runs therefore stay lexical and
   deterministic. The embedding path is covered separately with the service mocked
   (`tests/unit/test_search_ranking.py`).
4. Within a ranking pass, `EmbeddingRelevanceProvider` embeds the query once and caches each
   document embedding, so `rank_items` does not recompute per item.

**Follow-up (not blocking):** cross-request / persistent embedding caching (current cache is
per-pass only), and cosine-score calibration for ada-002's compressed similarity range if semantic
ordering proves too flat in production. Reopen if either is needed.

**Tests:** `tests/unit/test_search_ranking.py` — fallback-on-zero-vector, active cosine path,
per-pass caching, flag-gated provider selection, and embedding-driven reordering through
`rank_items`.

**Cross-ref:** Completes the v3 design seam noted in `SEARCH_SYSTEM.md` Phase v3; supersedes the
"richer provider-backed ranking" clause of APP-DEBT-MIGRATED-1's search row.

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
  - `platform/governance/EVOLUTION_PLAN.md` → **BROUGHT OVER** as `docs/platform/governance/EVOLUTION_PLAN.md`.
    It's an existing, current roadmap (not synthesized): Phases 1–4 are completed runtime hardening
    (kept as historical context, owned upstream by `aindy-runtime`), Phase 5 is the current
    cross-repo phase, and Phases 6–7 + the named phases are app-facing. Brought over with
    cross-repo reference hygiene (runtime-owned governance links flagged; moved app-doc paths fixed)
    and an ownership preamble.

- **`platform/governance/INVARIANTS.md` (late finding — was pre-classified runtime-only, actually
  mixed ~50/50):** the app-domain invariants were extracted to
  `docs/platform/governance/INVARIANTS.md` — masterplan/genesis (single-active, locking,
  synthesis-ready gate, audit-draft gate, atomic creation, non-null columns), analytics canonical-
  metrics uniqueness, rippletrace DropPoint-before-Ping, freelance non-null columns, and the
  JWT/API-key/rate-limit invariants whose protected surfaces are app routers (enforcement mechanism
  stays runtime-owned). Original section numbers preserved for traceability. The runtime invariants
  (PostgreSQL/UTC/session-isolation/memory-graph/embedding/schema-drift) remain runtime-owned —
  **author the runtime half in `aindy-runtime`** (fold into the Bucket A handoff).

**Status:** DOCS-MIGRATION-2 complete (apps side). Open items, both on `aindy-runtime`: the **Bucket A**
relocation and the **runtime half of `INVARIANTS.md`**.

**Reopen trigger:** Follow-up on the `aindy-runtime` items, or a re-triage of `EVOLUTION_PLAN` phases
as they complete.

---

## APP-DEBT-MIGRATED-1: domain debt recovered from the pre-split register (2026-06-27)

**Status:** Tracked. Migrated from the pre-split `docs/platform/engineering/TECH_DEBT.md`
(triaged 2026-04-25) under DOCS-MIGRATION-2 Bucket C. These app-domain items were never carried into
this repo's register — a genuine tracking gap. Runtime/infrastructure items from the same source stay
with `aindy-runtime`. Verify each against current code before acting; the source triage is ~2 months old.

### APP-DEBT-MIGRATED-1a: Genesis session locking enforced only in application logic (production-blocking)

**Status:** RESOLVED — already fixed in this repo before migration; verified 2026-06-27.
**Severity:** High  **Effort:** M  **Files:** `apps/masterplan/services/masterplan_factory.py`,
`apps/masterplan/masterplan.py`

**Original concern (from the pre-split triage, 2026-04-25):**
`create_masterplan_from_genesis()` prevents double-locking by reading `GenesisSessionDB.status` in
application code, but the schema enforces no DB-level uniqueness/lock invariant for the
lock/plan-creation transition. Concurrent lock requests can create duplicate or inconsistent
masterplan state from one genesis session — a correctness bug in a primary planning workflow.

**Resolution:** The fix landed in this repo on 2026-04-26 (the day after the source triage) and was
carried in unverified during the DOCS-MIGRATION-2 migration. Both transaction-boundary layers the
item asked for are present:
- DB backstop: partial unique index `uq_masterplan_genesis_session_id` on
  `master_plans.linked_genesis_session_id` — declared in `apps/masterplan/masterplan.py` and created
  by migration `2d4f6a8b0c1d_add_masterplan_genesis_session_uniqueness.py` (wired into the head chain;
  PostgreSQL partial-index branch, plain unique index on other dialects).
- Row-locking: `create_masterplan_from_genesis()` reads the session under `with_for_update()` and
  catches `IntegrityError` on commit, surfacing a clean `ValueError`.

Concurrent lock requests can no longer create duplicate masterplan state: the row lock serializes the
common path and the unique index is the hard backstop if two transactions both pass the status check.
Regression coverage added 2026-06-27 in `tests/unit/test_masterplan_genesis_locking.py` (asserts the
application guard, the DB unique-index rejection, and that distinct sessions remain unconstrained).

### Deferred app-domain items

| Item | Domain | Effort | When to revisit |
|------|--------|--------|-----------------|
| Search orchestration unified (Steps 1–6 + v3 ranking + semantic seam, 2026-06-28) — shared `search_service`, unified `SearchResponse` contract, agent tool + `unified_search` workflow, shared lexical ranking, and the hybrid embedding-ranking seam (**SEARCH-RANKING-EMBEDDINGS-1**, RESOLVED) all shipped. No remaining search-ranking debt | search | — | done |
| Freelance commercial workflow incomplete — payments/refunds/webhooks/idempotency/subscriptions and now lead→client→order lineage (Phase 1, 2026-06-28: `ClientAccount` + intake_service) exist; agent-driven execution (Phase 2) and the autonomous optimization loop (Phase 5) do not | freelance | M | before exposing freelance as a primary autonomous revenue path |
| RippleTrace productization incomplete — execution-causality, graph edges, UI, and now end-to-end causal-graph validation (backend + frontend, Steps 1–2, 2026-06-28) exist; deeper insight generation and broader scenario coverage do not | rippletrace | M | before using RippleTrace as a primary incident/audit surface |
| Masterplan dependency cascade + execution automation — anchor/ETA debt closed; ETA is now plan-scoped + cascade/critical-path aware (MASTERPLAN_SAAS Step 1, 2026-06-30, `apps/masterplan/services/eta_service.py`). task completion now returns the refreshed projection (Step 3, `_recalculate_active_masterplan_eta` → `task_orchestration.masterplan_projection`). the plan's ETA panel now surfaces the cascade metrics directly — basis chip, critical-chain depth, ready/blocked — and adopts the completion-response projection reactively via a `MasterplanProjectionProvider` context so completing a task refreshes the plan panel without a refetch (MASTERPLAN_SAAS Step 2, 2026-06-30, `client/src/components/app/MasterPlanDashboard.jsx`, `client/src/context/MasterplanProjectionContext.jsx`). ETA is now continuous-time: per-task `estimated_hours` drives a remaining-effort + effort-weighted-critical-path projection (`projection_basis="duration"`), reducing to count-based cascade when estimates are absent (2026-06-30, `apps/tasks/services/task_service.py`, `apps/masterplan/services/eta_service.py`). external automation connectors now reach external surfaces — CRM (stub → provider-agnostic outbound POST) and social (additive external delivery on top of the internal feed) join email/webhook/stripe, all wrapped in the runtime `perform_external_call` boundary (MASTERPLAN_SAAS Step 4, 2026-06-30, `apps/automation/services/automation_execution_service.py`, `tests/unit/test_automation_connectors.py`). Remaining is runtime-owned hardening only (see MASTERPLAN-CONNECTOR-RUNTIME-1 below), not app wiring | masterplan | L | mostly closed; residual is runtime-owned |
| ARM low-risk config suggestions require manual apply — `auto_apply_safe` remains advisory, not auto-applied | arm | S | before positioning ARM as a self-tuning service |
| Infinity loop autonomy still shallow — reasoning extracted into a reusable engine + dedicated `reason()` service (strategy_selector/feedback_analyzer) the loop consumes, plus `reasoning.*` observability events, agent integration (planner consumes the `analytics.reasoning_recommendation` job; completion hook → reasoning-backed orchestrator), reasoning `execution_intent` + a registered `reasoning` flow strategy / `reasoning_apply` flow, and the `reasoning.evaluate` agent tool (`apps/analytics/services/reasoning/`, `apps/analytics/agents/`, ARM/Reasoning Phases 1–5 + tool follow-up, 2026-06-28/29). All app-ownable reasoning phases are complete. Still no deep threshold/weight learning and not a bounded autonomous controller | analytics | M | before enabling autonomous optimization decisions |
| Nodus-native reasoning execution deferred (runtime) — reasoning `execution_intent` runs through the flow engine (Phase 4), but there is no app-facing registration surface for Nodus `.nd` workflows; true Nodus-first execution needs a `register_nodus_workflow`-style hook added in `aindy-runtime` (runtime feature request, not an app edit) | runtime/analytics | M | when Nodus becomes the primary execution substrate |
| Infinity support-system depth — explicit `UserFeedback` nudges per-user KPI **weights** (Step 5), support inputs are centralized into one `SupportState` snapshot (Step 1), and the support → decision seam has behavioral coverage (Step 6) (2026-06-29). Remaining: weight feedback into the KPI **score formulas** (deliberately deferred — risks conflating measurement with sentiment; weights are the principled lever); the full DB-backed loop E2E (integration-tier); fold `identity_boot_service` state into the snapshot; and consume observability + agent/async execution aggregates (Steps 3/4) — runtime-gated, need a runtime aggregate syscall/job. ARM `arm_metrics_service` KPI output is also still not consumed by Infinity (recomputes from raw analysis rows) | analytics | M | when deepening Infinity optimization |
| Agentics completion is runtime-owned — the doc that defined the `aindy-runtime` split. App-side decision levers (autonomy trigger policy, agent ranking strategy, completion hook) are now tested (AGENTICS hardening, 2026-06-29). Phases B (Nodus VM/`.nd`) and E (durable workers), and most of D (delegation/registry/conflict), are runtime work in `aindy-runtime`, not app edits; the registerable D lever (ranking) is done | runtime/agent | L | when `aindy-runtime` advances Agentics execution |
| Identity inference rules-only — observation exists; probabilistic/model-driven inference does not | identity | M | before expanding identity-driven personalization |
| SYLVA reserved agent namespace inactive — scaffolding only, agent unimplemented | agent | S | when the reserved agent is activated or removed |

**Reopen trigger:** Per-item "when to revisit" above, or substantial work in the named domain.
