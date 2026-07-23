#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"graph+{stamp}@local.test",f"GrPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None):
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=60) as x:return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read() or b"{}")
        except Exception:return e.code,{}
import urllib.request as u2
def reg(p,b):
    r=u2.Request(BASE+p,data=json.dumps(b).encode(),headers={"Content-Type":"application/json"})
    try:
        with u2.urlopen(r,timeout=60) as x:return json.loads(x.read())
    except urllib.error.HTTPError as e:return json.loads(e.read())
reg("/auth/register",{"email":email,"password":password,"username":f"g{stamp}"})
tok=reg("/auth/login",{"email":email,"password":password})["access_token"]

print("=== user token against each candidate ===")
for p in ("/apps/rippletrace/causal/graph","/apps/influence_graph","/apps/causal_graph"):
    s,d=call("GET",p,tok)
    keys=sorted(d.keys()) if isinstance(d,dict) else type(d).__name__
    print(f"  GET {p:36} -> {s}  keys={keys}")
    if s==200 and isinstance(d,dict):
        print(f"      nodes at .nodes: {'nodes' in d}  at .data.nodes: {'data' in d and isinstance(d.get('data'),dict) and 'nodes' in d['data']}")
        print(f"      sample: {json.dumps(d)[:200]}")
PY
