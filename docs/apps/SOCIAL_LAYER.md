# Social Layer — Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Social Layer is a **public-facing identity and interaction system** that captures profiles, posts, and social signals, then routes them into A.I.N.D.Y. for visibility scoring and continuity.

It is not a memory system.

It is a **social execution layer** designed to:

* represent identity
* surface content
* track interactions
* feed signals into analytics and memory

---

## 2. Core Lifecycle (Canonical Pipeline)

```
Profile → Post → Feed → Signal → Insight
```

### Profile

Identity surface:

* name
* tagline
* trust tier
* metrics snapshot

---

### Post

Content surface:

* user content
* timestamp
* visibility tier
* tags

---

### Feed

Distribution layer:

* posts surfaced by relevance
* trust-tier filtering

---

### Signal

Interaction and reaction capture:

* engagement counts
* ripple or visibility metrics

---

### Insight

Analytics + feedback:

* visibility scoring
* influence tracking
* memory capture

---

## 3. Core Components

---

### 3.1 Profiles

**Implementation:**

* `apps/social/routes/social_router.py`
* `apps/social/models/social_models.py`
* MongoDB storage

**Current Capabilities:**

* create/update profiles
* fetch profile by username

---

### 3.2 Posts + Feed

**Implementation:**

* `apps/social/routes/social_router.py`
* MongoDB storage

**Current Capabilities:**

* create posts
* fetch feed with trust-tier weighted relevance scoring
* track impressions and interaction signals
* record explicit interactions (`view`, `click`, `like`, `boost`, `comment`) via
  `POST /social/posts/{post_id}/interact`
* expose social analytics summaries

**Missing:**

* comment/reply **content** model — `comments_count` is an integer counter only;
  there is no stored comment text or threaded discussion

---

### 3.3 Bridge Integration

**Implementation:**

* `apps/bridge/routes/bridge_router.py` (`/bridge/user_event`)
* `AINDY/server.js` forwards events

**Current Capabilities:**

* Node → FastAPI bridge exists
* `/bridge/user_event` persists to SQL audit table (`bridge_user_events`)

**Missing:**

* bridge / system-origin events are not surfaced in the social feed — they remain
  isolated SQL audit rows

---

### 3.4 Memory Logging

**Implementation:**

* `apps/social/routes/social_router.py` calls into the Memory Bridge via execution hints

**Current Capabilities:**

* posts are logged to Memory Bridge with DB session
* high/low engagement signals are captured as memory hints

---

### 3.5 Frontend

**Implementation:**

* `client/src/components/app/ProfileView.jsx`
* `client/src/components/app/Feed.jsx`
* `client/src/components/app/PostComposer.jsx`

**Current Capabilities:**

* UI surfaces for profiles + feed
* analytics panel and top-performing content summaries

---

## 4. Architectural Layers

### Storage Layer

* MongoDB (profiles, posts)

### Orchestration Layer

* FastAPI routes
* Node bridge (Express)

### Analytics Layer

* visibility scoring
* trust-tier influence
* engagement and conversion summaries

---

## 5. Current Implementation (Reality)

**Implemented:**

* profile upsert + fetch
* post creation
* feed listing + visibility scoring
* explicit interaction capture (view/click/like/boost/comment counters)
* Node → FastAPI bridge
* analytics summaries and trend output
* memory-backed performance feedback
* Infinity-facing social performance signals

**Missing:**

* comment/reply **content** model (threaded discussion)
* social narrative / event-driven feed surfaces (bridge + system-origin events)
* durable analytics history (metrics are flattened onto post documents)

---

## 6. Doc → Code Parity Table

| Documented Capability | Evidence in Docs | Implementation Reality | Status | Primary Files |
| --- | --- | --- | --- | --- |
| Profile CRUD | Social layer notes | Profile upsert + public fetch via MongoDB | Partial | `apps/social/routes/social_router.py`, `apps/social/models/social_models.py` |
| Post creation | Social layer notes | Post insert + list | Implemented | `apps/social/routes/social_router.py` |
| Feed ranking | Roadmap intent | Trust-tier weighted ranking + Infinity score weighting | Implemented | `apps/social/routes/social_router.py` |
| Trust-tier weighting | Roadmap intent | Trust tier weighted relevance scoring in feed | Implemented | `apps/social/routes/social_router.py` |
| Interaction capture (view/click/like/boost/comment counts) | Social layer intent | `POST /social/posts/{post_id}/interact` persists `$inc` counters and refreshes engagement signals | Implemented | `apps/social/routes/social_router.py` |
| Bridge event persistence | Bridge integration notes | `/bridge/user_event` persists to `bridge_user_events` | Implemented | `apps/bridge/routes/bridge_router.py`, `apps/automation/bridge_user_event.py` |
| Memory logging | Social layer notes | Posts logged via Memory Bridge with DB session | Implemented | `apps/social/routes/social_router.py` |
| Comment / reply threads | Social layer intent | Only a `comments_count` integer counter exists — no stored comment text or threading | Missing | `apps/social/models/social_models.py`, `apps/social/routes/social_router.py` |
| Analytics dashboard | Roadmap intent | Analytics summaries, trends, and top content are exposed in API/UI | Implemented | `apps/social/routes/social_router.py`, `client/src/components/app/Feed.jsx` |

---

