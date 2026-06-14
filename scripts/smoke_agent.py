"""
Agent domain smoke test — runs against a live pip-installed aindy-runtime stack.

Prerequisites (server-side env vars):
  AINDY_AGENT_PLANNER_BACKEND=stub   # enables canned plan, no LLM required
  AINDY_ASYNC_HEAVY_EXECUTION=false  # use sync create path
  AINDY_ENABLE_BACKGROUND_TASKS=false

Usage:
  python scripts/smoke_agent.py
  python scripts/smoke_agent.py --base-url http://localhost:8000

The script registers a throw-away user, exercises the full agent lifecycle
(create -> get -> list -> approve -> events -> steps -> reject), then exits 0
if all assertions pass or 1 if any fail.
"""

import argparse
import sys
import time
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


def _extract_run_id(body: dict) -> str | None:
    """
    to_execution_response embeds run_id inside execution_record.
    Fall back to top-level run_id (present in run_to_dict responses).
    """
    er = body.get("execution_record") or {}
    return (
        er.get("run_id")
        or body.get("run_id")
        or (body.get("data", {}).get("run_id") if isinstance(body.get("data"), dict) else None)
    )


def _status_from(body: dict) -> str:
    # to_execution_response uppercases; run_to_dict lowercases
    return str(body.get("status") or "").lower()


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


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    data, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={data.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-agent-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    data, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    data, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = data.get("access_token") or (data.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {data}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_tools(session, base, results):
    data, ok = _get(session, base, "/apps/agent/tools", "list tools")
    if not ok:
        results["tools"] = "FAIL"
        return

    tools = data.get("data") or data if isinstance(data, list) else []
    count = len(tools) if isinstance(tools, list) else "?"
    _ok("list tools", f"{count} tools registered")
    results["tools"] = "PASS"


def step_create(session, base, results):
    goal = "Smoke test: recall my most recent strategic priorities."
    data, ok = _post(
        session, base,
        "/apps/agent/run",
        {"goal": goal},
        "create agent run",
        expect=(200, 201, 202),
    )
    if not ok:
        results["create"] = "FAIL"
        return None

    status = _status_from(data)
    run_id = _extract_run_id(data)

    if not run_id:
        _fail("create agent run", f"no run_id in response: {list(data.keys())}")
        results["create"] = "FAIL"
        return None

    if status not in ("pending_approval", "approved", "executing", "completed", "failed"):
        _fail("create agent run", f"unexpected status={status!r}")
        results["create"] = "FAIL"
        return None

    _ok("create agent run", f"run_id={run_id}  status={status}")
    results["create"] = "PASS"
    return run_id


def step_get(session, base, run_id, results):
    data, ok = _get(session, base, f"/apps/agent/runs/{run_id}", "get run by id")
    if not ok:
        results["get_run"] = "FAIL"
        return False

    got_id = data.get("run_id") or _extract_run_id(data)
    status = _status_from(data)
    if not got_id:
        _fail("get run by id", f"no run_id in: {list(data.keys())}")
        results["get_run"] = "FAIL"
        return False

    _ok("get run by id", f"run_id={got_id}  status={status}")
    results["get_run"] = "PASS"
    return True


def step_list(session, base, run_id, results):
    data, ok = _get(session, base, "/apps/agent/runs", "list runs")
    if not ok:
        results["list_runs"] = "FAIL"
        return

    items = data.get("data") or (data if isinstance(data, list) else [])
    found = any(
        str(item.get("run_id") or _extract_run_id(item) or "") == run_id
        for item in items
        if isinstance(item, dict)
    )
    if not found:
        _fail("list runs", f"run_id {run_id} not found in {len(items)} runs")
        results["list_runs"] = "FAIL"
        return

    _ok("list runs", f"{len(items)} run(s), target run present")
    results["list_runs"] = "PASS"


def step_approve(session, base, run_id, results):
    data, ok = _post(
        session, base,
        f"/apps/agent/runs/{run_id}/approve",
        {},
        "approve run",
        expect=(200, 201, 202),
    )
    if not ok:
        results["approve"] = "FAIL"
        return False

    status = _status_from(data)
    # Acceptable: approved (CAS won), or any later state if execution raced ahead
    accepted = {"approved", "executing", "completed", "failed"}
    if status not in accepted:
        _fail("approve run", f"unexpected post-approve status={status!r}")
        results["approve"] = "FAIL"
        return False

    _ok("approve run", f"status={status}")
    results["approve"] = "PASS"
    return True


def step_poll_status(session, base, run_id, results, attempts=5, delay=1.0):
    """
    Brief poll after approval. Execution fires in a background thread and will
    fail without real LLM/tools — we just confirm the state machine moved.
    Terminal states: completed, failed, rejected.
    """
    terminal = {"completed", "failed", "rejected"}
    status = None
    for i in range(attempts):
        data, ok = _get(session, base, f"/apps/agent/runs/{run_id}", f"poll status (attempt {i+1})")
        if not ok:
            break
        status = _status_from(data)
        if status in terminal or status == "approved":
            break
        time.sleep(delay)

    _ok("poll final status", f"status={status}")
    results["poll_status"] = "PASS"  # informational — we accept any status after approve


def step_events(session, base, run_id, results):
    data, ok = _get(session, base, f"/apps/agent/runs/{run_id}/events", "get run events")
    if not ok:
        results["events"] = "FAIL"
        return

    events = data.get("data") or data.get("events") or (data if isinstance(data, list) else [])
    approved_events = [
        e for e in events
        if isinstance(e, dict) and str(e.get("event_type") or "").upper() == "APPROVED"
    ]
    if not approved_events:
        _fail("get run events", f"no APPROVED event in {len(events)} events")
        results["events"] = "FAIL"
        return

    _ok("get run events", f"{len(events)} event(s), APPROVED event present")
    results["events"] = "PASS"


def step_steps(session, base, run_id, results):
    data, ok = _get(session, base, f"/apps/agent/runs/{run_id}/steps", "get run steps")
    if not ok:
        results["steps"] = "FAIL"
        return

    steps = data.get("data") or (data if isinstance(data, list) else [])
    _ok("get run steps", f"{len(steps)} step(s)")
    results["steps"] = "PASS"


def step_reject(session, base, results):
    """Create a second run and immediately reject it."""
    data, ok = _post(
        session, base,
        "/apps/agent/run",
        {"goal": "Smoke test reject path: summarise last week."},
        "create second run (for reject)",
        expect=(200, 201, 202),
    )
    if not ok:
        results["reject"] = "FAIL"
        return

    run_id2 = _extract_run_id(data)
    if not run_id2:
        _fail("create second run", "no run_id in response")
        results["reject"] = "FAIL"
        return

    status_after_create = _status_from(data)
    if status_after_create not in ("pending_approval", "approved", "executing", "completed", "failed"):
        _fail("create second run", f"unexpected status={status_after_create!r}")
        results["reject"] = "FAIL"
        return

    # Only reject if it's still pending
    if status_after_create == "pending_approval":
        rej_data, rej_ok = _post(
            session, base,
            f"/apps/agent/runs/{run_id2}/reject",
            {},
            "reject second run",
            expect=(200, 201, 202),
        )
        if not rej_ok:
            results["reject"] = "FAIL"
            return

        rej_status = _status_from(rej_data)
        if rej_status not in ("rejected", "failed"):
            _fail("reject second run", f"unexpected status={rej_status!r}")
            results["reject"] = "FAIL"
            return
        _ok("reject run", f"run_id={run_id2}  status={rej_status}")
    else:
        _ok("reject run", f"run already in {status_after_create!r}, skip reject (SKIP)")

    results["reject"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agent domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("AGENT SMOKE TEST")
    print(f"Target: {base}")
    print("Requires: AINDY_AGENT_PLANNER_BACKEND=stub on server")
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

    print("\n[3] Tools")
    step_tools(session, base, results)

    print("\n[4] Create agent run")
    run_id = step_create(session, base, results)
    if not run_id:
        print("\nCreate failed — cannot continue lifecycle tests.")
        _print_summary(results)
        sys.exit(1)

    print("\n[5] Get run by ID")
    step_get(session, base, run_id, results)

    print("\n[6] List runs")
    step_list(session, base, run_id, results)

    print("\n[7] Approve run")
    approved = step_approve(session, base, run_id, results)

    if approved:
        print("\n[8] Poll execution status")
        step_poll_status(session, base, run_id, results)

        print("\n[9] Events")
        step_events(session, base, run_id, results)

        print("\n[10] Steps")
        step_steps(session, base, run_id, results)
    else:
        for k in ("poll_status", "events", "steps"):
            results[k] = "SKIP"

    print("\n[11] Reject path")
    step_reject(session, base, results)

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
        print("ALL TESTS PASSED -- agent domain smoke OK")


if __name__ == "__main__":
    main()
