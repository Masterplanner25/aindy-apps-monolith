"""API surface sweep — clear the backend before the browser walkthrough.

Enumerates every route from the LIVE openapi.json, then exercises the read-only (GET) surface
with a real authenticated session. Purpose is to separate "backend is broken" from "frontend is
broken" so anything hit in the browser afterwards is provably a client-side issue.

Safety: GET only by default. Nothing mutating is called unless --include-writes is passed
(it is not, here). Routes with path params are called with a dummy id — for those a 404 is a
correct answer; only a 5xx is a defect.

Verdict buckets:
  OK      2xx                      — works
  AUTH    401/403                  — rejected (flagged: these are reachable-but-denied)
  MISSING 404                      — no such route/record (fine for dummy-id routes)
  BUG     5xx / timeout / conn err — real backend defect, the reason we sweep
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
TIMEOUT = 30


def call(method, path, token=None, body=None, clip=400):
    """clip=None returns the full body — required when the caller parses JSON, since a
    truncated body silently fails json.loads and looks like a missing field."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t0 = time.time()
    cut = (lambda b: b if clip is None else b[:clip])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, time.time() - t0, cut(r.read())
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0, cut(e.read())
    except Exception as e:
        return None, time.time() - t0, repr(e)[:400]


def main():
    stamp = int(time.time())
    email, password = f"sweep+{stamp}@local.test", f"SweepPass!{stamp}"

    call("POST", "/auth/register", body={"email": email, "password": password,
                                         "username": f"sweep{stamp}"})
    st, el, raw = call("POST", "/auth/login", body={"email": email, "password": password},
                       clip=None)
    token = ""
    try:
        token = (json.loads(raw) or {}).get("access_token", "")
    except Exception as e:
        print(f"  token parse failed: {e!r}; body starts {raw[:120]!r}")
    print(f"auth: login status={st} in {el:.2f}s  token={'yes' if token else 'NO'}")
    if not token:
        print("!! no token — sweep would only measure auth failures. aborting.")
        return 1

    st, _, raw = call("GET", "/openapi.json", token, clip=None)
    spec = json.loads(raw)
    paths = spec.get("paths", {})
    print(f"openapi: {len(paths)} paths\n")

    results = {"OK": [], "AUTH": [], "MISSING": [], "BUG": [], "OTHER": []}
    swept = 0
    for path, ops in sorted(paths.items()):
        if "get" not in ops:
            continue
        # substitute dummy path params; a 404 there is a correct answer
        concrete, dummy = path, False
        while "{" in concrete:
            s, e = concrete.index("{"), concrete.index("}")
            name = concrete[s + 1:e]
            val = "1" if ("id" in name.lower() and "uuid" not in name.lower()) else \
                  "00000000-0000-0000-0000-000000000000"
            concrete = concrete[:s] + val + concrete[e + 1:]
            dummy = True

        status, elapsed, body = call("GET", concrete, token)
        swept += 1
        entry = (path, status, round(elapsed, 2), body if isinstance(body, str) else body[:180])
        if status is None or (isinstance(status, int) and status >= 500):
            results["BUG"].append(entry)
        elif status < 300:
            results["OK"].append(entry)
        elif status in (401, 403):
            results["AUTH"].append(entry)
        elif status == 404:
            (results["MISSING"] if not dummy else results["OK"]).append(entry)
        else:
            results["OTHER"].append(entry)

    print("=" * 72)
    print(f"SWEPT {swept} GET routes")
    for k in ("OK", "AUTH", "MISSING", "OTHER", "BUG"):
        print(f"  {k:<8} {len(results[k])}")
    print("=" * 72)

    for k in ("BUG", "AUTH", "MISSING", "OTHER"):
        if not results[k]:
            continue
        print(f"\n----- {k} -----")
        for path, status, el, body in results[k]:
            print(f"  [{status}] {el}s  {path}")
            if k == "BUG":
                print(f"           {body}")
    slow = sorted([r for r in results["OK"] if r[2] > 2.0], key=lambda r: -r[2])[:10]
    if slow:
        print("\n----- SLOW (>2s, ok but worth noting) -----")
        for path, status, el, _ in slow:
            print(f"  [{status}] {el}s  {path}")
    return 0


sys.exit(main())
