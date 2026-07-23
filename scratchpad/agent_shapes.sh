#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"ashape+{stamp}@local.test",f"AsPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None,timeout=90):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=timeout) as x:return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read() or b"{}")
        except Exception:return e.code,{}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"as{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]

def summarize(label, r):
    rid = r.get("run_id") or (r.get("execution_record") or {}).get("run_id")
    status = r.get("status")
    plan_top = (r.get("plan") or {}).get("steps") if isinstance(r.get("plan"),dict) else None
    plan_nested = ((r.get("result") or {}).get("plan") or {}).get("steps") if isinstance(r.get("result"),dict) else None
    print(f"\n### {label}")
    print(f"    top keys        : {sorted(r.keys())}")
    print(f"    run_id (top)    : {r.get('run_id')}")
    print(f"    run_id (record) : {(r.get('execution_record') or {}).get('run_id')}")
    print(f"    status          : {status}")
    print(f"    plan at .plan.steps        : {len(plan_top) if plan_top else 'none'}")
    print(f"    plan at .result.plan.steps : {len(plan_nested) if plan_nested else 'none'}")

_,created=call("POST","/apps/agent/run",tok,{"goal":"Pick a framework."})
summarize("CREATE  POST /apps/agent/run", created)
rid=(created.get("execution_record") or {}).get("run_id")

s,got=call("GET",f"/apps/agent/runs/{rid}",tok)
summarize(f"GET     /apps/agent/runs/{{id}}  ({s})", got)

s,appr=call("POST",f"/apps/agent/runs/{rid}/approve",tok,{})
summarize(f"APPROVE /apps/agent/runs/{{id}}/approve  ({s})", appr)

s,steps=call("GET",f"/apps/agent/runs/{rid}/steps",tok)
print(f"\n### STEPS  GET /runs/{{id}}/steps ({s})")
print(f"    type={type(steps).__name__}  " + (f"count={len(steps)}" if isinstance(steps,list) else f"keys={sorted(steps.keys()) if isinstance(steps,dict) else steps}"))
PY
