#!/usr/bin/env bash
# Why does an agent run get stuck "planning"? Check planner config + keys, then create a
# run and watch what state it lands in.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"

echo "########## planner config + keys in the running container ##########"
docker exec "$API" python - <<'PY'
import os
for k in ("AINDY_AGENT_PLANNER_BACKEND","AINDY_PLANNER_BACKEND","AGENT_PLANNER_BACKEND",
          "ANTHROPIC_API_KEY","OPENAI_API_KEY","DEEPSEEK_API_KEY","AINDY_CLAUDE_MODEL",
          "AINDY_AGENT_PLANNER_MODEL"):
    v = os.getenv(k)
    if v is None:
        print(f"  {k:32} = <unset>")
    else:
        show = v if not any(s in k for s in ("KEY","SECRET")) else (v[:6]+"…"+f"({len(v)} chars)" if v else "<empty>")
        print(f"  {k:32} = {show}")
PY

echo
echo "########## create a run and watch its status ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"agent+{stamp}@local.test",f"AgPass!{stamp}"
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
    except Exception as e:return None,{"err":repr(e)}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"ag{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]

t0=time.time()
s,run=call("POST","/apps/agent/run",tok,{"goal":"Evaluate three AI agent frameworks and pick one."})
print(f"  POST /apps/agent/run -> {s} in {time.time()-t0:.1f}s")
rid=run.get("run_id") or (run.get("data") or {}).get("run_id")
print(f"  run_id={rid}  keys={sorted(run.keys())}")
print(f"  status field: {run.get('status')!r}  plan present: {'plan' in json.dumps(run)}")
if rid:
    for i in range(4):
        time.sleep(2)
        s,det=call("GET",f"/apps/agent/runs/{rid}",tok)
        st=det.get("status") or (det.get("data") or {}).get("status")
        print(f"    t+{(i+1)*2}s GET run -> {s} status={st!r}")
# show a truncated run body for shape
print("\n  run body (truncated):")
print("  " + json.dumps(run)[:600])
PY
echo
echo "########## planner-related errors in logs ##########"
docker logs "$API" --since 3m 2>&1 | grep -iE "planner|anthropic|claude|plan.*fail|api.?key|401|timeout" | grep -viE "STRIPE|placeholder|health" | tail -15
