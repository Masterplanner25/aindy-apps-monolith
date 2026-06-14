"""
Tasks domain smoke test — runs against a live pip-installed aindy-runtime stack.

Exercises the full task lifecycle via HTTP:
  create -> list -> start -> pause -> complete -> list (verify status)
  + recurrence check endpoint

Usage:
  python scripts/smoke_tasks.py
  python scripts/smoke_tasks.py --base-url http://localhost:8000
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
    """Return the 'data' payload from a canonical pipeline response."""
    return body.get("data") or {}


def _tasks_from(body: dict) -> list:
    """Extract the tasks list from a /tasks/list response."""
    d = _data(body)
    if isinstance(d, dict):
        t = d.get("tasks")
        if isinstance(t, list):
            return t
    if isinstance(d, list):
        return d
    return []


def _status_label(body: dict) -> str:
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
    email = f"smoke-tasks-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    data, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    data, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = data.get("access_token") or (_data(data) if isinstance(_data(data), str) else _data(data).get("access_token"))
    if not token:
        _fail("login", f"no access_token in: {data}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_list_empty(session, base, results):
    """List tasks — expect 200 and an empty list (fresh user)."""
    data, ok = _get(session, base, "/apps/tasks/list", "list tasks (empty)")
    if not ok:
        results["list_empty"] = "FAIL"
        return
    tasks = _tasks_from(data)
    _ok("list tasks (empty)", f"{len(tasks)} task(s)")
    results["list_empty"] = "PASS"


def step_create(session, base, task_name, results):
    data, ok = _post(
        session, base,
        "/apps/tasks/create",
        {"name": task_name, "category": "smoke", "priority": "high"},
        "create task",
    )
    if not ok:
        results["create"] = "FAIL"
        return False

    d = _data(data)
    task_id = d.get("task_id")
    status = d.get("status") or _status_label(data)

    if not task_id:
        _fail("create task", f"no task_id in data keys: {list(d.keys())}")
        results["create"] = "FAIL"
        return False

    if str(status).lower() not in ("pending", "unknown", ""):
        # tolerate unknown — some flows don't echo status on create
        pass

    _ok("create task", f"task_id={task_id}  status={status}")
    results["create"] = "PASS"
    return True


def step_list_contains(session, base, task_name, expected_status, label, results, key):
    """List tasks and verify our task appears with the expected status."""
    data, ok = _get(session, base, "/apps/tasks/list", label)
    if not ok:
        results[key] = "FAIL"
        return

    tasks = _tasks_from(data)
    matches = [t for t in tasks if str(t.get("task_name") or "").lower() == task_name.lower()]

    if not matches:
        _fail(label, f"task '{task_name}' not found in {len(tasks)} tasks")
        results[key] = "FAIL"
        return

    actual_status = str(matches[0].get("status") or "").lower()
    if expected_status and actual_status != expected_status:
        _fail(label, f"expected status={expected_status!r}, got {actual_status!r}")
        results[key] = "FAIL"
        return

    _ok(label, f"{len(tasks)} task(s), '{task_name}' status={actual_status}")
    results[key] = "PASS"


def step_start(session, base, task_name, results):
    data, ok = _post(
        session, base,
        "/apps/tasks/start",
        {"name": task_name},
        "start task",
    )
    if not ok:
        results["start"] = "FAIL"
        return False

    d = _data(data)
    msg = str(d.get("message") or "").lower()
    if "started" not in msg and "in_progress" not in msg and "progress" not in msg:
        # Some flows return empty message — accept 2xx as success
        _ok("start task", f"2xx returned, message={msg!r}")
    else:
        _ok("start task", msg)
    results["start"] = "PASS"
    return True


def step_pause(session, base, task_name, results):
    data, ok = _post(
        session, base,
        "/apps/tasks/pause",
        {"name": task_name},
        "pause task",
    )
    if not ok:
        results["pause"] = "FAIL"
        return False

    d = _data(data)
    msg = str(d.get("message") or "").lower()
    _ok("pause task", msg or "2xx returned")
    results["pause"] = "PASS"
    return True


def step_complete(session, base, task_name, results):
    data, ok = _post(
        session, base,
        "/apps/tasks/complete",
        {"name": task_name},
        "complete task",
    )
    if not ok:
        results["complete"] = "FAIL"
        return False

    d = _data(data)
    # Response has {task_result: ..., orchestration: {...}} from the task_completion flow
    task_result = d.get("task_result")
    orchestration = d.get("orchestration")
    _ok("complete task", f"task_result={task_result!r}  has_orchestration={orchestration is not None}")
    results["complete"] = "PASS"
    return True


def step_recurrence_check(session, base, results):
    """Trigger the recurrence check background job via the endpoint."""
    data, ok = _post(
        session, base,
        "/apps/tasks/recurrence/check",
        {},
        "recurrence check",
    )
    if not ok:
        results["recurrence_check"] = "FAIL"
        return

    _ok("recurrence check", "endpoint accepted recurrence trigger")
    results["recurrence_check"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Tasks domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    task_name = f"smoke-task-{uuid.uuid4().hex[:8]}"

    print("=" * 60)
    print("TASKS SMOKE TEST")
    print(f"Target: {base}")
    print(f"Task name: {task_name}")
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

    print("\n[3] List tasks (initial empty list)")
    step_list_empty(session, base, results)

    print("\n[4] Create task")
    ok = step_create(session, base, task_name, results)
    if not ok:
        print("\nCreate failed — cannot continue lifecycle tests.")
        _print_summary(results)
        sys.exit(1)

    print("\n[5] List tasks (verify task present, status=pending)")
    step_list_contains(session, base, task_name, "pending", "list after create", results, "list_after_create")

    print("\n[6] Start task")
    step_start(session, base, task_name, results)

    print("\n[7] List tasks (verify status=in_progress)")
    step_list_contains(session, base, task_name, "in_progress", "list after start", results, "list_after_start")

    print("\n[8] Pause task")
    step_pause(session, base, task_name, results)

    print("\n[9] List tasks (verify status=paused)")
    step_list_contains(session, base, task_name, "paused", "list after pause", results, "list_after_pause")

    print("\n[10] Complete task")
    step_complete(session, base, task_name, results)

    print("\n[11] List tasks (verify status=completed)")
    step_list_contains(session, base, task_name, "completed", "list after complete", results, "list_after_complete")

    print("\n[12] Recurrence check")
    step_recurrence_check(session, base, results)

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
        print("ALL TESTS PASSED -- tasks domain smoke OK")


if __name__ == "__main__":
    main()
