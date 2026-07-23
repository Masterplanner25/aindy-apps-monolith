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
echo "==> research query (was 500)"
docker exec -i "$CID" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"resfix+{stamp}@local.test",f"RfPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None,timeout=120):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=timeout) as x:return x.status,x.read()
    except urllib.error.HTTPError as e:return e.code,e.read()
call("POST","/auth/register",body={"email":email,"password":password,"username":f"r{stamp}"})
_,b=call("POST","/auth/login",body={"email":email,"password":password})
tok=json.loads(b)["access_token"]
t0=time.time()
s,r=call("POST","/apps/research/query",tok,
         {"query":"best AI agent frameworks 2024","summary":"compare LangChain, AutoGen, CrewAI"})
d=json.loads(r) if r else {}
print(f"    POST /apps/research/query -> {s} in {time.time()-t0:.1f}s")
if s==200:
    print(f"      id={d.get('id')} query={d.get('query')!r}")
    print(f"      summary={str(d.get('summary'))[:80]!r}")
    print(f"      source={d.get('source')} results={len(d.get('results') or [])}")
else:
    print(f"      {r[:200]}")
PY
