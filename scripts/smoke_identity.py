"""
Identity domain smoke test — runs against a live pip-installed aindy-runtime stack.

Covers:
  GET  /apps/identity/boot       — boot context (memory, runs, score, flows, runtime)
  GET  /apps/identity/           — get identity profile
  PUT  /apps/identity/           — update preferences (tone, risk_tolerance)
  GET  /apps/identity/           — verify update reflected
  GET  /apps/identity/evolution  — evolution history
  GET  /apps/identity/context    — LLM prompt context string

All 5 routes use the default canonical pipeline response:
  {"status": "success", "data": {...}, "trace_id": "...", ...}
Extraction: body.get("data")

Usage:
  python scripts/smoke_identity.py
  python scripts/smoke_identity.py --base-url http://localhost:8000
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
    email = f"smoke-identity-{uuid.uuid4().hex[:8]}@aindy.local"
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


def step_boot(session, base, results):
    """GET /apps/identity/boot — rich boot context."""
    body, ok = _get(session, base, "/apps/identity/boot", "identity boot")
    if not ok:
        results["boot"] = "FAIL"
        return

    d = _data(body)
    user_id = d.get("user_id")
    memory_count = len(d.get("memory") or [])
    runs_count = len(d.get("runs") or [])
    system_state = d.get("system_state") or {}
    runtime = d.get("runtime")

    if not user_id:
        _fail("identity boot", f"no user_id in data keys: {list(d.keys())}")
        results["boot"] = "FAIL"
        return

    _ok(
        "identity boot",
        f"user_id={user_id[:8]}...  memory={memory_count}  runs={runs_count}"
        f"  score={system_state.get('score')}  runtime_present={runtime is not None}",
    )
    results["boot"] = "PASS"


def step_get_profile(session, base, results):
    """GET /apps/identity/ — identity profile."""
    body, ok = _get(session, base, "/apps/identity/", "get identity profile")
    if not ok:
        results["get_profile"] = "FAIL"
        return

    d = _data(body)
    user_id = d.get("user_id")
    communication = d.get("communication") or {}
    tone = communication.get("tone")

    if not user_id:
        _fail("get identity profile", f"no user_id in data keys: {list(d.keys())}")
        results["get_profile"] = "FAIL"
        return

    _ok("get identity profile", f"user_id={user_id[:8]}...  tone={tone!r}")
    results["get_profile"] = "PASS"
    return tone


def step_update_profile(session, base, results):
    """PUT /apps/identity/ — update tone + risk_tolerance."""
    body, ok = _put(
        session, base,
        "/apps/identity/",
        {"tone": "concise", "risk_tolerance": "moderate"},
        "update identity profile",
    )
    if not ok:
        results["update_profile"] = "FAIL"
        return False

    d = _data(body)
    changes_recorded = d.get("changes_recorded")
    profile = d.get("profile") or {}
    new_tone = (profile.get("communication") or {}).get("tone")

    _ok(
        "update identity profile",
        f"changes_recorded={changes_recorded}  new_tone={new_tone!r}",
    )
    results["update_profile"] = "PASS"
    return True


def step_verify_update(session, base, results):
    """GET /apps/identity/ again — confirm tone=concise persisted."""
    body, ok = _get(session, base, "/apps/identity/", "verify profile update")
    if not ok:
        results["verify_update"] = "FAIL"
        return

    d = _data(body)
    tone = (d.get("communication") or {}).get("tone")

    if tone != "concise":
        _fail("verify profile update", f"expected tone='concise', got {tone!r}")
        results["verify_update"] = "FAIL"
        return

    _ok("verify profile update", f"tone={tone!r} persisted correctly")
    results["verify_update"] = "PASS"


def step_evolution(session, base, results):
    """GET /apps/identity/evolution — evolution history."""
    body, ok = _get(session, base, "/apps/identity/evolution", "identity evolution")
    if not ok:
        results["evolution"] = "FAIL"
        return

    d = _data(body)
    # Evolution summary has change_count, recent_changes, or similar
    change_count = d.get("change_count") or d.get("total_changes") or len(d.get("recent_changes") or [])
    _ok("identity evolution", f"change_count={change_count}  keys={list(d.keys())}")
    results["evolution"] = "PASS"


def step_context(session, base, results):
    """GET /apps/identity/context — LLM prompt context string."""
    body, ok = _get(session, base, "/apps/identity/context", "identity context")
    if not ok:
        results["context"] = "FAIL"
        return

    d = _data(body)
    context = d.get("context")
    is_empty = d.get("is_empty")

    if "context" not in d:
        _fail("identity context", f"no 'context' key in data: {list(d.keys())}")
        results["context"] = "FAIL"
        return

    _ok(
        "identity context",
        f"is_empty={is_empty}  length={len(context) if context else 0}",
    )
    results["context"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Identity domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("IDENTITY DOMAIN SMOKE TEST")
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

    print("\n[3] Boot identity context (GET /apps/identity/boot)")
    step_boot(session, base, results)

    print("\n[4] Get identity profile (GET /apps/identity/)")
    step_get_profile(session, base, results)

    print("\n[5] Update identity preferences (PUT /apps/identity/)")
    updated = step_update_profile(session, base, results)

    if updated:
        print("\n[6] Verify update persisted (GET /apps/identity/)")
        step_verify_update(session, base, results)
    else:
        results["verify_update"] = "SKIP"

    print("\n[7] Identity evolution history (GET /apps/identity/evolution)")
    step_evolution(session, base, results)

    print("\n[8] Identity LLM context (GET /apps/identity/context)")
    step_context(session, base, results)

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
        print("ALL TESTS PASSED -- identity domain smoke OK")


if __name__ == "__main__":
    main()
