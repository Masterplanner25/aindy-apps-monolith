"""Tests for the shared relevance + ranking layer (Evolution Plan — Phase v3).

Covers the lexical relevance signal, the composite score, and how the unified
adapters rank results so every surface orders on one axis.
"""

from __future__ import annotations

import pytest

from apps.search.schemas import (
    SearchResultItem,
    leadgen_to_search_response,
    rank_items,
    research_to_search_response,
    seo_to_search_response,
)
from apps.search.services.search_scoring import (
    EmbeddingRelevanceProvider,
    composite_score,
    default_relevance_provider,
    embedding_ranking_enabled,
    embedding_relevance,
    lexical_relevance,
    tokenize,
)

pytestmark = pytest.mark.app_profile


def test_tokenize_drops_stopwords_and_single_chars():
    assert tokenize("The AI-driven Cloud platform") == ["ai", "driven", "cloud", "platform"]
    assert tokenize("") == []


def test_lexical_relevance_bounds():
    assert lexical_relevance("cloud security", "cloud security platform") == pytest.approx(1.0)
    assert lexical_relevance("cloud security", "unrelated marketing copy") == 0.0
    assert lexical_relevance("", "anything") == 0.0
    partial = lexical_relevance("cloud security tooling", "we sell cloud widgets")
    assert 0.0 < partial < 1.0


def test_composite_score_weighting():
    # default relevance_weight=0.6
    assert composite_score(1.0, 0.0) == pytest.approx(0.6)
    assert composite_score(0.0, 1.0) == pytest.approx(0.4)
    assert composite_score(1.0, 1.0) == pytest.approx(1.0)
    # custom weight
    assert composite_score(1.0, 0.0, relevance_weight=0.9) == pytest.approx(0.9)


def test_rank_items_reorders_and_annotates():
    items = [
        SearchResultItem(title="Generic Co", snippet="general services", score=0.9),
        SearchResultItem(title="Cloud Security Inc", snippet="cloud security platform", score=0.4),
    ]
    ranked = rank_items("cloud security", items)
    # relevance (weight 0.6) lifts the lower-quality but on-topic item to the top
    assert ranked[0].title == "Cloud Security Inc"
    assert ranked[0].metadata["relevance"] == pytest.approx(1.0)
    assert ranked[0].metadata["quality_score"] == pytest.approx(0.4)
    assert ranked[0].score == pytest.approx(0.76)
    assert ranked[1].score == pytest.approx(0.36)


def test_rank_items_passthrough_without_query():
    items = [SearchResultItem(title="X", score=0.5)]
    out = rank_items("   ", items)
    assert out[0].score == pytest.approx(0.5)
    assert "relevance" not in out[0].metadata


def test_leadgen_adapter_ranks_relevance_over_quality():
    payload = {
        "query": "cloud security",
        "results": [
            {"company": "BigBudget Co", "url": "https://big.io", "context": "ads", "overall_score": 90},
            {"company": "Cloud Security Inc", "url": "https://sec.io",
             "context": "cloud security platform", "overall_score": 40},
        ],
    }
    resp = leadgen_to_search_response(payload)
    assert resp.results[0].title == "Cloud Security Inc"
    assert resp.search_score == pytest.approx(resp.results[0].score)
    assert resp.results[0].score > resp.results[1].score


def test_research_adapter_ranks_summary_above_bare_sources():
    payload = {
        "query": "edge inference latency",
        "summary": "Edge inference latency keeps dropping with new accelerators.",
        "search_score": 0.5,
        "raw_excerpt": "https://vendor.example.com",
    }
    resp = research_to_search_response(payload)
    # the on-topic summary outranks the bare source URL
    assert resp.results[0].snippet.startswith("Edge inference latency")
    assert resp.results[0].score >= resp.results[-1].score


