---
title: "Frontend Walk Log — live user-path walkthrough"
last_verified: "2026-07-22"
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
| 4 | Defect | network | `InfiniteNetwork` calls `/api/users`, which no route serves; also no member-list endpoint exists and signup never provisions a social profile | confirmed live; 4 consolidation options logged, decision deferred |
| 5 | Defect | Genesis | Leaving the page abandons the session; transcript is never stored | diagnosed, decision needed |
| 6 | Gap | auth | No password recovery — a forgotten password locks the account out permanently | runtime feature request |
| 7 | Defect | search / research | Research web-search provider (Perplexity) is an unwired stub — no key sent, wrong endpoint | decided: wire Perplexity (opt 1), not built |
| 8 | Design | auth / client | A 401 on ANY request logs the whole session out — a stray widget 401 bounces the user to sign-in | decision needed |
| 9 | Question | search / SEO | Who saves an SEO analysis? (answered: the system, automatically) | answered |
| 10 | Design | social | The social feed reads very bare on first look — presentation, and "social feed" vs "trust feed" identity | design note |
| 11 | Defect | social | Posts don't appear after posting — Mongo not enabled + a 500 on the created post + a false-success degrade | fixed (needs Mongo) |
| 12 | Defect | social / client api | The feed renders nothing and analytics shows all zeros — `social.js` never unwrapped the execution envelope | fixed |
| 13 | Defect | client api (systemic) | `unwrapEnvelope` coverage is inconsistent across `client/src/api/` — 8 modules have none | diagnosed, watch while walking |
| 14 | Defect | tasks | Created tasks never appear — `/apps/tasks/list` nests the array one level deeper than the unwrap handles | fixed |
| 15 | Question | tasks | Is a task tracked, or executed by the AI? (answered: tracked; AI execution is opt-in and has no UI) | answered, decision needed |
| 16 | Defect | masterplan | The only non-Genesis MasterPlan create route 500s — Genesis is the sole working way to get a plan | confirmed live, unfixed |
| 17 | Design | masterplan / genesis / tasks | The three surfaces were one section and are now disconnected tabs; no UI links a task to a plan. Includes an import-an-external-plan proposal | design decision |
| 18 | Design | analytics / kpi | Analytics is LinkedIn-specific and owner-specific; KPI Snapshot is a manual-entry calculator that wants to be a dashboard | owner verdict: redesign or remove |
| 19 | Defect | arm | ARM Analyze reads files from the **server**, the prefilled default cannot exist, and a failed analysis renders a blank screen | fixed (client); default path decision open |
| 20 | Security | arm | ARM has no project-root confinement — any allowlisted-extension file anywhere on the server is readable and gets sent to an external LLM | hardening recommended |

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

**Update (2026-07-22 walk) — confirmed live, and it's broader than a wrong URL.**

Verified against the running stack: `GET /api/users` → **404**, `POST /api/users` → **404**,
and nothing resembling it exists in the OpenAPI schema. Both halves of the page (list members,
create profile) are wired to a route that has never existed on this backend — the component is
a leftover from a standalone prototype and was never connected.

Two further findings that constrain the fix:

1. **There is no member-listing endpoint at all.** Social exposes only
   `POST /apps/social/profile` and `GET /apps/social/profile/{username}`. A "Network Members"
   list has nothing to call; it would need a new `GET /apps/social/profiles` route.
