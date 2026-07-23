#!/usr/bin/env bash
# Confirm the HTTPException->500 conversion and capture the CONTRAST that proves the
# trigger is "raised outside an execution context", not "always".
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"

docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"httpexc+{stamp}@local.test", f"HttpExcPass!{stamp}"
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8000"+p,data=json.dumps(b).encode(),
                             headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x: return x.read()
    except urllib.error.HTTPError as e: return e.read()
post("/auth/register", {"email":email,"password":password,"username":f"he{stamp}"})
tok = json.loads(post("/auth/login", {"email":email,"password":password})).get("access_token","")

cases = [
    ("AFFECTED?  /apps/memory/traces/<valid-uuid, absent>", "/apps/memory/traces/00000000-0000-0000-0000-000000000000", 404),
    ("AFFECTED?  /apps/masterplans/1",                      "/apps/masterplans/1", 404),
    ("CONTRAST   /apps/agent/runs/1 (in pipeline)",         "/apps/agent/runs/1", 400),
    ("CONTRAST   /apps/freelance/metrics/latest",           "/apps/freelance/metrics/latest", 404),
]
for label, path, expect in cases:
    req = urllib.request.Request("http://127.0.0.1:8000"+path,
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            got = r.status
    except urllib.error.HTTPError as e:
        got = e.code
    flag = "  <== 500 MASKS THE REAL CODE" if got >= 500 else ""
    print(f"  {label:<52} expect~{expect}  got {got}{flag}")
PY

echo
echo "########## masterplans traceback ##########"
docker logs "$API" --since 40s 2>&1 | grep -B3 -A6 "masterplan" | grep -E "HTTPException|RouteExecutionViolation|masterplan_router|raise |line [0-9]+, in" | head -12
