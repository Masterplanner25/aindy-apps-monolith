# Search System � Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Search System is a **multi-surface AI retrieval stack** that turns queries into ranked, actionable results across SEO analysis, lead discovery, and research workflows.

It is not a single endpoint.

It is a **search orchestration layer** intended to:

* process queries
* retrieve sources
* score relevance
* persist outcomes
* feed back into execution

---

## 2. Core Lifecycle (Canonical Pipeline)

```
Query ? Processing ? Retrieval ? Ranking ? Output
```

### Query

User or system-provided search intent:

* free text
* domain-specific templates
* task or research prompts

---

### Processing

Normalization and pre-processing:

* tokenization
* query expansion
* domain filtering

---

### Retrieval

External or internal source fetch:

* web search
* stored research results
* memory recall

---

### Ranking

Scoring and ordering:

* relevance
* fit / intent scores
* semantic similarity

---

### Output

Structured results:

* ranked leads
* SEO insights
* research summaries

---

## 3. Core Components

---

### 3.1 SEO Analysis (AI SEO)

**Implementation:**

* `apps/search/routes/seo_routes.py`
* `apps/search/services/seo_services.py`

**Current Capabilities:**

* keyword extraction
* readability
* keyword density
* AI meta description (`/seo/meta`)

**Missing:**

* AI SEO improvement suggestions (stubbed)
* competitor benchmarking
* AI search ranking feedback loop

---

### 3.2 Lead Generation (B2B AI Search)

**Implementation:**

* `apps/search/services/leadgen_service.py`
* `apps/search/routes/leadgen_router.py`
* `apps/search/models/leadgen_model.py`

**Current Capabilities:**

* GPT-4o lead scoring
* DB persistence
* Memory Bridge logging
* Memory Orchestrator recall for prior leadgen context
* External retrieval via `apps/search/services/research_engine.web_search()` with structured response parsing + fallback

**Missing:**

* provider-backed lead search with richer parsing (current structured parsing is minimal)
* query template system (documented but not implemented)

---

### 3.3 Research / DeepSearch

**Implementation:**

* `apps/search/services/research_engine.py`
* `apps/search/routes/research_results_router.py`
* `apps/search/services/research_results_service.py`

**Current Capabilities:**

* research result storage
* memory logging (capture engine)
* Memory Orchestrator recall attached to `/research/query` results
* Live summary generation via `apps/search/services/research_engine.ai_analyze()`
* Live external retrieval via `apps/search/services/research_engine.web_search()`

**Missing:**

* external provider reliability/coverage guarantees (current integration is best-effort)

---

### 3.4 Memory Search (Semantic Recall)

**Implementation:**

* `AINDY/routes/memory_router.py`
* `AINDY/db/dao/memory_node_dao.py`

**Current Capabilities:**

* semantic similarity search (`/memory/nodes/search`)
* resonance recall (`/memory/recall`)

**Note:**

This capability exists but is not wired into the Search System flows documented under `AINDY/Search System/`.

---

## 4. Architectural Layers

### Retrieval Layer

* External search (implemented in research + leadgen flows)
* Internal search (Memory Bridge recall)

### Orchestration Layer

* FastAPI routes
* service modules

### Persistence Layer

* Postgres models for leadgen + research
* Memory Bridge for search outcomes

---

## 5. Current Implementation (Reality)

**Implemented:**

* basic SEO analysis endpoints
* lead scoring + DB persistence
* research result storage
* Memory Orchestrator recall used in LeadGen and Research query flow
* semantic memory search (separate system)
* live external retrieval in research and leadgen flow

**Missing:**

* (none of the original roadmap items remain) — unified search pipeline, reusable
  hybrid orchestration, shared ranking, and SEO/LeadGen/Research UI are all
  implemented; see the Phase Mapping table and Next Steps below.

---

## 6. System Classification

The Search System is currently:

> A fragmented set of partial search tools (SEO + LeadGen + Research) with an unintegrated semantic recall engine.

