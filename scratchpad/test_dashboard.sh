#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"dash+{stamp}@local.test", f"DashPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type":"application/json"}
    if tok: h["Authorization"]=f"Bearer {tok}"
    r = urllib.request.Request(BASE+p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return x.status, x.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except Exception as e: return None, repr(e).encode()
call("POST","/auth/register",body={"email":email,"password":password,"username":f"d{stamp}"})
_,b = call("POST","/auth/login",body={"email":email,"password":password})
tok = json.loads(b)["access_token"]
print("  (fresh account)\n")
for m,p in [("GET","/apps/dashboard/overview"),
            ("GET","/apps/scores/me"),
            ("GET","/apps/scores/me/history?days=14"),
            ("GET","/apps/scores/me/history")]:
    s,r = call(m,p,tok)
    print(f"  {m} {p:<40} -> {s}  {r[:200]}")
PY
echo
echo "=== api errors in the last minute ==="
docker logs "$API" --since 60s 2>&1 | grep -iE "error|traceback|exception" | grep -viE "STRIPE|placeholder" | tail -12
