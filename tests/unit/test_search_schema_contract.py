"""Contract tests for the unified search schema (Evolution Plan — Step 2).

These exercise the pure adapter functions that normalize each search surface
(leadgen, research, SEO) into the shared ``SearchResponse`` shape. No DB or
network is required.
"""

from __future__ import annotations

import pytest

from apps.search.schemas import (
    SEARCH_TYPE_LEADGEN,
    SEARCH_TYPE_RESEARCH,
    SEARCH_TYPE_SEO,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    enrich_lead_row,
    leadgen_to_search_response,
    research_to_search_response,
    seo_to_search_response,
    to_search_response,
)

pytestmark = pytest.mark.app_profile


def test_search_request_defaults_and_bounds():
    req = SearchRequest(query="ai consultants")
    assert req.query == "ai consultants"
    assert req.search_type is None
    assert req.limit == 10
    with pytest.raises(ValueError):
        SearchRequest(query="x", limit=0)
    with pytest.raises(ValueError):
        SearchRequest(query="x", limit=999)


def test_leadgen_adapter_maps_rows_and_metadata():
    payload = {
        "query": "fintech leads",
        "search_type": SEARCH_TYPE_LEADGEN,
        "results": [
            {
                "company": "Acme Corp",
                "url": "https://acme.example.com",
                "reasoning": "Strong intent signals",
                "fit_score": 80,
                "intent_score": 90,
                "data_quality_score": 70,
                "overall_score": 85,
            }
        ],
        "memory": {"count": 2, "ids": ["m1", "m2"]},
        "history_id": "h-1",
    }
    resp = leadgen_to_search_response(payload)
    assert isinstance(resp, SearchResponse)
    assert resp.search_type == SEARCH_TYPE_LEADGEN
    assert resp.query == "fintech leads"
    assert resp.history_id == "h-1"
    assert resp.memory.count == 2 and resp.memory.ids == ["m1", "m2"]

    item = resp.results[0]
    assert item.title == "Acme Corp"
    assert item.url == "https://acme.example.com"
    assert item.snippet == "Strong intent signals"
    # overall_score 85 (0..100) normalizes onto 0..1
    assert item.score == pytest.approx(0.85)
    assert item.metadata["fit_score"] == 80
    assert item.metadata["overall_score"] == 85
    # top-level search_score derived from item scores
    assert resp.search_score == pytest.approx(0.85)


def test_leadgen_adapter_derives_company_from_url_when_missing():
    resp = leadgen_to_search_response(
        {"results": [{"url": "https://www.deep-search.io/path"}]}
    )
    assert resp.results[0].title == "Deep Search"


def test_research_adapter_builds_summary_and_extracts_sources():
    payload = {
        "query": "market sizing",
        "summary": "The TAM is large and growing.",
        "source": "external_search",
        "search_score": 0.6,
        "raw_excerpt": "see https://a.example.com and https://b.example.com here",
        "memory": {"items": [{"id": "x"}]},
    }
    resp = research_to_search_response(payload)
    assert resp.search_type == SEARCH_TYPE_RESEARCH
    # first item is the summary
    assert resp.results[0].snippet == "The TAM is large and growing."
    assert resp.results[0].score == pytest.approx(0.6)
    assert resp.results[0].metadata["source"] == "external_search"
    # source URLs surface as additional results
    urls = [i.url for i in resp.results if i.url]
    assert "https://a.example.com" in urls
    assert "https://b.example.com" in urls
    # memory count inferred from items length
    assert resp.memory.count == 1


def test_research_adapter_empty_summary_yields_no_summary_item():
    resp = research_to_search_response({"query": "q", "summary": "   "})
    assert all(i.snippet is None for i in resp.results)


def test_seo_adapter_emits_analysis_and_keyword_items():
    payload = {
        "query": "content",
        "search_type": SEARCH_TYPE_SEO,
        "search_score": 0.72,
        "readability": 65.0,
        "word_count": 800,
        "top_keywords": ["growth", "ai"],
        "keyword_densities": {"growth": 1.5, "ai": 2.0},
    }
    resp = seo_to_search_response(payload)
    assert resp.search_type == SEARCH_TYPE_SEO
    assert resp.results[0].title == "SEO analysis"
    assert resp.results[0].metadata["word_count"] == 800
    keyword_titles = [i.title for i in resp.results[1:]]
    assert keyword_titles == ["growth", "ai"]


def test_to_search_response_dispatch_and_override():
    leadgen_payload = {"search_type": SEARCH_TYPE_LEADGEN, "results": []}
    assert to_search_response(leadgen_payload).search_type == SEARCH_TYPE_LEADGEN
    # explicit override wins over embedded type
    forced = to_search_response({"results": []}, search_type="custom")
    assert forced.search_type == "custom"
    # unknown/missing type falls back to research adapter
    assert to_search_response({"query": "q"}).search_type == SEARCH_TYPE_RESEARCH


def test_enrich_lead_row_is_additive():
    row = {
        "company": "Globex",
        "url": "https://globex.example.com",
        "reasoning": "Active hiring",
        "overall_score": 90,
        "search_score": 0.5,
    }
    enriched = enrich_lead_row(row)
    # legacy keys preserved untouched
    assert enriched["company"] == "Globex"
    assert enriched["overall_score"] == 90
    assert enriched["reasoning"] == "Active hiring"
    # shared keys added
    assert enriched["title"] == "Globex"
    assert enriched["snippet"] == "Active hiring"
    # search_score (0.5) preferred over overall_score for the unit score
    assert enriched["score"] == pytest.approx(0.5)


def test_leadgen_and_research_share_a_compatible_structure():
    """Both surfaces must expose the same top-level and per-item field set."""
    leadgen = leadgen_to_search_response(
        {"query": "q", "results": [{"company": "A", "url": "https://a.io", "overall_score": 50}]}
    )
    research = research_to_search_response(
        {"query": "q", "summary": "s", "search_score": 0.4}
    )
    assert set(leadgen.model_dump().keys()) == set(research.model_dump().keys())
    item_fields = set(SearchResultItem.model_fields.keys())
    for resp in (leadgen, research):
        for item in resp.results:
            assert set(item.model_dump().keys()) == item_fields
