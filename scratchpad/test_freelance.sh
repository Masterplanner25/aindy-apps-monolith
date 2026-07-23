#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"fl+{stamp}@local.test", f"FlPass!{stamp}"
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8000"+p,data=json.dumps(b).encode(),
                             headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return x.read()
    except urllib.error.HTTPError as e: return e.read()
post("/auth/register", {"email":email,"password":password,"username":f"fl{stamp}"})
tok = json.loads(post("/auth/login", {"email":email,"password":password})).get("access_token","")
print(f"  (fresh account, token={'ok' if tok else 'NONE'})\n")
for path in ("/apps/freelance/orders", "/apps/freelance/feedback", "/apps/freelance/metrics/latest"):
    req = urllib.request.Request("http://127.0.0.1:8000"+path,
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            print(f"  {path:<40} -> {r.status}  {body[:160]}")
    except urllib.error.HTTPError as e:
        print(f"  {path:<40} -> {e.code}  {e.read()[:200]}")
    except Exception as e:
        print(f"  {path:<40} -> ERR {e!r}")
PY
echo
echo "=== relevant api log lines ==="
docker logs "$API" --since 40s 2>&1 | grep -iE "freelance" | grep -viE "STRIPE_WEBHOOK|Bootstrap OK" | tail -8
