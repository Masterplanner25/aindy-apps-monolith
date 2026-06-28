"""Unified search request / result schema (Evolution Plan — Step 2).

This module defines the shared, surface-agnostic contract that every search
surface (SEO, leadgen, research) can be normalized into. Surface routers keep
emitting their backward-compatible payloads; the adapters here turn any of
those payloads into a single ``SearchResponse`` shape so consumers (agents,
workflows, future UI) can treat leadgen and research results identically.

The adapters are pure functions over plain dicts — no DB, no I/O — so they are
cheap to call from service code and trivial to unit test.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

# Canonical search_type values used across the search surfaces.
SEARCH_TYPE_SEO = "seo_analysis"
SEARCH_TYPE_LEADGEN = "leadgen"
SEARCH_TYPE_LEAD_PREVIEW = "lead_preview"
SEARCH_TYPE_RESEARCH = "research"

_URL_RE = re.compile(r"https?://[^\s)\"']+")


class SearchRequest(BaseModel):
    """Standard inbound search request across every surface."""

    query: str
    search_type: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class SearchResultItem(BaseModel):
    """A single ranked result, shared across all search surfaces.

    Surface-specific fields (fit/intent scores, keyword densities, ...) live in
    ``metadata`` so the top-level shape stays uniform.
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    url: str | None = None
    snippet: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchMemoryRef(BaseModel):
    """Lightweight reference to the memory context attached to a search."""

    count: int = 0
    ids: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Unified, ranked search response emitted by every surface."""

    query: str
    search_type: str
    results: list[SearchResultItem] = Field(default_factory=list)
    search_score: float | None = None
    memory: SearchMemoryRef = Field(default_factory=SearchMemoryRef)
    learning_context: dict[str, Any] | None = None
    history_id: str | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _as_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _coerce_unit_score(value: Any) -> float | None:
    """Normalize a score onto the 0..1 range.

    Surfaces are inconsistent: leadgen ``overall_score`` is 0..100 while the
    shared scorers emit 0..1. Anything > 1 is treated as a percentage.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num > 1.0:
        num = num / 100.0
    return max(0.0, min(1.0, num))


def _memory_ref(payload: dict[str, Any]) -> SearchMemoryRef:
    mem = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    ids = [str(i) for i in (mem.get("ids") or [])]
    count = mem.get("count")
    if count is None:
        items = mem.get("items") or []
        count = len(items) if isinstance(items, list) else 0
    return SearchMemoryRef(count=int(count or 0), ids=ids)


def _company_from_url(url: str) -> str:
    domain = urlparse(url).netloc or url
    return domain.replace("www.", "").split(".")[0].replace("-", " ").title() or "Unknown"


# --------------------------------------------------------------------------- #
# Surface adapters
# --------------------------------------------------------------------------- #
def lead_result_item(row: dict[str, Any]) -> SearchResultItem:
    """Map a single leadgen/lead-preview row onto the shared item shape."""
    url = row.get("url") or None
    title = row.get("company") or row.get("title") or (
        _company_from_url(url) if url else "Unknown"
    )
    snippet = row.get("context") or row.get("reasoning") or row.get("snippet")
    score = _coerce_unit_score(
        row.get("search_score")
        if row.get("search_score") is not None
        else row.get("overall_score")
    )
    metadata = {
        k: row[k]
        for k in (
            "fit_score",
            "intent_score",
            "data_quality_score",
            "overall_score",
            "reasoning",
        )
        if k in row and row[k] is not None
    }
    return SearchResultItem(title=title, url=url, snippet=snippet, score=score, metadata=metadata)


def enrich_lead_row(row: dict[str, Any]) -> dict[str, Any]:
    """Additively add the shared item fields to a leadgen row in place.

    Existing keys (``company``, ``overall_score``, ``reasoning``, ...) are kept
    so legacy consumers and the UI keep working; the common ``title``/``snippet``
    /``score`` keys are added only when absent. Returns the same dict.
    """
    if not isinstance(row, dict):
        return row
    common = lead_result_item(row).model_dump()
    for key in ("title", "url", "snippet", "score"):
        row.setdefault(key, common.get(key))
    return row


def rank_items(
    query: str,
    items: list[SearchResultItem],
    *,
    reorder: bool = True,
    relevance_fn: Any = None,
) -> list[SearchResultItem]:
    """Score items by a shared relevance+quality composite and (optionally) sort.

    Each surface puts its own quality score in ``item.score``; this preserves it
    under ``metadata.quality_score``, records ``metadata.relevance``, and sets
    ``item.score`` to the unified composite so every surface ranks on one axis
    (Evolution Plan — Phase v3). With no usable query the items pass through
    unchanged so callers never see scores deflated by a missing signal.

    ``relevance_fn`` is the pluggable relevance signal — a callable
    ``(query, text) -> float`` on 0..1. It defaults to
    ``default_relevance_provider()``, which is lexical unless the embedding seam
    is enabled (TECH_DEBT SEARCH-RANKING-EMBEDDINGS-1); the embedding provider
    falls back to lexical on its own when the backend is unavailable, so the
    default is always safe.
    """
    if not items or not (query or "").strip():
        return list(items)
    from apps.search.services.search_scoring import (
        composite_score,
        default_relevance_provider,
    )

    if relevance_fn is None:
        relevance_fn = default_relevance_provider()

    ranked: list[SearchResultItem] = []
    for item in items:
        text = " ".join(part for part in (item.title, item.snippet) if part)
        relevance = relevance_fn(query, text)
        quality = item.score if item.score is not None else 0.0
        composite = composite_score(relevance, quality)
        metadata = dict(item.metadata or {})
        metadata.setdefault("quality_score", round(quality, 4))
        metadata["relevance"] = round(relevance, 4)
        ranked.append(item.model_copy(update={"score": round(composite, 4), "metadata": metadata}))
    if reorder:
        ranked.sort(key=lambda i: i.score if i.score is not None else 0.0, reverse=True)
    return ranked