It is NOT:

* a unified search platform
* a full AI search optimization system

---

## 7. Evolution Plan (System Roadmap)

---

### Phase v1 � Stabilize Search Surfaces

**Goal:** Align live endpoints with documented behaviors

**Actions:**

* normalize SEO endpoints
* remove stubbed responses or mark them explicitly
* document leadgen retrieval integration ?

---

### Phase v2 � Retrieval Integration

**Goal:** Enable real retrieval for leadgen + research

**Actions:**

* wire `apps/search/services/research_engine.py` into `/research/query` ?
* replace mocked `run_ai_search()` results with real provider calls ?
* integrate Memory Orchestrator recall into search flows ?

---

### Phase v3 � Ranking Unification

**Goal:** Shared ranking layer

**Actions:**

* unify relevance scoring across SEO, leadgen, research - DONE

A shared lexical relevance signal (`lexical_relevance`) plus a `composite_score`
(0.6 relevance / 0.4 surface quality) now live in `apps/search/services/search_scoring.py`.
The `rank_items` ranker in `apps/search/schemas/search_schema.py` applies them so
every surface's `SearchResponse.results` carry one unified `score` (surface quality
preserved under `metadata.quality_score`, relevance under `metadata.relevance`).
Leadgen and research results are reordered by the composite; SEO is annotated
without reordering (it is an analysis surface, not retrieval).

**Semantic seam (SEARCH-RANKING-EMBEDDINGS-1, wired 2026-06-28):** relevance is
pluggable. `rank_items` takes a `relevance_fn` and defaults to
`default_relevance_provider()` — lexical unless `AINDY_SEARCH_EMBEDDING_RANKING`
opts into the hybrid `EmbeddingRelevanceProvider`, which scores cosine similarity
over the runtime embedding stack (`AINDY.memory.embedding_service`) and falls back
to lexical automatically when the backend is unavailable. App-profile/CI runs stay
lexical and deterministic (testing-mode embeddings return zero vectors → fallback).
**Tests:** `tests/unit/test_search_ranking.py`.

---

### Phase v4 � Feedback & Memory Loop

**Goal:** Closed-loop search system

**Actions:**

* persist outcomes to Memory Bridge
* feed results into future query weighting

---

### Phase v5 � UI + Dashboard Integration - DONE

**Goal:** Operational surface

**Actions:**

* integrate SEO + LeadGen UI into client - DONE
* add result history views - DONE

The Research, SEO, and LeadGen surfaces are now routed (`/search/research`,
`/search/seo`, `/search/leadgen`) and reachable from the sidebar + app-shell nav
(the SEO tool was previously built but orphaned, and the sidebar links pointed at
dead `/research`, `/seo`, `/leadgen` paths). A shared `client/src/components/app/SearchResults.jsx`
renders the unified ranked `results[]` with per-item rank/relevance score badges
and an overall `search_score`; Research surfaces ranked sources and SEO/Research/
LeadGen each show a `SearchHistory` result-history view.
**Tests:** `client/src/test/search-nav.test.jsx`, `client/src/test/search-results.test.jsx`.

---

## 8. Technical Debt

### Structural

* search features exist in disconnected modules
* no unified query processing layer

### Functional

* ? leadgen search now uses real retrieval (orchestrator + provider)
* ? research search executes via `/research/query`
* ranking unified: shared lexical relevance + composite score order results across surfaces
* SEO suggestions stubbed

### Conceptual

* semantic search exists but is not part of Search System flows

---

## 9. Phase Mapping

| Phase | Component            | Status      | Required Action |
| ----- | -------------------- | ----------- | --------------- |
| v1    | Surface Alignment    | Partial     | Normalize       |
| v2    | Retrieval Integration| Complete    | Maintenance only |
| v3    | Ranking Unification  | Complete    | Maintenance only |
| v4    | Feedback Loop        | Missing     | Persist + reuse |
| v5    | UI Integration       | Complete    | Maintenance only |

