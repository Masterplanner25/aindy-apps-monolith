"""
Automation domain smoke test.

Adapter: raw_json_adapter (prefix "automation")
  body = handler return value (no canonical wrapper)

Routes tested:
  GET /apps/automation/logs           — list logs; empty for fresh user
  GET /apps/automation/scheduler/status — direct handler (no flow); scheduler state
  GET /apps/automation/logs/{id}      — 404 for nonexistent log

Routes skipped:
  POST /apps/automation/tasks/{id}/trigger — needs a real task in DB
  POST /apps/automation/logs/{id}/replay   — needs a log in failed/retrying status

Response shapes:
  GET /logs        body = {"logs": [], "count": 0, "filters": {...}, "execution_envelope": {...}}
  GET /scheduler   body = {"running": bool, "jobs": [...], "job_count": int}
  GET /logs/{id}   → 404 when log not found

Usage:
  python scripts/smoke_automation.py
  python scripts/smoke_automation.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

BASE = "/apps/automation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _get(session, base, path, label, expect=(200,)):
    r = session.get(f"{base}{path}")
    if r.status_code not in expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
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
    email = f"smoke-auto-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    r = session.post(f"{base}/auth/register", json={"email": email, "password": pw})
    if r.status_code not in (200, 201):
        _fail("register", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None

    r = session.post(f"{base}/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        _fail("login", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None

    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_list_logs(session, base, results):
    """GET /apps/automation/logs — flow-backed; body has logs/count/filters keys."""
    body, ok = _get(session, base, f"{BASE}/logs", "list automation logs")
    if not ok:
        results["list_logs"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("list automation logs", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["list_logs"] = "FAIL"
        return

    logs = body.get("logs")
    count = body.get("count")

    if logs is None:
        _fail("list automation logs", f"no 'logs' key in body: {list(body.keys())}")
        results["list_logs"] = "FAIL"
        return

    if not isinstance(logs, list):
        _fail("list automation logs", f"'logs' is {type(logs).__name__}, expected list")
        results["list_logs"] = "FAIL"
        return

    _ok("list automation logs", f"count={count}  logs={len(logs)}  (empty OK for fresh user)")
    results["list_logs"] = "PASS"


def step_scheduler_status(session, base, results):
    """GET /apps/automation/scheduler/status — direct handler (no flow); scheduler state."""
    body, ok = _get(session, base, f"{BASE}/scheduler/status", "scheduler status")
    if not ok:
        results["scheduler_status"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("scheduler status", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["scheduler_status"] = "FAIL"
        return

    running = body.get("running")
    job_count = body.get("job_count")

    if running is None:
        _fail("scheduler status", f"no 'running' key in body: {list(body.keys())}")
        results["scheduler_status"] = "FAIL"
        return

    jobs = body.get("jobs") or []
    _ok("scheduler status", f"running={running}  job_count={job_count}  jobs_in_list={len(jobs)}")
    results["scheduler_status"] = "PASS"


def step_get_log_not_found(session, base, results):
    """GET /apps/automation/logs/{id} — nonexistent ID → expect 404."""
    fake_id = str(uuid.uuid4())
    body, ok = _get(session, base, f"{BASE}/logs/{fake_id}", "get nonexistent log", expect=(404,))
    if not ok:
        results["get_log_404"] = "FAIL"
        return

    _ok("get nonexistent log", f"404 as expected for id={fake_id[:8]}...")
    results["get_log_404"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Automation domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("AUTOMATION DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Skipping: POST /tasks/{id}/trigger (needs real task), POST /logs/{id}/replay (needs failed log)")
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

    print("\n[3] List automation logs (GET /apps/automation/logs)")
    step_list_logs(session, base, results)

    print("\n[4] Scheduler status (GET /apps/automation/scheduler/status)")
    step_scheduler_status(session, base, results)

    print("\n[5] Get nonexistent log (GET /apps/automation/logs/{id} -> 404)")
    step_get_log_not_found(session, base, results)

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
        print("ALL TESTS PASSED -- automation domain smoke OK")


if __name__ == "__main__":
    main()