2. **`network_bridge` is not a drop-in target.** `GET /apps/network_bridge/authors` returns
   **401 with a valid bearer token** — it is API-key gated. Pointing the page at it would
   reproduce the RippleTrace logout bug (#145), where an api-key-gated call 401s and the
   global 401 handler signs the user out (open item 8).

**Related gap — profile provisioning was never moved to signup.** The owner recalled asking for
profile creation to happen at sign-up rather than on a separate tab. It was not implemented.
`apps/identity/services/signup_initialization_service.py` provisions a `UserIdentity` row, an
initial memory node, an analytics score, an initial agent run, and an `identity.created` event —
**no social profile**. Confirmed live: a freshly registered user returns **404** from
`GET /apps/social/profile/{username}`. A profile only exists once the user visits
`/profile/:username` and clicks "Create Identity Node", which is why that screen opens in
create-mode for every new account.

**Consolidation options (logged, not chosen — owner deferred the decision to keep walking):**

| # | Option | What it entails |
|---|---|---|
| A | Delete the tab; provision at signup | Remove `InfiniteNetwork` + its route; add social-profile creation to `initialize_signup_state`; `/profile/:username` becomes the single profile surface. Smallest surface, matches the original intent. |
| B | Keep a directory; build its backend | Add `GET /apps/social/profiles`, repoint the page at it, make `/network` read-only browse. Profile creation still moves to signup. |
| C | Fold into `/social` as a Members tab | Delete the standalone route, add a directory tab beside the Trust Feed. Still needs the list endpoint; consolidates social into one destination. |
| D | Park it | Disable the route so nobody hits a dead page; treat consolidation as a redesign decision. |

All four share two prerequisites: profile creation moves into signup, and any directory needs a
new social list endpoint. Note also that `/network` and `/profile/:username` are two UIs for one
concept built against two different backends, one of which doesn't exist — a redesign /
consolidation candidate in the owner's own framing, consistent with the "underspecified
presentation over working backends" theme running through this walk.

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

### 6. No password recovery — `Gap`

**Observed:** an internet drop ended the session (logged out), and the account could not be
signed back into. There is no "forgot password" path anywhere in the UI or the API — a
forgotten or mistyped-then-forgotten password locks a real user out permanently, with no
self-service way back in.

**Confirmed:** the entire auth surface is `POST /auth/register`, `POST /auth/login`,
`POST /auth/logout`, `POST /auth/admin/invalidate-sessions/{user_id}`. No reset-request, no
reset-confirm, no email verification, no change-password. Login itself is healthy — verified a
fresh register+login returns 200, a wrong password returns 401 — so this is purely a missing
recovery flow, not a broken one.

**Ownership:** auth lives in the runtime (`AINDY/routes/auth_router.py`,
`AINDY/services/auth_service.py`), not in `apps/`. This is therefore a **runtime feature
request**, not an app-repo change. A minimal version needs:

- `POST /auth/password/reset-request` (email → tokenised link; must not leak whether an
  address exists)
- `POST /auth/password/reset-confirm` (token + new password → `hash_password`, then invalidate
  existing sessions — the `admin/invalidate-sessions` primitive already exists to build on)
- an email-sending capability (a connector), which the runtime does not currently ship
- optionally `POST /auth/password/change` for a signed-in user

**Immediate workaround used during this walk:** the walkthrough account
(`shawnknight@the-master-plan.com`) was reset directly against the local stack using the
runtime's own `hash_password`, verified with a real login. This is a dev-stack unblock only —
it required shell access to the database and is not a substitute for a recovery flow. A real
deployment has no such door.

**Status:** logged for the runtime team. Not an app-repo fix.

---

### 7. Research web-search provider is an unwired stub — `Defect`

**Observed:** a research query returns a summary that reads like an error — e.g. "The provided
message indicates an error due to an invalid API key." The query no longer 500s (that was a
separate route bug, fixed in `fix/research-query-request-param`), but the *content* is the
provider's own auth-failure text, summarised back to the user.

**Why:** the research path is two providers in sequence
(`apps/search/services/research_engine.py`):

1. `web_search(query)` → Perplexity, `GET https://api.perplexity.ai/search?q=…`
2. `ai_analyze(content)` → OpenAI gpt-4o, which summarises whatever step 1 returned

**OpenAI works** — it successfully produced the summary, so `OPENAI_API_KEY` is valid. The
break is entirely in `web_search`, and it is not just a missing env var:

```python
url = f"https://api.perplexity.ai/search?q={query}"
resp = perform_external_call(..., operation=lambda: requests.get(url))
```

- **No auth is ever sent** — a bare `requests.get(url)`, no `Authorization` header.
- **There is no `PERPLEXITY_API_KEY` in config at all** (`hasattr(settings, "PERPLEXITY_API_KEY")`
  is `False`), so there is nothing to send even if a key were added to `.env`.
- **Wrong endpoint** — Perplexity's API is `POST /chat/completions` (OpenAI-compatible), not a
  `GET /search?q=`.

So Perplexity rejects the unauthenticated request with "invalid API key", and gpt-4o dutifully
summarises that error. Present keys on the stack: `OPENAI`, `ANTHROPIC`, `DEEPSEEK` — none of
which is a web-search provider.

**Same gap surfaces in Lead Generation (same root cause).** `search_leads` → the same
`research_engine.web_search` → Perplexity error. Nothing parses out, so it falls back to a
single placeholder lead `{company: "External Search", context: <the raw error text>}`
(`search_service.py:343`), and then OpenAI *scores that placeholder* — producing a lead whose
summary literally reads "intent score is low due to the current API key issue" (observed:
Match Score 26, company "External Search"). So leadgen can't find real leads until the search
provider is wired. The honest-degrade fallback (below) must cover leadgen too: when the search
returns nothing real, return an empty/"no leads found" state rather than scoring an error string.

