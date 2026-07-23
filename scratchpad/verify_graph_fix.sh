#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
echo "==> rebuild api"
dc build api >/dev/null 2>&1 || { echo "build failed"; exit 1; }
dc up -d api >/dev/null 2>&1
CID="$(dc ps -q api)"
for i in $(seq 1 45); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  [ "$st" = "healthy" ] && { echo "    healthy at t+$((i*4))s"; break; }
  sleep 4
done
docker exec -i "$CID" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"gfix+{stamp}@local.test",f"GfPass!{stamp}"
BASE="http://127.0.0.1:8000"
def reg(p,b):
    r=urllib.request.Request(BASE+p,data=json.dumps(b).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x:return json.loads(x.read())
    except urllib.error.HTTPError as e:return json.loads(e.read())
def get(p,tok):
    r=urllib.request.Request(BASE+p,headers={"Authorization":f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x:return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read())
        except Exception:return e.code,{}
reg("/auth/register",{"email":email,"password":password,"username":f"g{stamp}"})
tok=reg("/auth/login",{"email":email,"password":password})["access_token"]
print("  the 3 routes GraphView now uses (all must be 200 for a user):")
for p in ("/apps/rippletrace/influence/graph","/apps/rippletrace/causal/graph"):
    s,d=get(p,tok)
    print(f"    GET {p:38} -> {s}  keys={sorted(d.keys()) if isinstance(d,dict) else d}")
print("  the OLD legacy routes GraphView no longer calls (were 401):")
for p in ("/apps/influence_graph","/apps/causal_graph"):
    s,_=get(p,tok)
    print(f"    GET {p:38} -> {s}")
PY