## 7. Gap → File Mapping

| Gap | Impact | Files to Update |
| --- | --- | --- |
| No comment/reply content model | Social layer still lacks threaded discussion | `apps/social/routes/social_router.py`, `apps/social/models/social_models.py`, `client/src/components/app/*` |
| Bridge / system events not surfaced in feed | Audit-origin events stay isolated from the social surface | `apps/bridge/routes/bridge_router.py`, `apps/social/routes/social_router.py`, `client/src/components/app/Feed.jsx` |
| Analytics history embedded in post documents | Trend analysis is rebuilt from current counters, not durable snapshots | `apps/social/models/social_models.py`, `apps/social/services/social_performance_service.py` |
| Identity split between social and system identity | Profile state can drift across Mongo social profiles and SQL identity profiles | `apps/social/routes/social_router.py`, `apps/identity/routes/identity_router.py`, identity service/model files |

---

## 8. Risk Register

| Risk | Type | Failure Mode | Impact | Likely? |
| --- | --- | --- | --- | --- |
| Heuristic scoring noise | Product | Visibility scores may not reflect true relevance | Medium engagement | Medium |
| Divergent schemas | Technical | Social profile fields drift across code/docs | Inconsistent UI + data | Medium |
| Cross-system mismatch | Integration | Social signals are linked to Memory Bridge, but identity/profile state can still drift across systems | Inconsistent behavior and analytics context | Medium |

---

## 9. System Classification

The Social Layer is currently:

> A social interaction and analytics layer backed by MongoDB with visibility scoring, performance feedback, and bridge persistence, but without threaded discussion or broader narrative surfaces.

It is NOT:

* an influence graph
* a complete narrative/event-driven social system

---

## 10. Evolution Plan (System Roadmap)

---

### Phase v1 — Stabilize Social CRUD

**Goal:** Stable identity and content flow

**Actions:**

* normalize profile schema
* harden post creation + feed response

**Status:** Complete

---

### Phase v2 — Bridge Persistence

**Goal:** Make bridge events real

**Actions:**

* persist `/bridge/user_event` ✅

**Status:** Complete

---

### Phase v3 — Visibility Scoring

**Goal:** Ranking logic

**Actions:**

* trust-tier weighting ✅
* engagement-based ordering ✅

**Status:** Complete

---

### Phase v4 — Analytics Layer

**Goal:** Social intelligence surface

**Actions:**

* dashboards ✅
* visibility metrics ✅

**Status:** Complete

---

### Phase v5 — Feedback Loop

**Goal:** Continuous improvement

**Actions:**

* feed analytics into scoring ✅
* log visibility outcomes to Memory Bridge ✅

**Status:** Complete

---

## 11. Technical Debt

### Structural

* analytics persistence is currently embedded in post documents rather than a separate history model

### Functional

* comment/reply content is not implemented (only a counter exists)

### Conceptual

* social profile and system identity remain separate layers

---

## 12. Phase Mapping

| Phase | Component           | Status      | Required Action |
| ----- | ------------------- | ----------- | --------------- |
| v1    | CRUD + Feed         | Complete    | Maintenance only |
| v2    | Bridge Persistence  | Complete    | Maintenance only |
| v3    | Visibility Scoring  | Complete    | Maintenance only |
| v4    | Analytics Layer     | Complete    | Maintenance only |
| v5    | Feedback Loop       | Complete    | Maintenance only |

---

## 13. Next Steps

The core phases (v1–v5) are complete. The following are enhancements beyond v5.

### Completed

* **Interaction endpoints** — likes, boosts, and comment counts are persisted
  interactions via `POST /social/posts/{post_id}/interact` rather than dormant
  fields on posts. _(Done — see `apps/social/routes/social_router.py`.)_

### Remaining

#### Step 1 — Add a comment and reply content model
**Files:** `apps/social/models/social_models.py`, `apps/social/routes/social_router.py`, `client/src/components/app/Feed.jsx`
**Outcome:** the social layer supports actual discussion threads (stored comment text, author, optional parent reply) instead of a bare `comments_count` integer.

#### Step 2 — Surface bridge and system-origin events where intended
**Files:** `apps/bridge/routes/bridge_router.py`, `apps/social/routes/social_router.py`, `client/src/components/app/Feed.jsx`
**Outcome:** bridge-origin or system-origin events can appear in the social layer instead of remaining isolated audit rows.

#### Step 3 — Expand analytics history and retention
**Files:** `apps/social/models/social_models.py`, `apps/social/services/social_performance_service.py`, analytics UI components
**Outcome:** trend analysis is based on durable history rather than only current post-document counters.

#### Step 4 — Unify social profile with system identity
**Files:** `apps/social/routes/social_router.py`, `apps/identity/routes/identity_router.py`, identity service/model files
**Outcome:** Mongo social profiles and SQL identity profiles stop drifting as separate user identity systems.

---

## 14. Governance Notes

* This document is the **canonical reference** for the Social Layer.
* Any deviations must be recorded in:

  * `TECH_DEBT.md`
  * `docs/platform/governance/EVOLUTION_PLAN.md`

---

## 15. Summary (Operational Truth)

The Social Layer is not complete when posts are stored.

It is complete when:

> Social activity produces visibility signals, those signals affect ranking, and outcomes are captured as memory and analytics.
