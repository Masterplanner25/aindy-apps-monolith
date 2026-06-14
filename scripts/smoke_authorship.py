"""
Authorship domain smoke test.

One route: POST /apps/authorship/reclaim
  Parameters: query params (content, author, motto)
  Pipeline: raw_json_adapter (prefix "authorship") + _with_execution_envelope
  Body: {"reclaimed_text": str, "fingerprints_detected": list,
         "originator": str, "motto": str, "execution_envelope": {...}}

epistemic_reclaim is pure Python (regex + hash + unicode watermark) — no LLM, no DB.

Usage:
  python scripts/smoke_authorship.py
  python scripts/smoke_authorship.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

BASE = "/apps/authorship"


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


def _post(session, base, path, label, params=None, json=None, expect=(200, 201)):
    r = session.post(f"{base}{path}", params=params or {}, json=json)
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
    email = f"smoke-au-{uuid.uuid4().hex[:8]}@aindy.local"
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


def step_reclaim(session, base, results):
    """POST /apps/authorship/reclaim?content=...&author=...&motto=...
    Returns pure-Python watermarked text — no LLM needed."""
    sample = (
        "This is a smoke test of the Epistemic Reclaimer. "
        "It should detect any AI fingerprints and return a reclaimed version "
        "with a visible signature and invisible unicode watermark."
    )
    body, ok = _post(
        session, base, f"{BASE}/reclaim",
        "reclaim authorship",
        params={
            "content": sample,
            "author": "Knight, Shawn",
            "motto": "Quicker, Better, Smarter, Faster",
        },
    )
    if not ok:
        results["reclaim"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("reclaim authorship", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["reclaim"] = "FAIL"
        return

    reclaimed = body.get("reclaimed_text")
    fingerprints = body.get("fingerprints_detected")
    originator = body.get("originator")

    if reclaimed is None:
        _fail("reclaim authorship", f"no 'reclaimed_text' in body: {list(body.keys())}")
        results["reclaim"] = "FAIL"
        return

    if not isinstance(fingerprints, list):
        _fail("reclaim authorship", f"'fingerprints_detected' is {type(fingerprints).__name__}, expected list")
        results["reclaim"] = "FAIL"
        return

    _ok(
        "reclaim authorship",
        f"originator={originator!r}  "
        f"fingerprints={len(fingerprints)}  "
        f"reclaimed_len={len(reclaimed)}"
    )
    results["reclaim"] = "PASS"


def step_reclaim_empty(session, base, results):
    """POST /reclaim with minimal content — edge case, should still return 200."""
    body, ok = _post(
        session, base, f"{BASE}/reclaim",
        "reclaim authorship (empty content)",
        params={"content": "hello"},
    )
    if not ok:
        results["reclaim_empty"] = "FAIL"
        return

    reclaimed = body.get("reclaimed_text") if isinstance(body, dict) else None
    if reclaimed is None:
        _fail("reclaim authorship (empty content)", f"no 'reclaimed_text': {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["reclaim_empty"] = "FAIL"
        return

    _ok("reclaim authorship (empty content)", f"reclaimed_len={len(reclaimed)}")
    results["reclaim_empty"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Authorship domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("AUTHORSHIP DOMAIN SMOKE TEST")
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

    print("\n[3] Reclaim authorship (POST /apps/authorship/reclaim)")
    step_reclaim(session, base, results)

    print("\n[4] Reclaim authorship — minimal content")
    step_reclaim_empty(session, base, results)

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
        print("ALL TESTS PASSED -- authorship domain smoke OK")


if __name__ == "__main__":
    main()
