#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY'
import json, time, base64, urllib.request, urllib.error
stamp=int(time.time())
email,password=f"exp+{stamp}@local.test",f"ExpPass!{stamp}"
BASE="http://127.0.0.1:8000"
def post(p,b):
    r=urllib.request.Request(BASE+p,data=json.dumps(b).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x: return json.loads(x.read())
    except urllib.error.HTTPError as e: return json.loads(e.read())
post("/auth/register",{"email":email,"password":password,"username":f"e{stamp}"})
d=post("/auth/login",{"email":email,"password":password})
tok=d["access_token"]
p=tok.split(".")[1]; p+="="*(-len(p)%4)
claims=json.loads(base64.urlsafe_b64decode(p))
now=int(time.time()); exp=claims.get("exp"); iat=claims.get("iat")
print(f"  server now : {now}  {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now))} UTC")
print(f"  token iat  : {iat}")
print(f"  token exp  : {exp}  {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp))} UTC")
print(f"  TTL        : {exp-now} s  ({(exp-now)/3600:.2f} h)")
print(f"  claims     : {sorted(claims.keys())}")
PY