**Fix options (a decision, not just a key):**

1. **Wire Perplexity properly** — add a `PERPLEXITY_API_KEY` config field, send it as a Bearer
   header, and call `POST /chat/completions`. Requires the user to hold a Perplexity key.
2. **Switch to a search provider the stack has a key for** — none of OPENAI/ANTHROPIC/DEEPSEEK
   is a web search API, so this means adding one (Tavily, Brave, SerpAPI, …).
3. **Degrade honestly** — if no search key is configured, skip `web_search` and either research
   over memory/LLM only or return a clear "web search not configured" state, rather than
   summarising a provider error as if it were a result.

**Decision (owner, 2026-07-21): option 1 — wire Perplexity properly.** Real web research via
Perplexity, not a degrade or a swap. Scope to implement:

- add a `PERPLEXITY_API_KEY` setting (config field + `.env`); the deployment supplies the key
- rewrite `research_engine.web_search` to `POST https://api.perplexity.ai/chat/completions`
  (OpenAI-compatible body: a `sonar`/`sonar-pro` model + messages), with
  `Authorization: Bearer <key>` — routed through `perform_external_call` so the key is never
  logged
- when the key is absent, degrade honestly (option 3 as the fallback path) rather than
  summarising Perplexity's auth error as a result — so local/dev stacks without a key don't
  surface error text as content
- the OpenAI `ai_analyze` summariser stays as-is (it works); it now summarises real search
  results instead of an auth error

**Status:** decided — option 1. Not yet built. Needs a Perplexity key at deploy; safe-degrade
fallback lands with it so a missing key is a clean "web search not configured" state.

---

### 8. A 401 on any request logs the whole session out — `Design`

**Observed:** opening the Dashboard Graph tab bounced the user to the sign-in page, in a loop
(re-login → back to /dashboard/graph → bounce again). The concrete cause was fixed (GraphView
was hitting api-key-gated routes that 401 a normal user — see Resolved #145). But the reason a
*graph widget* could log the user out at all is a broader client-side design choice worth a
decision.

**Why:** the `@aindy/ui-kit` request core dispatches a global `aindy:session-expired` event on
**any** response with status 401 (`authRequest` → `status === 401 && dispatch()`). `AuthContext`
listens for it and clears the token, which drops `isAuthenticated` and sends the user to
`/login`. So a 401 from *any* endpoint — including optional, non-critical dashboard data —
tears down the entire session, even when the component itself catches the error and would have
degraded gracefully. The dispatch fires *inside* the request wrapper, before the component's own
`catch` runs, so a component cannot opt out after the fact.

**Why it's a design item, not just a bug:** treating 401 as "session dead" is correct for
*auth-critical* calls (the token genuinely expired or was revoked). It is wrong for *optional
data* calls, where a 401 may mean "you lack access to this one widget", not "your session is
over". The current all-or-nothing rule means any future endpoint that 401s for a normal user
(a permissions edge, a deprecated route, an admin-only widget on a shared page) becomes a
full-logout bug — exactly how #145 manifested.

**Ownership caveat:** the dispatch lives in `@aindy/ui-kit` (the request core), so the cleanest
fix is upstream. App-side mitigations are possible but partial.

**Options:**

1. **Distinguish auth-critical from optional requests (upstream).** Give the ui-kit a request
   variant that returns `null`/throws on 401 *without* dispatching session-expired (one already
   exists internally — some helpers do `if (status === 401) return null`). Optional widgets
   (graphs, side panels) use it; auth-critical calls keep the session-ending behavior. Correct,
   but needs a ui-kit change.
2. **Verify before logout.** On a 401, don't clear the session immediately — re-check the token
   (local `exp`, or a lightweight `/auth`-side check) and only log out if it's actually invalid.
   Prevents a single endpoint's authorization 401 from ending a valid session. App-side-ish
   (AuthContext), but the dispatch still originates upstream.
3. **Accept it, and enforce a rule:** no user-facing surface may call an endpoint that 401s for
   a normal user. Cheapest, but fragile — it's a convention with no guardrail, and #145 shows
   how easily it's violated.

**Recommendation:** option 1 (upstream) is the right long-term fix; option 2 is a reasonable
app-side stopgap. Until then, the API-route audit + the ownership tests are the only guardrail
against another #145.

**Status:** logged for a decision. Primarily a `@aindy/ui-kit` concern; app-side stopgap
possible in `AuthContext`.

---

### 9. Who saves an SEO analysis, and why "No saved searches yet" — `Question` (answered)

**Observed:** the AI SEO tool works — Analyze SEO returns a scorecard, Generate Meta returns a
description, Get Suggestions returns a strategy. But "Recent SEO Analyses" said *No saved
searches yet* after running one, prompting: who saves it — the user or the system?

**Answer: the system, automatically.** There is no "save" button and no user action anywhere in
search — every analyze / meta / research / leadgen call auto-persists to history via
`execute_durable_search`. SEO analyze *is* wired into that: verified live that
`POST /apps/seo/analyze` writes a `search_history` row with `search_type="seo_analysis"`, and
`GET /apps/search/history?search_type=seo_analysis` returns it (count=1). So it is being saved,
by the system, keyed to the user.

**Why the panel looked empty (fixed):** `SearchHistory` fetched once on mount
(`useEffect(…, [searchType])`) and never again, so a just-run analysis didn't appear until a
page reload. Fixed: the panel now takes a `refreshToken` the tool bumps after a successful
analyze, so the new entry shows immediately.

**Also fixed — meta description length:** `generate_meta_description` used `enforce_word_limit`
(a WORD limit), so the default `limit=160` produced ~160 *words* (~900+ chars) rather than the
~155–160 *characters* a SERP meta description should be. Rewritten to a character budget with
sentence-safe trimming.

**Left as-is (as the owner noted):** suggestion depth scales with the article — "light" output
reflects light input, not a defect. Worth revisiting as an upgrade, not a fix.

**Design note (feeds the frontend-redesign thought):** the auto-save-everything model and the
"Recent …" panels are worth a deliberate decision — should history be per-article, searchable,
deletable, shared across the search surfaces? Currently it's an implicit system behavior with a
thin UI. Not a bug; a design call.

**Status:** answered + the two concrete gaps fixed (panel refresh, meta length).

---

### 10. The social feed reads bare on first look — `Design`

**Observed:** the social feed looks very bare for a social feed on a first pass. Not wrong —
a design note.

**What's actually there:** the primitives exist. `Feed.jsx` renders a post composer, a
social-analytics panel (Posts / Impressions / Clicks / Avg Engagement, top posts, a trend),
post cards with interactions, a loading panel, and an empty state. So it's not unfinished
plumbing — it's minimal *presentation* over a working structure (inline styles, few visual
cues, no rich post chrome).