def leadgen_to_search_response(payload: Any) -> SearchResponse:
    """Normalize a leadgen / lead-preview payload into a ``SearchResponse``."""
    data = _as_dict(payload)
    query = data.get("query", "")
    items = rank_items(
        query,
        [
            lead_result_item(row)
            for row in (data.get("results") or [])
            if isinstance(row, dict)
        ],
    )
    search_score = items[0].score if items else data.get("search_score")

    return SearchResponse(
        query=query,
        search_type=data.get("search_type") or SEARCH_TYPE_LEADGEN,
        results=items,
        search_score=search_score,
        memory=_memory_ref(data),
        learning_context=data.get("learning_context"),
        history_id=data.get("history_id"),
    )


def research_to_search_response(payload: Any) -> SearchResponse:
    """Normalize a research / unified-query payload into a ``SearchResponse``."""
    data = _as_dict(payload)
    query = data.get("query", "")
    summary = (data.get("summary") or "").strip()
    search_score = data.get("search_score")
    source = data.get("source")

    items: list[SearchResultItem] = []
    if summary:
        items.append(
            SearchResultItem(
                title=query or "Research summary",
                url=None,
                snippet=summary,
                score=_coerce_unit_score(search_score),
                metadata={"source": source} if source else {},
            )
        )

    # Surface any source URLs found in the raw excerpt as additional results.
    seen: set[str] = set()
    for url in _URL_RE.findall(data.get("raw_excerpt") or ""):
        if url in seen:
            continue
        seen.add(url)
        items.append(
            SearchResultItem(
                title=_company_from_url(url),
                url=url,
                snippet=None,
                score=None,
                metadata={"source": "raw_excerpt"},
            )
        )
        if len(items) >= 6:
            break

    items = rank_items(query, items)
    return SearchResponse(
        query=query,
        search_type=data.get("search_type") or SEARCH_TYPE_RESEARCH,
        results=items,
        search_score=items[0].score if items else search_score,
        memory=_memory_ref(data),
        learning_context=data.get("learning_context"),
        history_id=data.get("history_id"),
    )


def seo_to_search_response(payload: Any) -> SearchResponse:
    """Normalize an SEO analysis payload into a ``SearchResponse``."""
    data = _as_dict(payload)
    query = data.get("query", "")
    search_score = data.get("search_score")
    densities = data.get("keyword_densities") or {}

    items: list[SearchResultItem] = [
        SearchResultItem(
            title="SEO analysis",
            url=None,
            snippet=None,
            score=_coerce_unit_score(search_score),
            metadata={
                "readability": data.get("readability"),
                "word_count": data.get("word_count"),
                "top_keywords": data.get("top_keywords") or [],
            },
        )
    ]
    for keyword in (data.get("top_keywords") or [])[:5]:
        items.append(
            SearchResultItem(
                title=str(keyword),
                url=None,
                snippet=None,
                score=_coerce_unit_score(densities.get(keyword)),
                metadata={"keyword_density": densities.get(keyword)},
            )
        )

    # SEO is an analysis surface, not retrieval: annotate relevance for parity
    # but keep the analysis-then-keywords order and the SEO quality score.
    items = rank_items(query, items, reorder=False)
    return SearchResponse(
        query=query,
        search_type=data.get("search_type") or SEARCH_TYPE_SEO,
        results=items,
        search_score=search_score,
        memory=_memory_ref(data),
        learning_context=data.get("learning_context"),
        history_id=data.get("history_id"),
    )


_ADAPTERS = {
    SEARCH_TYPE_SEO: seo_to_search_response,
    SEARCH_TYPE_LEADGEN: leadgen_to_search_response,
    SEARCH_TYPE_LEAD_PREVIEW: leadgen_to_search_response,
    SEARCH_TYPE_RESEARCH: research_to_search_response,
}


def to_search_response(payload: Any, search_type: str | None = None) -> SearchResponse:
    """Dispatch a raw surface payload to the correct adapter.

    ``search_type`` overrides the value embedded in the payload; when neither is
    present the research adapter is used as the most general fallback.
    """
    data = _as_dict(payload)
    resolved = (search_type or data.get("search_type") or SEARCH_TYPE_RESEARCH).lower()
    adapter = _ADAPTERS.get(resolved, research_to_search_response)
    response = adapter(data)
    if search_type:
        response.search_type = search_type
    return response


__all__ = [
    "SEARCH_TYPE_SEO",
    "SEARCH_TYPE_LEADGEN",
    "SEARCH_TYPE_LEAD_PREVIEW",
    "SEARCH_TYPE_RESEARCH",
    "SearchRequest",
    "SearchResultItem",
    "SearchMemoryRef",
    "SearchResponse",
    "rank_items",
    "lead_result_item",
    "enrich_lead_row",
    "leadgen_to_search_response",
    "research_to_search_response",
    "seo_to_search_response",
    "to_search_response",
]
