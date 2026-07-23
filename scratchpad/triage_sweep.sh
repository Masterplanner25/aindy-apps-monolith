#!/usr/bin/env bash
# Triage the sweep findings:
#  1. confirm the 25 /apps/* 401s are correct API-key gating on deprecated legacy routes
#  2. pull tracebacks for the two genuine 500s
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"

echo "########## 1. legacy routes with the API key (expect 200 => 401 was correct gating) ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, os, urllib.request, urllib.error
key = os.getenv("AINDY_API_KEY", "")
print(f"  AINDY_API_KEY present: {'yes' if key else 'NO'}")
for path in ("/apps/top_drop_points", "/apps/causal_graph", "/apps/playbooks"):
    for label, hdrs in (("no key", {}), ("with key", {"X-API-Key": key})):
        req = urllib.request.Request("http://127.0.0.1:8000"+path, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()[:80]
                dep = r.headers.get("Deprecation") or r.headers.get("X-Deprecated") or "-"
                print(f"    {path:<28} {label:<9} -> {r.status}  deprecation-hdr={dep}")
        except urllib.error.HTTPError as e:
            print(f"    {path:<28} {label:<9} -> {e.code}")
        except Exception as e:
            print(f"    {path:<28} {label:<9} -> ERR {e!r}")
PY

echo
echo "########## 2. reproduce the two genuine 500s ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"triage+{stamp}@local.test", f"TriagePass!{stamp}"
def post(p, b):
    r = urllib.request.Request("http://127.0.0.1:8000"+p, data=json.dumps(b).encode(),
                               headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as x: return x.read()
    except urllib.error.HTTPError as e: return e.read()
post("/auth/register", {"email":email,"password":password,"username":f"tri{stamp}"})
tok = json.loads(post("/auth/login", {"email":email,"password":password})).get("access_token","")
for path in ("/apps/masterplans/1",
             "/apps/memory/traces/00000000-0000-0000-0000-000000000000",
             "/apps/memory/traces/not-a-uuid"):
    req = urllib.request.Request("http://127.0.0.1:8000"+path,
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"    {path:<58} -> {r.status}")
    except urllib.error.HTTPError as e:
        print(f"    {path:<58} -> {e.code} {e.read()[:100]}")
PY

echo
echo "########## 3. traceback from api logs ##########"
docker logs "$API" --since 60s 2>&1 | grep -A 18 "Traceback" | tail -50