**The more interesting design point:** it's labelled **"Trust Feed"**, not a social feed, and
the metrics are engagement/impressions/trust-flavoured. So part of why it reads as "bare for a
social feed" may be that it isn't trying to be one — it's a trust/reputation surface wearing a
feed's shape. The design question is identity: is this meant to be a conventional social feed
(rich posts, threading, reactions, media) or a trust/reputation dashboard (scores, standing,
signal)? The current UI sits between the two, which is what makes it feel thin.

**Redesign signal:** this is the third design note in the walk (after the thin "Recent …"
history panels on SEO/LeadGen, and the search surfaces all sharing one shape). The recurring
theme: the app has the right *data and primitives* almost everywhere, but the *presentation
layer and surface identity* are underspecified. That is exactly the input a frontend redesign
wants — the bones are sound; the decisions to make are "what is each surface for, and how rich
should it be."

**Status:** design note, no code change. Feeds the frontend-redesign thread.

---

### 11. Posts don't appear after posting — `Defect`

**Observed:** post from the composer, the form clears as if it worked, but the post never shows
in the feed.

**Three layered causes (all addressed):**

1. **The social layer is MongoDB-backed, and Mongo wasn't running.** `docker-compose.prod.yml`
   ships without Mongo (social is "degradable"). With no Mongo, `create_post` and `get_feed`
   fall into their degraded branch. Added an opt-in overlay `docker-compose.mongo.yml` to run
   Mongo locally:
   `docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml up -d`.

2. **A false-success on the degraded path (the real bug).** When Mongo was absent, `create_post`
   returned a `_mongo_degraded_payload` wrapped in a **200 SUCCESS** envelope, so the client saw
   success, cleared the form, and refetched an empty feed — a silent no-op the user reads as
   "my post vanished." Now the `db is None` path raises **503** (`social_unavailable`) for both
   `create_post` and `get_feed`, so a missing/again-down social layer reads as *unavailable*,
   not *posted-and-lost*. Honest failure over silent data loss.

