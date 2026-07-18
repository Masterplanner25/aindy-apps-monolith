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
from apps.search.schemas.search_schema import to_search_response
from apps.search.services.search_scoring import (
    EmbeddingRelevanceProvider,
    composite_score,
    default_relevance_provider,
    embedding_ranking_enabled,
    embedding_relevance,
    lexical_relevance,
    outcome_nudge,
    outcome_weighting_enabled,
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


# --------------------------------------------------------------------------- #
# Outcome→query ranking weighting — Search v4 §8
# --------------------------------------------------------------------------- #
def test_outcome_weighting_flag(monkeypatch):
    monkeypatch.delenv("AINDY_SEARCH_OUTCOME_WEIGHTING", raising=False)
    assert outcome_weighting_enabled() is False
    monkeypatch.setenv("AINDY_SEARCH_OUTCOME_WEIGHTING", "1")
    assert outcome_weighting_enabled() is True


def test_outcome_nudge_bounds_and_sign():
    assert outcome_nudge(0.0) == 0.0
    assert outcome_nudge(None) == 0.0
    assert outcome_nudge(1.0) > 0.0
    assert outcome_nudge(-1.0) < 0.0
    assert outcome_nudge(-1.0) == pytest.approx(-outcome_nudge(1.0))
    # saturating: no amount of feedback exceeds ±max_nudge (0.15)
    assert outcome_nudge(1000.0) <= 0.15
    assert outcome_nudge(1000.0) == pytest.approx(0.15, abs=1e-6)
    # monotonic in weight
    assert outcome_nudge(2.0) > outcome_nudge(0.5)


def test_rank_items_ignores_outcome_weights_when_absent():
    items = [SearchResultItem(title="A", url="https://a.io", snippet="cloud", score=0.5)]
    ranked = rank_items("cloud", items)  # no outcome_weights
    assert "outcome_weight" not in ranked[0].metadata
    baseline = ranked[0].score
    same = rank_items("cloud", items, outcome_weights={})  # empty map is a no-op
    assert same[0].score == pytest.approx(baseline)
    assert "outcome_weight" not in same[0].metadata


def test_rank_items_applies_outcome_nudge_and_annotates():
    items = [SearchResultItem(title="A", url="https://a.io", snippet="cloud security", score=0.5)]
    base = rank_items("cloud security", items)[0].score
    lifted = rank_items(
        "cloud security", items, outcome_weights={"https://a.io": 1.0}
    )[0]
    assert lifted.score == pytest.approx(base + outcome_nudge(1.0), abs=1e-4)
    assert lifted.metadata["outcome_weight"] == pytest.approx(1.0)
    assert lifted.metadata["outcome_nudge"] == pytest.approx(outcome_nudge(1.0), abs=1e-4)


def test_outcome_weight_can_flip_close_results():
    # two near-tied results; feedback tips the balance
    items = [
        SearchResultItem(title="First", url="https://first.io", snippet="cloud security", score=0.5),
        SearchResultItem(title="Second", url="https://second.io", snippet="cloud security", score=0.5),
    ]
    # equal relevance+quality -> stable order without feedback
    neutral = rank_items("cloud security", items)
    assert [r.url for r in neutral] == ["https://first.io", "https://second.io"]
    # a strong positive on the second + a dismissal on the first flips them
    flipped = rank_items(
        "cloud security",
        items,
        outcome_weights={"https://first.io": -1.0, "https://second.io": 1.0},
    )
    assert flipped[0].url == "https://second.io"


def test_outcome_weight_keys_on_url_then_title():
    items = [SearchResultItem(title="Bare Title", snippet="cloud", score=0.5)]  # no url
    lifted = rank_items("cloud", items, outcome_weights={"Bare Title": 1.0})[0]
    assert lifted.metadata["outcome_weight"] == pytest.approx(1.0)


def test_to_search_response_forwards_outcome_weights_to_leadgen():
    payload = {
        "query": "cloud security",
        "results": [
            {"company": "Alpha", "url": "https://alpha.io", "context": "cloud security", "overall_score": 50},
            {"company": "Beta", "url": "https://beta.io", "context": "cloud security", "overall_score": 50},
        ],
    }
    resp = to_search_response(
        payload, search_type="leadgen", outcome_weights={"https://beta.io": 1.0}
    )
    assert resp.results[0].url == "https://beta.io"


def test_to_search_response_seo_ignores_outcome_weights():
    payload = {
        "query": "growth content",
        "search_score": 0.72,
        "readability": 65.0,
        "word_count": 800,
        "top_keywords": ["growth"],
        "keyword_densities": {"growth": 1.5},
    }
    # SEO is an analysis surface; weights must not raise or reorder it
    resp = to_search_response(
        payload, search_type="seo_analysis", outcome_weights={"SEO analysis": 1.0}
    )
    assert resp.results[0].title == "SEO analysis"
    assert "outcome_weight" not in resp.results[0].metadata


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