---

## 10. Next Steps

### Step 1 - Create a unified search service
**Files:** `apps/search/services/search_service.py`  
**Outcome:** external, internal, semantic, and hybrid search requests route through one reusable interface.

### Step 2 - Standardize search request and result schemas - DONE
**Files:** `apps/search/schemas/search_schema.py`, `apps/search/schemas/__init__.py`, `apps/search/services/search_service.py`, `apps/search/routes/leadgen_router.py`, `apps/search/flows/search_flows.py`  
**Outcome:** A shared `SearchRequest` / `SearchResultItem` / `SearchResponse` contract plus per-surface adapters (`leadgen_to_search_response`, `research_to_search_response`, `seo_to_search_response`, dispatcher `to_search_response`) now normalize every surface into one ranked shape. Leadgen and research emit compatible `results` items (`title`, `url`, `snippet`, `score`, `metadata`) and consistent top-level fields (`query`, `search_type`, `search_score`, `memory`, `learning_context`, `history_id`).

**Backward compatibility:** changes are additive — leadgen rows keep `company` / `reasoning` / `overall_score` (consumed by `client/src/components/app/LeadGen.jsx`); the shared keys are added alongside them. Research, which previously returned no result list, now also returns a normalized `results` array.

**Tests:** `tests/unit/test_search_schema_contract.py` (`-m app_profile`).

### Step 3 - Move hybrid retrieval into the shared search layer
**Files:** `apps/search/services/leadgen_service.py`, `apps/search/routes/research_results_router.py`, `apps/search/services/search_service.py`  
**Outcome:** memory recall plus external retrieval is implemented once and reused across search surfaces.

### Step 4 - Add shared search history and reuse
**Files:** `apps/search/models/leadgen_model.py`, `apps/search/models/research_results.py`, `apps/search/services/research_results_service.py`, `apps/search/services/search_service.py`  
**Outcome:** search outcomes become reusable across the system instead of staying siloed by feature.

### Step 5 - Integrate unified search into agent tools - DONE
**Files:** `apps/search/agents/tools.py`, `apps/search/agents/capabilities.py`, `apps/search/syscalls.py`
(runtime registration surfaces are consumed, not owned: `AINDY.agents.tool_registry`, `AINDY.kernel.syscall_registry`)
**Outcome:** A single `search.query` agent tool now backs all surfaces. It dispatches the new `sys.v1.search.query` syscall, which routes by `search_type` (`research` | `leadgen` | `seo_analysis` | `memory`) through `search_service` and returns the normalized `SearchResponse` (Step 2 contract). The legacy `leadgen.search` / `research.query` tools remain for backward compatibility.

**Tests:** `tests/unit/test_search_unified_tool_and_flow.py`.

### Step 6 - Expose unified search to workflow execution - DONE
**Files:** `apps/automation/flows/flow_definitions.py`, `apps/search/bootstrap.py`
(runtime execution surface consumed, not owned: `AINDY.runtime.flow_engine`)
**Outcome:** The `unified_search` workflow (`search_validate` → `search_query_execute`) dispatches `sys.v1.search.query` and surfaces the ranked `SearchResponse` under the `search_result` state key. Search is now a reusable workflow capability rather than a research-only utility. The flow is registered by reference (string syscall dispatch), so no new cross-app import dependency is introduced.

**Tests:** `tests/unit/test_search_unified_tool_and_flow.py`.

---

## 11. Governance Notes

* This document is the **canonical reference** for Search System architecture.
* Any changes must align with:

  * documented lifecycle
  * retrieval integrity
  * Memory Bridge integration rules

* Deviations must be recorded in:

  * `docs/platform/engineering/TECH_DEBT.md`
  * `docs/apps/EVOLUTION_PLAN.md`

---

## 12. Summary (Operational Truth)

The Search System is not complete when it stores results.

It is complete when:

> Queries trigger real retrieval, results are ranked and persisted, and outcomes feed back into future search behavior.