3. **A 500 on every successful post once Mongo WAS enabled.** `insert_one` mutates the doc in
   place, adding a Mongo `_id` (ObjectId); `create_post` returned that raw dict, and FastAPI's
   JSON encoder raised `'ObjectId' object is not iterable` → 500. (The feed was unaffected — it
   rebuilds each doc through the `SocialPost` model, which sheds `_id`.) Fixed by dropping `_id`
   after insert. Verified live: with the Mongo overlay, `POST /apps/social/post` → 200 and the
   post appears in `GET /apps/social/feed`.

**Note for deploy:** social requires Mongo. It's degradable by design, but "degraded" now means
an honest *unavailable*, not a fake success. Decide per-environment whether social is enabled.

**Status:** fixed. Social works with the Mongo overlay; the false-success + 500 are gone.

---

### 12. The feed renders nothing, and the analytics panel is structurally zeroed — `Defect`

**Observed (from the browser console, while walking `/network`):**

```
Feed.jsx:69 safeMap prevented crash. Value: {status:'SUCCESS', data: Array(7), result: Array(7), …}
```

Seven posts came back and none were on screen.

**Why:** every `/apps/social` route runs its handler through `execute_with_pipeline_sync` and
returns the standard `{status, data, result, events, next_action, trace_id}` envelope. But
`client/src/api/social.js` was the one API module with **zero** `unwrapEnvelope` calls, so the
raw envelope was handed to the components:

- `setPosts(envelope)` → `safeMap` receives an object and renders nothing. The empty state
  doesn't rescue it either: `posts.length === 0` is `undefined === 0` → false. So the stream is
  blank with no explanation — the worst of both branches.
- `analytics.overview` is read off the envelope → `undefined` → Posts / Impressions / Clicks /
  Avg Engagement all display `0`.
- View-mode `ProfileView` reads `profile.username.charAt(0)`, which throws on an envelope.

**This partly re-explains open item 10** ("the feed reads bare"). That was logged as a
presentation/identity design note, and the presentation point stands — but the analytics panel
was *also* structurally zeroed by this bug, so the surface was reading barer than it is.

**Fixed:** all six functions in `social.js` now `.then(unwrapEnvelope)`. `unwrapEnvelope` is
safe here — it only unwraps when a `data` key is present and rethrows an embedded `error`.
Regression test added at `client/src/test/social-envelope.test.jsx` (feed returns an array,
analytics exposes `overview`, profile returns the document).

**Status:** fixed.

---

### 13. `unwrapEnvelope` coverage across the client API layer is inconsistent — `Defect` (systemic)

**Observed:** item 12 was not a one-off. Auditing `client/src/api/`:

| Has `unwrapEnvelope` | Has none |
|---|---|
| `analytics`, `arm`, `tasks` | `agent`, `masterplan`, `memory`, `rippletrace`, `search`, `freelance`, `identity`, `operator` |

The same walk console also emitted ~40 `safeMap prevented crash` lines originating **inside
`@aindy/ui-kit`**, which is the same signature: a component handed an envelope where it expected
an array.

**Why it isn't a blanket fix:** not every route is enveloped — only those routed through the
execution pipeline. Applying `unwrapEnvelope` indiscriminately would corrupt any plain response
that legitimately carries a `data` key. The correct unit of work is per-module: check which of
that domain's routes wrap, then unwrap those.

**Predicted symptom while walking:** "the data exists but the screen is empty," with no error
and no empty state — precisely the shape of items 11 and 12, and previously of the dashboard
overview (#137). Tasks, MasterPlan and Memory are the next likely hits.

**Status:** diagnosed. Verify per surface as the walk reaches it rather than sweeping blind.

---

### 14. A created task never appears in the list — `Defect`

**Observed:** on `/tasks`, adding a directive appeared to do nothing — the input cleared and the
list still read "No active directives."

**The task was created correctly.** Verified live with exactly the body the UI sends
(`{name, priority}`): `POST /apps/tasks/create` → **200**, row persisted with `task_id=2`, and
`GET /apps/tasks/list` → **200** returning that task. Both ends of the round trip work.

**Why nothing rendered:** `/apps/tasks/list` nests its array one level deeper than the other
list routes. After `unwrapEnvelope` the caller holds:

```json
{ "tasks": [ { "task_id": 2, "task_name": "…" } ], "execution_envelope": { … } }
```

— an object, not an array. `TaskDashboard` then does
`Array.isArray(data) ? [...data] : []`, which discards it and falls through to the empty state.
So the screen reported "no tasks" while the API was returning one.

This is the *second* form of item 13. The first (social, item 12) was a missing unwrap; this one
has the unwrap and still fails, because a single unwrap isn't sufficient when the payload nests
the collection under a named key. Worth checking both shapes on the remaining surfaces.

**Fixed:** `getTasks` now flattens `data.tasks`, passing a bare array through unchanged and
yielding `[]` when the key is absent. Regression test at
`client/src/test/tasks-list-payload.test.jsx` (3 cases).

**Status:** fixed.

---

### 15. Is a task tracked, or executed by the AI? — `Question` (answered)

**Asked while walking `/tasks`:** the screen is titled "Execution Engine" and the input says
"Initialize new directive," which reads like work handed to the AI. Is a task something the AI
completes, or something the user tracks?

**Answer: tracked by default. AI execution exists, is opt-in, and has no UI.**

The `Task` model is a rich tracking record — status, priority, category, due/scheduled/reminder
times, recurrence, estimated hours (`duration`), actual elapsed `time_spent`, dependencies
(`depends_on` / `dependency_type`), parent/child nesting, and a `masterplan_id` link. Completing
one drives real machinery: MasterPlan ETA/WCU recalculation, the Infinity orchestrator, a TWR
score, dependency-unlock cascade.

Autonomous execution hangs off two columns — `automation_type` and `automation_config`. When
`automation_type` is set, `queue_task_automation` dispatches an `automation.execute` autonomous
job into the automation domain's connectors (social, crm, email, webhook, stripe, subscription,
content_generation).

