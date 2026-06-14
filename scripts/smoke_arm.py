"""
ARM (Autonomous Reasoning Module) domain smoke test.

Tests the DB-only and gracefully-degrading routes only.
Skips POST /analyze and POST /generate — both require a live LLM.

Covers:
  GET  /apps/arm/logs           — ARM session log list (empty OK for fresh user)
  GET  /apps/arm/config         — read current ARM config
  PUT  /apps/arm/config         — update a config value (temperature)
  GET  /apps/arm/config (again) — verify update persisted
  GET  /apps/arm/metrics        — Thinking KPI report (empty OK, flow degrades gracefully)
  GET  /apps/arm/config/suggest — config suggestions (empty OK, flow degrades gracefully)

All routes use raw_json_adapter (prefix "arm"):
  body IS the handler return value — no canonical wrapper
  Keys include execution_envelope at top level.

Usage:
  python scripts/smoke_arm.py
  python scripts/smoke_arm.py --base-url http://localhost:8000
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
    email = f"smoke-arm-{uuid.uuid4().hex[:8]}@aindy.local"
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


def step_logs(session, base, results):
    """GET /apps/arm/logs — raw_json_adapter, body = {analyses: [...], generations: [...], ...}."""
    body, ok = _get(session, base, "/apps/arm/logs", "arm logs")
    if not ok:
        results["logs"] = "FAIL"
        return

    analyses = body.get("analyses") if isinstance(body, dict) else None
    generations = body.get("generations") if isinstance(body, dict) else None

    if analyses is None and generations is None:
        _fail("arm logs", f"neither 'analyses' nor 'generations' key in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["logs"] = "FAIL"
        return

    _ok(
        "arm logs",
        f"analyses={len(analyses) if isinstance(analyses, list) else analyses}"
        f"  generations={len(generations) if isinstance(generations, list) else generations}"
        f"  (empty OK for fresh user)",
    )
    results["logs"] = "PASS"


def step_config_get(session, base, results):
    """GET /apps/arm/config — raw_json_adapter, body = config dict + execution_envelope."""
    body, ok = _get(session, base, "/apps/arm/config", "arm config get")
    if not ok:
        results["config_get"] = "FAIL"
        return None

    model = body.get("model") if isinstance(body, dict) else None
    temperature = body.get("temperature") if isinstance(body, dict) else None

    if model is None:
        _fail("arm config get", f"no 'model' key in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["config_get"] = "FAIL"
        return None

    _ok("arm config get", f"model={model!r}  temperature={temperature}")
    results["config_get"] = "PASS"
    return temperature


def step_config_update(session, base, results):
    """PUT /apps/arm/config — update temperature → body = {status: 'updated', config: {...}}."""
    body, ok = _put(
        session, base,
        "/apps/arm/config",
        {"updates": {"temperature": 0.3}},
        "arm config update",
    )
    if not ok:
        results["config_update"] = "FAIL"
        return False

    status = body.get("status") if isinstance(body, dict) else None
    config = body.get("config") if isinstance(body, dict) else None
    new_temp = config.get("temperature") if isinstance(config, dict) else None

    if status != "updated":
        _fail("arm config update", f"expected status='updated', got {status!r}")
        results["config_update"] = "FAIL"
        return False

    _ok("arm config update", f"status={status!r}  new temperature={new_temp}")
    results["config_update"] = "PASS"
    return True


def step_config_verify(session, base, results):
    """GET /apps/arm/config again — confirm temperature=0.3 persisted."""
    body, ok = _get(session, base, "/apps/arm/config", "arm config verify update")
    if not ok:
        results["config_verify"] = "FAIL"
        return

    temperature = body.get("temperature") if isinstance(body, dict) else None

    if temperature != 0.3:
        _fail("arm config verify update", f"expected temperature=0.3, got {temperature!r}")
        results["config_verify"] = "FAIL"
        return

    _ok("arm config verify update", f"temperature={temperature} persisted correctly")
    results["config_verify"] = "PASS"


def step_metrics(session, base, results):
    """GET /apps/arm/metrics — flow-based, degrades gracefully without LLM."""
    body, ok = _get(session, base, "/apps/arm/metrics", "arm metrics")
    if not ok:
        results["metrics"] = "FAIL"
        return

    # Accept any 200 — flow returns empty dict if no ARM sessions or LLM unavailable
    envelope = body.get("execution_envelope") if isinstance(body, dict) else None
    env_status = (envelope or {}).get("status") if isinstance(envelope, dict) else None
    _ok("arm metrics", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}  env_status={env_status}")
    results["metrics"] = "PASS"


def step_config_suggest(session, base, results):
    """GET /apps/arm/config/suggest — flow-based, degrades gracefully without LLM."""
    body, ok = _get(session, base, "/apps/arm/config/suggest", "arm config suggest")
    if not ok:
        results["config_suggest"] = "FAIL"
        return

    envelope = body.get("execution_envelope") if isinstance(body, dict) else None
    env_status = (envelope or {}).get("status") if isinstance(envelope, dict) else None
    _ok("arm config suggest", f"keys={list(body.keys()) if isinstance(body, dict) else type(body)}  env_status={env_status}")
    results["config_suggest"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ARM domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("ARM DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Skipping: POST /analyze, POST /generate (require live LLM)")
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

    print("\n[3] ARM logs (GET /apps/arm/logs)")
    step_logs(session, base, results)

    print("\n[4] ARM config read (GET /apps/arm/config)")
    step_config_get(session, base, results)

    print("\n[5] ARM config update (PUT /apps/arm/config)")
    updated = step_config_update(session, base, results)

    if updated:
        print("\n[6] ARM config verify (GET /apps/arm/config)")
        step_config_verify(session, base, results)
    else:
        results["config_verify"] = "SKIP"

    print("\n[7] ARM metrics (GET /apps/arm/metrics)")
    step_metrics(session, base, results)

    print("\n[8] ARM config suggest (GET /apps/arm/config/suggest)")
    step_config_suggest(session, base, results)

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
        print("ALL TESTS PASSED -- arm domain smoke OK")


if __name__ == "__main__":
    main()