# --------------------------------------------------------------------------- #
# Semantic (embedding-backed) ranking seam — SEARCH-RANKING-EMBEDDINGS-1
# --------------------------------------------------------------------------- #
def test_embedding_ranking_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AINDY_SEARCH_EMBEDDING_RANKING", raising=False)
    assert embedding_ranking_enabled() is False
    # default provider is the bare lexical function when the seam is off
    assert default_relevance_provider() is lexical_relevance


def test_embedding_ranking_flag_selects_provider(monkeypatch):
    monkeypatch.setenv("AINDY_SEARCH_EMBEDDING_RANKING", "1")
    assert embedding_ranking_enabled() is True
    assert isinstance(default_relevance_provider(), EmbeddingRelevanceProvider)


def test_embedding_relevance_falls_back_to_lexical_when_unavailable(monkeypatch):
    """Zero-vector backend (testing/CI, API down) must degrade to lexical."""
    import AINDY.memory.embedding_service as es

    monkeypatch.setattr(es, "generate_query_embedding", lambda text: [0.0, 0.0, 0.0])
    q, t = "cloud security", "cloud security platform"
    assert embedding_relevance(q, t) == pytest.approx(lexical_relevance(q, t))


def test_embedding_relevance_uses_cosine_when_available(monkeypatch):
    import AINDY.memory.embedding_service as es

    def fake_embed(text):
        return {
            "query": [1.0, 0.0],
            "near": [1.0, 0.0],   # identical direction -> cosine 1.0
            "far": [0.0, 1.0],    # orthogonal -> cosine 0.0
        }.get(text, [0.0, 0.0])

    monkeypatch.setattr(es, "generate_query_embedding", fake_embed)
    # real cosine_similarity (pure-Python fallback) is used
    assert embedding_relevance("query", "near") == pytest.approx(1.0)
    assert embedding_relevance("query", "far") == pytest.approx(0.0)


def test_embedding_provider_caches_query_and_docs(monkeypatch):
    import AINDY.memory.embedding_service as es

    calls: list[str] = []

    def fake_embed(text):
        calls.append(text)
        return {"query": [1.0, 0.0], "doc": [1.0, 0.0]}.get(text, [0.0, 0.0])

    monkeypatch.setattr(es, "generate_query_embedding", fake_embed)
    provider = EmbeddingRelevanceProvider()
    provider("query", "doc")
    provider("query", "doc")
    # query embedded once for the pass; doc embedding cached after first call
    assert calls.count("query") == 1
    assert calls.count("doc") == 1


def test_rank_items_uses_embeddings_when_enabled(monkeypatch):
    import AINDY.memory.embedding_service as es

    def fake_embed(text):
        # the on-topic doc shares the query direction; the high-quality
        # off-topic doc is orthogonal, so semantic ranking should flip them
        return {
            "cloud security": [1.0, 0.0],
            "Cloud Security Inc cloud security platform": [1.0, 0.0],
            "Generic Co general services": [0.0, 1.0],
        }.get(text, [0.0, 0.0])

    monkeypatch.setattr(es, "generate_query_embedding", fake_embed)
    monkeypatch.setenv("AINDY_SEARCH_EMBEDDING_RANKING", "1")

    items = [
        SearchResultItem(title="Generic Co", snippet="general services", score=0.9),
        SearchResultItem(title="Cloud Security Inc", snippet="cloud security platform", score=0.4),
    ]
    ranked = rank_items("cloud security", items)
    assert ranked[0].title == "Cloud Security Inc"
    assert ranked[0].metadata["relevance"] == pytest.approx(1.0)


def test_seo_adapter_annotates_relevance_without_reordering():
    payload = {
        "query": "growth content",
        "search_score": 0.72,
        "readability": 65.0,
        "word_count": 800,
        "top_keywords": ["growth", "ai"],
        "keyword_densities": {"growth": 1.5, "ai": 2.0},
    }
    resp = seo_to_search_response(payload)
    # analysis item stays first; SEO keeps its own quality score
    assert resp.results[0].title == "SEO analysis"
    assert resp.search_score == pytest.approx(0.72)
    # relevance still annotated for parity with the other surfaces
    assert "relevance" in resp.results[0].metadata