**Two facts explain why adding a task feels inert even by design:**

1. **Automation fires on completion and unlock — never on creation.** The call sites are
   `reason="task_completed"` and `reason="task_unlocked"` in `task_service.py`. Nothing runs
   when a task is added, even a fully configured one.
2. **The UI cannot set `automation_type` at all.** `TaskCreate` accepts 13 fields; the dashboard
   sends exactly two — `{name, priority}` (`TaskDashboard.jsx` line 36). So `automation_type`,
   `automation_config`, `due_date`, `estimated_hours`, `masterplan_id`, `dependencies`,
   `recurrence`, `reminder_time` and `scheduled_time` are all reachable by the API and by agent
   tools, and unreachable from the screen.

So the surface is a plain to-do list wearing an execution engine's name, sitting on top of a
scheduler, a dependency graph, a MasterPlan link and an automation dispatcher — none of which
it exposes. The tracked-vs-executed confusion is an honest reading of what's on screen.

**Redesign signal — the strongest one yet.** Earlier notes (thin "Recent…" panels, the shared
search shape, the Trust Feed identity) were about presentation depth. This is the same pattern
at its most extreme: the backend supports scheduling, recurrence, dependencies, MasterPlan
linkage and autonomous execution, and the UI is one text input. The decision to make is what
`/tasks` is *for* — a quick capture list, a project planner over the dependency/MasterPlan
model, or the console for AI-executed work — and it can be answered without building backend.

**Status:** answered. The design decision (what to expose, and whether creation should ever
trigger automation) is open.

---

### 16. The only non-Genesis MasterPlan create route 500s — `Defect`

**Context:** raised while walking `/tasks` — "to walk the MasterPlan tab, one has to be created
via Genesis first." That is correct, and not only by design: the alternative path is broken.

There is **no** `POST /apps/masterplans`. Two creation paths exist:

1. `POST /apps/genesis/lock` → `create_masterplan_from_genesis` — the Genesis route.
2. `POST /apps/compute/create_masterplan` — a direct create from raw fields.

**Path 2 fails.** Verified live with a well-formed `MasterPlanInput` body:

```
POST /apps/compute/create_masterplan -> 500
{"detail": "'name' is an invalid keyword argument for MasterPlan"}
```

`create_masterplan_compute` does `MasterPlan(**data)`, but `MasterPlanInput` declares a `name`
field the `master_plans` table does not have. Even with `name` removed it would still fail:
`target_date` is `nullable=False` and the input never supplies it (the Genesis factory computes
it as `start_date + duration_years × 365`). The schema and the model have drifted apart, and
nothing in the client calls this route, so it went unnoticed.

**Consequence:** Genesis is the *only* working way to obtain a MasterPlan. Every downstream
surface that depends on a plan — MasterPlan dashboard, ETA/WCU projection, task→plan linkage,
the analytics masterplan endpoints — is gated behind completing a Genesis conversation.

**Note:** `GET /apps/masterplans/` returns `{plans, execution_envelope}` *unwrapped* (no
`{status, data}` envelope), and `MasterPlanDashboard` reads `data.plans` accordingly, so that
path is correct. Recording it because it is a *third* response convention alongside the two in
item 13 — enveloped, and enveloped-with-a-nested-key.

