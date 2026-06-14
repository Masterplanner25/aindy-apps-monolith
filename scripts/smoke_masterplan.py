"""
Masterplan domain smoke test — runs against a live pip-installed aindy-runtime stack.

Covers (no LLM required):
  masterplan  — GET /apps/masterplans/  (list, empty OK)
  goals       — create → list → state
  scores      — get → recalculate → history → submit feedback → list feedback
  genesis     — session create → get session  (LLM-free steps only)

Response shapes for this domain:
  raw_json_adapter  (masterplan, scores prefixes):
    body IS canonical.get("data") — no outer wrapper
  return_result=True (goals, genesis router pattern):
    body = raw data dict with execution_envelope injected at top level
    e.g. {"id": "...", "name": "...", "execution_envelope": {...}}

Usage:
  python scripts/smoke_masterplan.py
  python scripts/smoke_masterplan.py --base-url http://localhost:8000
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


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
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
        _fail(label, f"PUT {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-masterplan-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    _, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    body, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_masterplan_list(session, base, results):
    """GET /apps/masterplans/ — raw_json_adapter, body = {plans: [...]}."""
    body, ok = _get(session, base, "/apps/masterplans/", "masterplan list")
    if not ok:
        results["masterplan_list"] = "FAIL"
        return

    plans = body.get("plans") if isinstance(body, dict) else None
    if plans is None:
        _fail("masterplan list", f"no 'plans' key in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["masterplan_list"] = "FAIL"
        return

    _ok("masterplan list", f"{len(plans)} plan(s) (empty is OK for fresh user)")
    results["masterplan_list"] = "PASS"


def step_goal_create(session, base, goal_name, results):
    """POST /apps/goals — 201, return_result=True → body = goal dict + execution_envelope."""
    body, ok = _post(
        session, base,
        "/apps/goals",
        {
            "name": goal_name,
            "description": "Smoke test strategic goal",
            "goal_type": "strategic",
            "priority": 0.8,
        },
        "create goal",
        expect=(200, 201),
    )
    if not ok:
        results["goal_create"] = "FAIL"
        return None

    goal_id = body.get("id") if isinstance(body, dict) else None
    name = body.get("name") if isinstance(body, dict) else None
    status = body.get("status") if isinstance(body, dict) else None

    if not goal_id:
        _fail("create goal", f"no 'id' in body keys: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["goal_create"] = "FAIL"
        return None

    _ok("create goal", f"id={goal_id}  name={name!r}  status={status}")
    results["goal_create"] = "PASS"
    return goal_id


def step_goal_list(session, base, goal_name, results):
    """GET /apps/goals — return_result=True → body = {goals: [...], execution_envelope}."""
    body, ok = _get(session, base, "/apps/goals", "list goals")
    if not ok:
        results["goal_list"] = "FAIL"
        return

    goals = body.get("goals") if isinstance(body, dict) else None
    if goals is None:
        # Some flows return a flat list directly
        goals = body if isinstance(body, list) else []

    found = any(
        str(g.get("name") or "").lower() == goal_name.lower()
        for g in goals
        if isinstance(g, dict)
    )
    if not found:
        _fail("list goals", f"goal '{goal_name}' not found in {len(goals)} goal(s)")
        results["goal_list"] = "FAIL"
        return

    _ok("list goals", f"{len(goals)} goal(s), '{goal_name}' present")
    results["goal_list"] = "PASS"


def step_goal_state(session, base, results):
    """GET /apps/goals/state — return_result=True → body = {goals: [...], drift: {...}, execution_envelope}."""
    body, ok = _get(session, base, "/apps/goals/state", "goals state")
    if not ok:
        results["goal_state"] = "FAIL"
        return

    goals = body.get("goals") if isinstance(body, dict) else None
    drift = body.get("drift") if isinstance(body, dict) else None
    _ok("goals state", f"{len(goals) if isinstance(goals, list) else '?'} goal(s)  drift_present={drift is not None}")
    results["goal_state"] = "PASS"


def step_score_get(session, base, results):
    """GET /apps/scores/me — raw_json_adapter, body = score data (empty OK for fresh user)."""
    body, ok = _get(session, base, "/apps/scores/me", "get score")
    if not ok:
        results["score_get"] = "FAIL"
        return

    _ok("get score", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)} (empty OK)")
    results["score_get"] = "PASS"


def step_score_recalculate(session, base, results):
    """POST /apps/scores/me/recalculate — raw_json_adapter."""
    body, ok = _post(session, base, "/apps/scores/me/recalculate", {}, "score recalculate")
    if not ok:
        results["score_recalculate"] = "FAIL"
        return

    _ok("score recalculate", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["score_recalculate"] = "PASS"


def step_score_history(session, base, results):
    """GET /apps/scores/me/history — raw_json_adapter."""
    body, ok = _get(session, base, "/apps/scores/me/history", "score history")
    if not ok:
        results["score_history"] = "FAIL"
        return

    _ok("score history", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["score_history"] = "PASS"


def step_score_feedback_submit(session, base, results):
    """POST /apps/scores/feedback — raw_json_adapter."""
    body, ok = _post(
        session, base,
        "/apps/scores/feedback",
        {
            "source_type": "manual",
            "feedback_value": 1,
            "feedback_text": "Smoke test positive feedback",
        },
        "score feedback submit",
    )
    if not ok:
        results["score_feedback_submit"] = "FAIL"
        return

    _ok("score feedback submit", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["score_feedback_submit"] = "PASS"


def step_score_feedback_list(session, base, results):
    """GET /apps/scores/feedback — raw_json_adapter."""
    body, ok = _get(session, base, "/apps/scores/feedback", "score feedback list")
    if not ok:
        results["score_feedback_list"] = "FAIL"
        return

    _ok("score feedback list", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    results["score_feedback_list"] = "PASS"


def step_genesis_session_create(session, base, results):
    """POST /apps/genesis/session — no LLM, return_result=True → body = {session_id: N, ..., execution_envelope}."""
    body, ok = _post(session, base, "/apps/genesis/session", {}, "genesis session create")
    if not ok:
        results["genesis_session_create"] = "FAIL"
        return None

    session_id = body.get("session_id") if isinstance(body, dict) else None
    if not session_id:
        _fail("genesis session create", f"no session_id in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["genesis_session_create"] = "FAIL"
        return None

    _ok("genesis session create", f"session_id={session_id}")
    results["genesis_session_create"] = "PASS"
    return session_id


def step_genesis_session_get(session, base, session_id, results):
    """GET /apps/genesis/session/{id} — return_result=True → body = session data."""
    body, ok = _get(session, base, f"/apps/genesis/session/{session_id}", "genesis session get")
    if not ok:
        results["genesis_session_get"] = "FAIL"
        return

    got_id = body.get("session_id") if isinstance(body, dict) else None
    synthesis_ready = body.get("synthesis_ready") if isinstance(body, dict) else None
    _ok("genesis session get", f"session_id={got_id}  synthesis_ready={synthesis_ready}")
    results["genesis_session_get"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Masterplan domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    goal_name = f"smoke-goal-{uuid.uuid4().hex[:8]}"

    print("=" * 60)
    print("MASTERPLAN DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print(f"Goal name: {goal_name}")
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

    print("\n[3] Masterplan list (GET /apps/masterplans/)")
    step_masterplan_list(session, base, results)

    print("\n[4] Create goal (POST /apps/goals)")
    goal_id = step_goal_create(session, base, goal_name, results)

    print("\n[5] List goals (GET /apps/goals)")
    step_goal_list(session, base, goal_name, results)

    print("\n[6] Goals state (GET /apps/goals/state)")
    step_goal_state(session, base, results)

    print("\n[7] Get score (GET /apps/scores/me)")
    step_score_get(session, base, results)

    print("\n[8] Recalculate score (POST /apps/scores/me/recalculate)")
    step_score_recalculate(session, base, results)

    print("\n[9] Score history (GET /apps/scores/me/history)")
    step_score_history(session, base, results)

    print("\n[10] Submit score feedback (POST /apps/scores/feedback)")
    step_score_feedback_submit(session, base, results)

    print("\n[11] List score feedback (GET /apps/scores/feedback)")
    step_score_feedback_list(session, base, results)

    print("\n[12] Genesis session create (POST /apps/genesis/session)")
    genesis_session_id = step_genesis_session_create(session, base, results)

    if genesis_session_id:
        print("\n[13] Genesis session get (GET /apps/genesis/session/{id})")
        step_genesis_session_get(session, base, genesis_session_id, results)
    else:
        results["genesis_session_get"] = "SKIP"

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
        print("ALL TESTS PASSED -- masterplan domain smoke OK")


if __name__ == "__main__":
    main()
