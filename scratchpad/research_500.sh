#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"res2+{stamp}@local.test",f"Res2Pass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None,timeout=120):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=timeout) as x:return x.status,x.read()
    except urllib.error.HTTPError as e:return e.code,e.read()
    except Exception as e:return None,repr(e).encode()
call("POST","/auth/register",body={"email":email,"password":password,"username":f"r{stamp}"})
_,b=call("POST","/auth/login",body={"email":email,"password":password})
tok=json.loads(b)["access_token"]
s,r=call("POST","/apps/research/query",tok,
         {"query":"best AI agent frameworks 2024","summary":"comparison of LangChain, AutoGen, CrewAI"})
print(f"  -> {s}\n  {r[:400]}")
PY
echo
echo "########## traceback (full) ##########"
docker logs "$API" --since 60s 2>&1 | grep -B2 -A 30 "Traceback" | tail -45
