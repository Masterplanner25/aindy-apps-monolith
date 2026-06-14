"""
Dashboard domain smoke test — runs against a live pip-installed aindy-runtime stack.

Covers:
  GET /apps/dashboard/overview  — system awareness snapshot
  GET /apps/dashboard/health    — latest system health logs

Both routes use execute_with_pipeline_sync with no registered adapter
for the "dashboard" prefix → default canonical response:
  {"status": "success", "data": {...}, "trace_id": "...", ...}
Extraction: body.get("data")

Usage:
  python scripts/smoke_dashboard.py
  python scripts/smoke_dashboard.py --base-url http://localhost:8000
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
    """Extract data from default canonical pipeline response."""
    if not isinstance(body, dict):
        return {}
    return body.get("data") or {}


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
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
    email = f"smoke-dashboard-{uuid.uuid4().hex[:8]}@aindy.local"
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


def step_overview(session, base, results):
    """GET /apps/dashboard/overview — system awareness snapshot."""
    body, ok = _get(session, base, "/apps/dashboard/overview", "dashboard overview")
    if not ok:
        results["overview"] = "FAIL"
        return

    d = _data(body)
    if not isinstance(d, dict):
        _fail("dashboard overview", f"data is {type(d).__name__}, expected dict")
        results["overview"] = "FAIL"
        return

    _ok("dashboard overview", f"keys={list(d.keys())}")
    results["overview"] = "PASS"


def step_health_logs(session, base, results):
    """GET /apps/dashboard/health — system health logs."""
    body, ok = _get(session, base, "/apps/dashboard/health", "dashboard health logs")
    if not ok:
        results["health_logs"] = "FAIL"
        return

    d = _data(body)
    # health log result is typically a list or dict with a logs/entries key
    if isinstance(d, list):
        count = len(d)
    elif isinstance(d, dict):
        count = d.get("count") or len(d.get("logs") or d.get("entries") or d.get("results") or [])
    else:
        count = "?"

    _ok("dashboard health logs", f"count={count}  keys={list(d.keys()) if isinstance(d, dict) else 'list'}")
    results["health_logs"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Dashboard domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("DASHBOARD DOMAIN SMOKE TEST")
    print(f"Target: {base}")
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

    print("\n[3] Dashboard overview (GET /apps/dashboard/overview)")
    step_overview(session, base, results)

    print("\n[4] Dashboard health logs (GET /apps/dashboard/health)")
    step_health_logs(session, base, results)

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
        print("ALL TESTS PASSED -- dashboard domain smoke OK")


if __name__ == "__main__":
    main()