**Status:** confirmed live, unfixed. The fix needs a decision, not just a patch: `name` has no
column to land in, so either the model gains one or the schema drops it.

---

### 17. MasterPlan, Genesis/Assistant and Tasks were one section and are now disconnected — `Design`

**Observed (owner):** these three were originally a single tab/section. They are now separate
top-level routes, and the connective tissue went with the split.

**What the code confirms:**

- **Tasks cannot be attached to a plan from the UI.** `Task.masterplan_id` exists, is indexed,
  and drives ETA/WCU recalculation and the completion cascade. `TaskCreate` accepts it.
  `masterplan_id` appears in the client only in `AnalyticsPanel` and the projection context —
  **never** in the task-creation path (see item 15: the form sends `{name, priority}`).
  So every task created through the UI is permanently orphaned from every plan.
- **The link is real on the backend.** Completing a task recalculates the active plan's ETA and
  WCU and cascade-activates it (`_handle_task_completed` in `apps/tasks/bootstrap.py`). The
  machinery to make tasks and plans one system is built and running — it just never receives a
  `masterplan_id` from the surface where users create tasks.
- **Genesis is the sole entry point**, and its one alternative is broken (item 16).

So the split is not cosmetic: it severed the field that made the three surfaces one product.
This is the same "working backends, underspecified presentation" theme, but here the missing
piece is a *single field on a form*.

**Proposal raised by the owner — import a plan authored elsewhere.** Bring in a MasterPlan
drafted with an external assistant (Claude, ChatGPT), translated into A.I.N.D.Y.'s data points.
Worth recording because the insertion point is unusually clean:

- The translation target already exists. Genesis synthesis produces a **draft** — phases,
  success criteria, risk factors, ambition score, `time_horizon_years` — persisted to
  `GenesisSessionDB.draft_json`, and `create_masterplan_from_genesis` builds the plan from it
  (`structure_json`, `posture`, timeline, plus the anchor/goal fields `anchor_date`,
  `goal_value`, `goal_unit`, `goal_description`).
- So an import does **not** need a new creation pathway. It needs a translator from external
  prose into the existing draft shape, written to `draft_json` with `synthesis_ready=True` —
  after which the existing `/apps/genesis/lock` does the rest unchanged.
- That also answers where it belongs: import becomes a *way to start a Genesis session*, not a
  fourth parallel path, which keeps a single lock/versioning/audit route.
- Open questions: how much fidelity is required before a plan is "translatable"; whether the
  user reviews and edits the translated draft before locking (the audit route `/apps/genesis/audit`
  is the natural hook); and whether a low-confidence translation should drop the user into a
  Genesis conversation to fill the gaps rather than fail.

**Redesign signal:** the fourth and clearest structural one. Earlier notes were about how rich a
surface should look. This is about which surfaces should exist at all — the owner's read is that
MasterPlan, Genesis/Assistant and Tasks want to be one section again, and the orphaned
`masterplan_id` is the concrete evidence.

**Status:** design decision. The task→plan link is the smallest piece and could be fixed
independently of any redesign.

---

### 18. Analytics and KPI Snapshot — owner verdict on scope — `Design`

**Analytics (`/analytics`)** is LinkedIn analytics, and owner-specific: it reflects one person's
channel rather than anything a general user of the product would have. Flagged by the owner as a
candidate for removal rather than redesign.

