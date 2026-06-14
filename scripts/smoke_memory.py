"""
Memory domain smoke test — runs against a live pip-installed aindy-runtime stack.

Exercises the full memory surface via HTTP — all routes mount at /apps/memory/*:
  - /apps/memory/nodes, /apps/memory/links, /apps/memory/recall  (runtime-owned)
  - /apps/memory/metrics, /apps/memory/traces                     (monolith-owned)

All memory routes use raw_json_adapter (registered by bridge bootstrap), so the
HTTP response body is the raw data payload — not the canonical {"status","data"}
wrapper used by tasks/agent routes.

Lifecycle:
  create node A -> get -> update -> tag search -> recall (tags)
  -> similarity search (graceful empty) -> create node B -> link A->B
  -> get links -> feedback -> performance
  -> metrics + dashboard
  -> create trace -> list -> get -> append node -> get trace nodes

Note: similarity search (POST /memory/nodes/search) returns empty results when
no OpenAI key is configured; this is expected and treated as PASS.

Usage:
  python scripts/smoke_memory.py
  python scripts/smoke_memory.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _data(body: dict):
    """
    Return the data payload.

    Memory routes use raw_json_adapter (registered by bridge bootstrap), so the
    response body IS the payload — not wrapped in {"status", "data", ...}.
    We accept either shape: if there is a "data" dict, return it; otherwise
    treat the whole body as the payload (raw adapter path).
    """
    if not isinstance(body, dict):
        return {}
    d = body.get("data")
    if isinstance(d, dict) and d:
        return d
    # raw_json_adapter path: body is the payload directly
    if "status" not in body and "data" not in body:
        return body
    # body has "data" key but it's empty/None — still check for raw keys
    if any(k in body for k in ("id", "content", "traces", "results", "nodes", "summary", "total_runs")):
        return body
    return d if isinstance(d, dict) else {}


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201, 202)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _put(session, base, path, body, label, expect=(200,)):
    r = session.put(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"PUT {path} -> {r.status_code}: {r.text[:200]}")
        return None, False
    return r.json(), True


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    data, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={data.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-mem-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    _, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    data, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = data.get("access_token") or _data(data).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {data}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

def step_create_node(session, base, tag, label, results, key):
    data, ok = _post(
        session, base,
        "/apps/memory/nodes",
        {"content": f"Smoke test node: {label}", "tags": [tag], "node_type": "insight", "source": "smoke_test"},
        f"create node ({label})",
        expect=(200, 201),
    )
    if not ok:
        results[key] = "FAIL"
        return None

    d = _data(data)
    node_id = d.get("id")
    if not node_id:
        _fail(f"create node ({label})", f"no id in data keys: {list(d.keys())}")
        results[key] = "FAIL"
        return None

    _ok(f"create node ({label})", f"id={node_id}")
    results[key] = "PASS"
    return node_id


def step_get_node(session, base, node_id, results):
    data, ok = _get(session, base, f"/apps/memory/nodes/{node_id}", "get node by id")
    if not ok:
        results["get_node"] = "FAIL"
        return

    d = _data(data)
    got_id = d.get("id") or d.get("node_id")
    _ok("get node by id", f"id={got_id}")
    results["get_node"] = "PASS"


def step_update_node(session, base, node_id, results):
    data, ok = _put(
        session, base,
        f"/apps/memory/nodes/{node_id}",
        {"content": "Smoke test node (updated)", "tags": ["smoke-test", "updated"]},
        "update node",
    )
    if not ok:
        results["update_node"] = "FAIL"
        return

    d = _data(data)
    _ok("update node", f"id={d.get('id') or node_id}")
    results["update_node"] = "PASS"


# ---------------------------------------------------------------------------
# Search and recall
# ---------------------------------------------------------------------------

def step_search_by_tags(session, base, tag, results):
    data, ok = _get(
        session, base,
        f"/apps/memory/nodes?tags={tag}&mode=AND&limit=10",
        "search nodes by tags",
    )
    if not ok:
        results["search_by_tags"] = "FAIL"
        return

    d = _data(data)
    nodes = d.get("nodes") or d.get("results") or (data.get("data") if isinstance(data.get("data"), list) else [])
    _ok("search nodes by tags", f"{len(nodes)} node(s) matched tag={tag!r}")
    results["search_by_tags"] = "PASS"


def step_recall_by_tags(session, base, tag, results):
    data, ok = _post(
        session, base,
        "/apps/memory/recall",
        {"tags": [tag], "limit": 5},
        "recall by tags",
    )
    if not ok:
        results["recall_tags"] = "FAIL"
        return

    d = _data(data)
    count = d.get("count", 0)
    _ok("recall by tags", f"{count} result(s)")
    results["recall_tags"] = "PASS"


def step_similarity_search(session, base, results):
    """Similarity search — expects empty results without OpenAI key (graceful)."""
    data, ok = _post(
        session, base,
        "/apps/memory/nodes/search",
        {"query": "strategic priorities smoke test", "limit": 3},
        "similarity search (expect graceful empty)",
    )
    if not ok:
        results["similarity_search"] = "FAIL"
        return

    d = _data(data)
    count = d.get("count", 0)
    _ok("similarity search", f"{count} result(s) (0 expected without embeddings)")
    results["similarity_search"] = "PASS"


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def step_create_link(session, base, source_id, target_id, results):
    data, ok = _post(
        session, base,
        "/apps/memory/links",
        {"source_id": source_id, "target_id": target_id, "link_type": "related", "weight": 0.8},
        "create link A->B",
        expect=(200, 201),
    )
    if not ok:
        results["create_link"] = "FAIL"
        return None

    d = _data(data)
    link_id = d.get("id")
    _ok("create link A->B", f"link_id={link_id}  source={source_id[:8]}->target={target_id[:8]}")
    results["create_link"] = "PASS"
    return link_id


def step_get_links(session, base, node_id, results):
    data, ok = _get(session, base, f"/apps/memory/nodes/{node_id}/links", "get node links")
    if not ok:
        results["get_links"] = "FAIL"
        return

    d = _data(data)
    links = d.get("links") or d.get("results") or []
    _ok("get node links", f"{len(links)} link(s)")
    results["get_links"] = "PASS"


# ---------------------------------------------------------------------------
# Feedback and performance
# ---------------------------------------------------------------------------

def step_feedback(session, base, node_id, results):
    data, ok = _post(
        session, base,
        f"/apps/memory/nodes/{node_id}/feedback",
        {"outcome": "success", "context": "smoke test validation"},
        "record node feedback",
    )
    if not ok:
        results["feedback"] = "FAIL"
        return

    _ok("record node feedback", "outcome=success")
    results["feedback"] = "PASS"


def step_performance(session, base, node_id, results):
    data, ok = _get(session, base, f"/apps/memory/nodes/{node_id}/performance", "node performance")
    if not ok:
        results["performance"] = "FAIL"
        return

    d = _data(data)
    _ok("node performance", f"keys={list(d.keys())[:4]}")
    results["performance"] = "PASS"


# ---------------------------------------------------------------------------
# Metrics (monolith app routes)
# ---------------------------------------------------------------------------

def step_metrics_summary(session, base, results):
    data, ok = _get(session, base, "/apps/memory/metrics", "metrics summary")
    if not ok:
        results["metrics_summary"] = "FAIL"
        return

    d = _data(data)
    total = d.get("total_runs", "?")
    _ok("metrics summary", f"total_runs={total}")
    results["metrics_summary"] = "PASS"


def step_metrics_dashboard(session, base, results):
    data, ok = _get(session, base, "/apps/memory/metrics/dashboard", "metrics dashboard")
    if not ok:
        results["metrics_dashboard"] = "FAIL"
        return

    d = _data(data)
    insights = d.get("insights") or []
    _ok("metrics dashboard", f"{len(insights)} insight(s)")
    results["metrics_dashboard"] = "PASS"


# ---------------------------------------------------------------------------
# Traces (monolith app routes)
# ---------------------------------------------------------------------------

def step_create_trace(session, base, results):
    data, ok = _post(
        session, base,
        "/apps/memory/traces",
        {"title": "Smoke test trace", "description": "Created by smoke_memory.py", "source": "smoke_test"},
        "create trace",
        expect=(200, 201),
    )
    if not ok:
        results["create_trace"] = "FAIL"
        return None

    d = _data(data)
    trace_id = d.get("id")
    if not trace_id:
        _fail("create trace", f"no id in data keys: {list(d.keys())}")
        results["create_trace"] = "FAIL"
        return None

    _ok("create trace", f"trace_id={trace_id}")
    results["create_trace"] = "PASS"
    return trace_id


def step_list_traces(session, base, trace_id, results):
    data, ok = _get(session, base, "/apps/memory/traces", "list traces")
    if not ok:
        results["list_traces"] = "FAIL"
        return

    d = _data(data)
    traces = d.get("traces") or []
    found = any(str(t.get("id", "")) == trace_id for t in traces if isinstance(t, dict))
    if not found:
        _fail("list traces", f"trace_id {trace_id} not found in {len(traces)} traces")
        results["list_traces"] = "FAIL"
        return

    _ok("list traces", f"{len(traces)} trace(s), target trace present")
    results["list_traces"] = "PASS"


def step_get_trace(session, base, trace_id, results):
    data, ok = _get(session, base, f"/apps/memory/traces/{trace_id}", "get trace by id")
    if not ok:
        results["get_trace"] = "FAIL"
        return

    d = _data(data)
    got_id = d.get("id")
    _ok("get trace by id", f"id={got_id}")
    results["get_trace"] = "PASS"


def step_append_node(session, base, trace_id, node_id, results):
    data, ok = _post(
        session, base,
        f"/apps/memory/traces/{trace_id}/append",
        {"node_id": node_id},
        "append node to trace",
        expect=(200, 201),
    )
    if not ok:
        results["append_to_trace"] = "FAIL"
        return False

    d = _data(data)
    _ok("append node to trace", f"node_id={node_id[:8]}... in trace {trace_id[:8]}...")
    results["append_to_trace"] = "PASS"
    return True


def step_get_trace_nodes(session, base, trace_id, node_id, results):
    data, ok = _get(session, base, f"/apps/memory/traces/{trace_id}/nodes", "get trace nodes")
    if not ok:
        results["trace_nodes"] = "FAIL"
        return

    d = _data(data)
    nodes = d.get("nodes") or []
    found = any(str(n.get("node_id", "")) == node_id for n in nodes if isinstance(n, dict))
    if not found:
        _fail("get trace nodes", f"node_id {node_id} not in {len(nodes)} trace nodes")
        results["trace_nodes"] = "FAIL"
        return

    _ok("get trace nodes", f"{len(nodes)} node(s) in trace, appended node present")
    results["trace_nodes"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Memory domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    tag = f"smoke-{uuid.uuid4().hex[:6]}"

    print("=" * 60)
    print("MEMORY SMOKE TEST")
    print(f"Target: {base}")
    print(f"Smoke tag: {tag}")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token = step_auth(session, base, results)
    if not token:
        print("\nAuth failed — cannot continue.")
        _print_summary(results)
        sys.exit(1)

    # ── Node CRUD ────────────────────────────────────────────────
    print("\n[3] Create node A")
    node_id_a = step_create_node(session, base, tag, "A", results, "create_node_a")
    if not node_id_a:
        print("\nCreate node A failed — cannot continue.")
        _print_summary(results)
        sys.exit(1)

    print("\n[4] Get node A by ID")
    step_get_node(session, base, node_id_a, results)

    print("\n[5] Update node A")
    step_update_node(session, base, node_id_a, results)

    # ── Search and recall ────────────────────────────────────────
    print("\n[6] Search nodes by tags")
    step_search_by_tags(session, base, tag, results)

    print("\n[7] Recall by tags")
    step_recall_by_tags(session, base, tag, results)

    print("\n[8] Similarity search (graceful empty without embeddings)")
    step_similarity_search(session, base, results)

    # ── Links ────────────────────────────────────────────────────
    print("\n[9] Create node B (for linking)")
    node_id_b = step_create_node(session, base, tag, "B", results, "create_node_b")

    if node_id_b:
        print("\n[10] Create link A->B")
        step_create_link(session, base, node_id_a, node_id_b, results)
    else:
        results["create_link"] = "SKIP"
        _ok("create link", "SKIP — node B creation failed")

    print("\n[11] Get links for node A")
    step_get_links(session, base, node_id_a, results)

    # ── Feedback and performance ─────────────────────────────────
    print("\n[12] Record feedback on node A")
    step_feedback(session, base, node_id_a, results)

    print("\n[13] Node A performance")
    step_performance(session, base, node_id_a, results)

    # ── Metrics ─────────────────────────────────────────────────
    print("\n[14] Metrics summary")
    step_metrics_summary(session, base, results)

    print("\n[15] Metrics dashboard")
    step_metrics_dashboard(session, base, results)

    # ── Traces ───────────────────────────────────────────────────
    print("\n[16] Create trace")
    trace_id = step_create_trace(session, base, results)

    if trace_id:
        print("\n[17] List traces (verify created trace present)")
        step_list_traces(session, base, trace_id, results)

        print("\n[18] Get trace by ID")
        step_get_trace(session, base, trace_id, results)

        print("\n[19] Append node A to trace")
        appended = step_append_node(session, base, trace_id, node_id_a, results)

        if appended:
            print("\n[20] Get trace nodes (verify node A present)")
            step_get_trace_nodes(session, base, trace_id, node_id_a, results)
        else:
            results["trace_nodes"] = "SKIP"
    else:
        for k in ("list_traces", "get_trace", "append_to_trace", "trace_nodes"):
            results[k] = "SKIP"

    _print_summary(results)

    failed = [k for k, v in results.items() if v == "FAIL"]
    sys.exit(1 if failed else 0)


def _print_summary(results):
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    icons = {"PASS": "OK", "FAIL": "FAIL", "SKIP": "--"}
    for name, result in results.items():
        icon = icons.get(result, "??")
        print(f"  {icon}  {name}: {result}")
    print()
    failed = [k for k, v in results.items() if v == "FAIL"]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("ALL TESTS PASSED -- memory domain smoke OK")


if __name__ == "__main__":
    main()
