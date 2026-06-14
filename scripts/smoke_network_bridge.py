"""
Network Bridge domain smoke test.

Routes at /apps/network_bridge/*
Adapter: raw_json_adapter (prefix "network_bridge")
Auth: ALL routes require X-API-Key header (verify_api_key dependency at router level)
      AINDY_API_KEY is empty in the test environment -> 503 on all routes.

This script verifies:
  1. Server is healthy
  2. All network_bridge routes correctly reject unauthenticated requests (503)
  3. With a valid API key, routes work as expected (skipped -- key not configured)

Routes:
  POST /apps/network_bridge/connect      -- register external author (needs API key)
  POST /apps/network_bridge/user_event   -- log user event (needs API key)
  GET  /apps/network_bridge/authors      -- list authors (needs API key)

Usage:
  python scripts/smoke_network_bridge.py
  python scripts/smoke_network_bridge.py --base-url http://localhost:8000
  python scripts/smoke_network_bridge.py --api-key <key>  # if AINDY_API_KEY is set
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

BASE = "/apps/network_bridge"


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


def step_auth_required(session, base, results):
    """All network_bridge routes need X-API-Key. Without it -> 503 (key not configured)."""
    r = session.get(f"{base}{BASE}/authors")
    if r.status_code == 503:
        _ok("auth required (no key)", f"503 -- AINDY_API_KEY not configured, as expected")
        results["auth_required"] = "PASS"
    elif r.status_code == 401:
        _ok("auth required (no key)", "401 -- API key required, as expected")
        results["auth_required"] = "PASS"
    elif r.status_code == 422:
        _ok("auth required (no key)", "422 -- API key header required, as expected")
        results["auth_required"] = "PASS"
    else:
        _fail("auth required (no key)", f"expected 401/422/503, got {r.status_code}: {r.text[:200]}")
        results["auth_required"] = "FAIL"


def step_connect(session, base, results):
    """POST /apps/network_bridge/connect -- register external author."""
    payload = {
        "author_name": f"Smoke Test Node {uuid.uuid4().hex[:6]}",
        "platform": "SmokeTestPlatform",
        "connection_type": "BridgeHandshake",
        "notes": "Automated smoke test connection",
    }
    body, ok = _post(session, base, f"{BASE}/connect", payload, "connect external author")
    if not ok:
        results["connect"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("connect external author", f"expected dict, got {type(body).__name__}")
        results["connect"] = "FAIL"
        return

    _ok("connect external author", f"keys={list(body.keys())}")
    results["connect"] = "PASS"


def step_user_event(session, base, results):
    """POST /apps/network_bridge/user_event -- log a user event."""
    payload = {
        "name": "Smoke Test User",
        "tagline": "Automated smoke test",
        "platform": "InfiniteNetwork",
        "action": "create_profile",
    }
    body, ok = _post(session, base, f"{BASE}/user_event", payload, "log user event")
    if not ok:
        results["user_event"] = "FAIL"
        return

    status_val = body.get("status") if isinstance(body, dict) else None
    _ok("log user event", f"status={status_val!r}  keys={list(body.keys()) if isinstance(body, dict) else type(body).__name__}")
    results["user_event"] = "PASS"


def step_list_authors(session, base, results):
    """GET /apps/network_bridge/authors -- list registered external authors."""
    body, ok = _get(session, base, f"{BASE}/authors", "list authors")
    if not ok:
        results["list_authors"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("list authors", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["list_authors"] = "FAIL"
        return

    authors = body.get("authors") or body.get("data", {}).get("authors") if isinstance(body.get("data"), dict) else None
    count = len(authors) if isinstance(authors, list) else "?"
    _ok("list authors", f"count={count}  keys={list(body.keys())}")
    results["list_authors"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Network Bridge domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    parser.add_argument("--api-key", default=None, help="X-API-Key value (AINDY_API_KEY)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("NETWORK BRIDGE DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    if args.api_key:
        print(f"API key: provided ({args.api_key[:4]}...)")
    else:
        print("API key: NOT provided -- routes will return 503 (AINDY_API_KEY not set in env)")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    if args.api_key:
        session.headers["X-API-Key"] = args.api_key
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    if not args.api_key:
        print("\n[2] Auth gate -- all routes need X-API-Key")
        step_auth_required(session, base, results)
        print("\nNote: set AINDY_API_KEY env var and pass --api-key to test authenticated routes.")
        _print_summary(results)
        failed = [k for k, v in results.items() if v == "FAIL"]
        sys.exit(1 if failed else 0)

    # API key provided -- run full suite
    print("\n[2] Connect external author (POST /apps/network_bridge/connect)")
    step_connect(session, base, results)

    print("\n[3] Log user event (POST /apps/network_bridge/user_event)")
    step_user_event(session, base, results)

    print("\n[4] List authors (GET /apps/network_bridge/authors)")
    step_list_authors(session, base, results)

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
        print("ALL TESTS PASSED -- network_bridge domain smoke OK")


if __name__ == "__main__":
    main()
