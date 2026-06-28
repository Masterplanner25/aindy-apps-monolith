"""Tests for the unified search agent tool + workflow (Evolution Plan Steps 5/6).

Step 5 — one search contract for agents: the ``search.query`` tool dispatches the
``sys.v1.search.query`` syscall, which routes leadgen / research / SEO / memory
through ``search_service`` and returns a normalized ``SearchResponse``.

Step 6 — the same contract exposed as the reusable ``unified_search`` workflow.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile


def _ctx(user_id: str = "11111111-1111-1111-1111-111111111111"):
    # _db non-None => handler treats it as an external session it must not close.
    return SimpleNamespace(metadata={"_db": object()}, user_id=user_id)


# --------------------------------------------------------------------------- #
# Step 5 — unified syscall routing
# --------------------------------------------------------------------------- #
def test_search_syscall_requires_query():
    from apps.search import syscalls

    with pytest.raises(ValueError):
        syscalls._handle_search_query({"query": "  "}, _ctx())


def test_search_syscall_routes_research_by_default(monkeypatch):
    from apps.search import syscalls
    from apps.search.services import search_service

    captured = {}

    def fake_unified(query, db=None, user_id=None):
        captured["query"] = query
        return {
            "query": query,
            "summary": "a research summary",
            "search_score": 0.6,
            "memory": {"count": 1, "ids": ["m1"]},
            "raw_excerpt": "",
        }

    monkeypatch.setattr(search_service, "unified_query", fake_unified)

    out = syscalls._handle_search_query({"query": "market sizing"}, _ctx())
    assert out["search_type"] == "research"
    assert out["query"] == "market sizing"
    assert out["results"][0]["snippet"] == "a research summary"
    assert out["search_score"] == pytest.approx(0.6)
    assert out["memory"]["count"] == 1
    assert captured["query"] == "market sizing"


def test_search_syscall_routes_leadgen(monkeypatch):
    from apps.search import syscalls
    from apps.search.services import search_service

    def fake_leads(query, db=None, user_id=None, max_results=3):
        return {
            "query": query,
            "results": [
                {"company": "Acme", "url": "https://acme.io", "context": "hiring", "overall_score": 80}
            ],
            "memory": {"count": 0, "ids": []},
        }

    monkeypatch.setattr(search_service, "search_leads", fake_leads)

    out = syscalls._handle_search_query(
        {"query": "fintech leads", "search_type": "leadgen", "limit": 5}, _ctx()
    )
    assert out["search_type"] == "leadgen"
    item = out["results"][0]
    assert item["title"] == "Acme"
    assert item["url"] == "https://acme.io"
    assert item["score"] == pytest.approx(0.8)


def test_search_syscall_routes_seo(monkeypatch):
    from apps.search import syscalls
    from apps.search.services import search_service

    def fake_seo(text, top_n=10, db=None, user_id=None):
        return {
            "query": text,
            "search_score": 0.7,
            "readability": 60.0,
            "word_count": 500,
            "top_keywords": ["ai"],
            "keyword_densities": {"ai": 2.0},
        }

    monkeypatch.setattr(search_service, "analyze_seo_content", fake_seo)

    out = syscalls._handle_search_query(
        {"query": "some content", "search_type": "seo_analysis"}, _ctx()
    )
    assert out["search_type"] == "seo_analysis"
    assert out["results"][0]["title"] == "SEO analysis"


def test_search_syscall_routes_memory(monkeypatch):
    from apps.search import syscalls
    from apps.search.services import search_service

    def fake_memory(query, db=None, user_id=None, tags=None, limit=5):
        return {
            "items": [{"title": "prior note", "content": "remembered context", "id": "n1"}],
            "ids": ["n1"],
            "count": 1,
        }

    monkeypatch.setattr(search_service, "search_memory", fake_memory)

    out = syscalls._handle_search_query(
        {"query": "what did we learn", "search_type": "memory"}, _ctx()
    )
    assert out["search_type"] == "memory"
    assert out["memory"]["count"] == 1
    assert out["results"][0]["title"] == "prior note"
    assert out["results"][0]["snippet"] == "remembered context"


def test_all_branches_share_the_same_top_level_shape(monkeypatch):
    from apps.search import syscalls
    from apps.search.services import search_service

    monkeypatch.setattr(
        search_service, "unified_query",
        lambda q, db=None, user_id=None: {"query": q, "summary": "s", "search_score": 0.1},
    )
    monkeypatch.setattr(
        search_service, "search_leads",
        lambda q, db=None, user_id=None, max_results=3: {"query": q, "results": []},
    )
    research = syscalls._handle_search_query({"query": "q"}, _ctx())
    leadgen = syscalls._handle_search_query({"query": "q", "search_type": "leadgen"}, _ctx())
    assert set(research.keys()) == set(leadgen.keys())


# --------------------------------------------------------------------------- #
# Step 5 — agent tool wiring
# --------------------------------------------------------------------------- #
def test_search_query_tool_dispatches_unified_syscall(monkeypatch):
    from apps.search.agents import tools

    calls = {}

    def fake_invoke(syscall_name, args, *, user_id, capability):
        calls.update(name=syscall_name, args=args, user_id=user_id, capability=capability)
        return {"query": args.get("query"), "search_type": "research", "results": []}

    monkeypatch.setattr(tools, "invoke_tool_syscall", fake_invoke)

    out = tools.search_query({"query": "q", "search_type": "research"}, "user-9", db=None)
    assert calls["name"] == "sys.v1.search.query"
    assert calls["capability"] == "search.query"
    assert calls["user_id"] == "user-9"
    assert out["search_type"] == "research"


def test_search_tool_and_capability_are_registered():
    from AINDY.agents.tool_registry import TOOL_REGISTRY
    from apps.search.agents import capabilities, tools

    try:
        tools.register()
    except Exception:
        pass  # idempotent re-registration during a shared test session
    try:
        capabilities.register()
    except Exception:
        pass

    assert "search.query" in TOOL_REGISTRY


def test_unified_search_syscall_is_registered():
    from apps.search.syscalls import register_search_syscall_handlers
    from AINDY.kernel.syscall_registry import get_registered_syscalls

    try:
        register_search_syscall_handlers()
    except Exception:
        pass
    registry = get_registered_syscalls()
    names = list(registry.keys()) if hasattr(registry, "keys") else [
        getattr(s, "name", s) for s in registry
    ]
    assert "sys.v1.search.query" in names


# --------------------------------------------------------------------------- #
# Step 6 — unified_search workflow
# --------------------------------------------------------------------------- #
def test_search_validate_node_requires_query():
    from apps.automation.flows import flow_definitions as fd

    assert fd.search_validate({}, {})["status"] == "FAILURE"
    assert fd.search_validate({"query": "x"}, {})["status"] == "SUCCESS"


def test_search_query_execute_wraps_result_under_search_result(monkeypatch):
    from apps.automation.flows import flow_definitions as fd

    response = {"query": "q", "search_type": "research", "results": [], "search_score": 0.5}
    monkeypatch.setattr(
        fd, "_syscall_node",
        lambda name, state, context, capability: {"status": "SUCCESS", "output_patch": response},
    )
    out = fd.search_query_execute({"query": "q"}, {})
    assert out["status"] == "SUCCESS"
    assert out["output_patch"]["search_result"] == response


def test_search_query_execute_passes_errors_through(monkeypatch):
    from apps.automation.flows import flow_definitions as fd

    monkeypatch.setattr(
        fd, "_syscall_node",
        lambda name, state, context, capability: {"status": "RETRY", "error": "boom"},
    )
    out = fd.search_query_execute({"query": "q"}, {})
    assert out["status"] == "RETRY"
    assert "search_result" not in out.get("output_patch", {})


def test_unified_search_flow_and_nodes_registered():
    from apps.automation.flows.flow_definitions import register_all_flows
    from AINDY.runtime.flow_engine import FLOW_REGISTRY, NODE_REGISTRY

    try:
        register_all_flows()
    except Exception:
        pass
    assert "unified_search" in FLOW_REGISTRY
    assert "search_validate" in NODE_REGISTRY
    assert "search_query_execute" in NODE_REGISTRY
