#!/usr/bin/env bash
# Why does POST /apps/research/query 500? Reproduce + pull the traceback.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"

echo "########## reproduce ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"res+{stamp}@local.test",f"ResPass!{stamp}"
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
# try a few likely body shapes — the client sends one of these
for body in ({"query":"best AI agent frameworks 2024"},
             {"topic":"best AI agent frameworks 2024"},
             {"q":"best AI agent frameworks 2024"}):
    s,r=call("POST","/apps/research/query",tok,body)
    print(f"  body={list(body)[0]:8} -> {s}  {r[:180]}")
PY

echo
echo "########## traceback ##########"
docker logs "$API" --since 90s 2>&1 | grep -A 25 "Traceback" | tail -40
echo
echo "########## the research route + handler ##########"
PY_ERR=$(docker logs "$API" --since 90s 2>&1 | grep -iE "research|ResearchEngine|research_engine" | tail -8)
echo "$PY_ERR"