**KPI Snapshot (`/kpi`)** is currently a calculate-your-own-metrics surface — the user enters
numbers and it computes. Nothing is wrong with it as built; the owner's original intent was a
**dashboard** (values derived from the system's own data), not a manual calculator.

**Status:** owner verdict recorded — two more surfaces to either redesign or remove. Not walked
in depth, since scope is the open question rather than correctness.

---

### 19. ARM Analyze — what is it analyzing, and how would it reach your file? — `Defect`

**Asked while walking `/arm/analyze`:** it is a small text box prefilled with `tests/example.py`.
What does it actually analyze, and how would it get access to the file?

**Answer: files on the SERVER's filesystem — never yours.** `validate_file_path` does
`Path(file_path).resolve()` and requires `path.exists()`, resolved relative to the API process's
working directory (`/app` in the deployed image). There is no upload, no repo connection, no
file picker, and no access to the visitor's machine. In practice it can only analyze code that
ships inside the container — A.I.N.D.Y.'s own source. It is a developer tool pointed at the
server's own source tree, presented as a general product surface.

**Three concrete defects behind that:**

1. **The prefilled default cannot succeed.** `tests/` is not in the deployed image — `/app`
   contains `README.md`, `apps`, `alembic`, `scripts`, `logs`, `build`, `pyproject.toml` and no
   `tests`. Verified live: `tests/example.py` → `404: File not found`. The out-of-the-box first
   run is guaranteed to fail.
2. **The failure is completely invisible.** A failed analysis returns **HTTP 200 with
   `status: "success"`**; the real error lands at `data.error` ("Node arm_analyze_code failed
   after N retries"). `ARMAnalyze` only sets its error state when the request *throws*, so
   nothing throws, `result` has no `summary` / scores / findings, every render block is falsy,
   and the screen shows **nothing at all** after Run Analysis. Same false-success class as the
   social degrade (item 11) and the dashboard envelope bug (#137) — this is the third instance.
3. **A valid path also fails on this stack**, but for an unrelated reason: `apps/arm/models.py`
   passes validation, is read, and then the outbound LLM call fails repeatedly
   (`external.call.failed`) — a local provider-key/config matter, not an ARM bug.

**Fixed (client):** `submit` now surfaces `res.error` (with `failed_node`) in the existing error
banner instead of silently rendering an empty page; the misleading default is cleared; the
placeholder states that the path is server-side and relative to the API working directory; and
an empty submit is guarded.

**Left open (needs the owner's intent):** what the default path *should* be, and more
fundamentally whether ARM Analyze is a product surface at all. If it is meant to analyze the
user's code, it needs an upload or a repo connection — neither exists. If it is meant to analyze
A.I.N.D.Y.'s own source, it is an internal/dev tool and should say so.

---

### 20. ARM has no project-root confinement — `Security`

**Found while answering item 19.** `validate_file_path` guards with three mechanisms: a blocked
path-segment list (`.env`, `venv`, `__pycache__`, `.git`, `secrets`, `credentials`, `keys`), an
extension allowlist (`.py .js .jsx .ts .tsx .json .md .txt .yaml .yml`), and a post-read content
scan for secret-shaped patterns. **There is no check that the resolved path stays inside the
project root.**

Verified directly against the validator in the running container:

```
/usr/local/lib/python3.11/this.py  -> ALLOWED
/app/apps/arm/models.py            -> ALLOWED
/etc/hostname                      -> blocked (422, no extension — not by confinement)
```

`/etc/passwd` and `../../etc/hosts` are rejected only because they lack an allowlisted
extension, not because they are outside the project. So any authenticated user can read **any
`.py`/`.js`/`.json`/`.yaml`/`.md`/… file anywhere on the server filesystem**, and its contents
are then sent to an external LLM provider. The content scan catches secret-shaped strings, but
it runs *after* the read and only matches known patterns — site-packages source, deployment
YAML, and application config that isn't shaped like a key all pass through.

**Recommended hardening:** resolve against an explicit configured root and require
`resolved.is_relative_to(root)`, rejecting anything outside it — a confinement check rather than
an extension guess. Cheap to add, and it makes the existing allowlist a second layer instead of
the only one.

**Status:** hardening recommended, not applied — the right root depends on the item 19 decision
about what ARM is for. Worth doing before any deployment where the API host holds anything the
signed-in user shouldn't read.

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
| genesis | Leaving the page abandoned the session; now resumes the active one | #135 |
| dashboard | Score-history sparkline crashed the panel (undefined `score_delta`) | #139 |
| assistant | Agent run looked stuck at "planning" — response-shape mismatch | #140 |
| search | Research query 500'd — `@limiter.limit` grabbed a Pydantic body named `request` | #141 |
| dashboard | Graph tab bounced to Overview — `/dashboard/graph` route was missing | #144 |
| rippletrace | Graph tab logged the user out — GraphView hit api-key-gated routes | #145 |
| seo/leadgen | "Recent …" panels didn't refresh after a run; meta description too long | #147/#148 |
| social | Posts didn't appear — Mongo overlay + ObjectId-500 fix + honest 503 degrade | #149 |
| social | Feed rendered nothing and analytics read all zeros — `social.js` never unwrapped the envelope | #150 |
| tasks | Created tasks never appeared — the list array is nested under `data.tasks` | #151 |
| arm | Analyze rendered a blank screen on failure; the default path could never resolve | (this PR) |

**Upstream:** the `/apps` mount omission belongs in `@aindy/ui-kit`; corrected app-side in
`client/src/api/_routes.js` and logged against `UIKIT-ROUTE-DRIFT-1`. The 401-logs-out-everything
behavior (open item 8) is also a `@aindy/ui-kit` request-core concern.
