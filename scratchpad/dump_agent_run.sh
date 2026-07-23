#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"adump+{stamp}@local.test",f"AdPass!{stamp}"
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
call("POST","/auth/register",body={"email":email,"password":password,"username":f"ad{stamp}"})
_,d=call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]
s,run=call("POST","/apps/agent/run",tok,{"goal":"Pick an agent framework."})

def find_ids(obj, path=""):
    hits=[]
    if isinstance(obj,dict):
        for k,v in obj.items():
            if any(t in k.lower() for t in ("run_id","eu_id","record_id","id")) and isinstance(v,(str,int)):
                hits.append(f"{path}.{k} = {v}")
            hits+=find_ids(v, f"{path}.{k}")
    return hits

print("=== top-level keys ===")
print(" ", sorted(run.keys()))
print("\n=== any *_id fields (candidate run identifiers) ===")
for h in find_ids(run): print("  ", h)
print("\n=== where is the plan? ===")
for path in [("result","plan"),("plan",),("result","plan","steps")]:
    cur=run
    for k in path:
        cur=cur.get(k) if isinstance(cur,dict) else None
    print(f"  run.{'.'.join(path)}: {'present' if cur is not None else 'MISSING'}"
          + (f" ({len(cur)} steps)" if isinstance(cur,list) else ""))
print("\n=== can we GET the run back by any id? ===")
for label, rid in [("execution_record.eu_id", (run.get('execution_record') or {}).get('eu_id')),
                   ("execution_envelope.eu_id", (run.get('execution_envelope') or {}).get('eu_id')),
                   ("execution_record.run_id", (run.get('execution_record') or {}).get('run_id'))]:
    if rid:
        s2,_=call("GET",f"/apps/agent/runs/{rid}",tok)
        print(f"  GET /runs/{{{label}={rid}}} -> {s2}")
PY
