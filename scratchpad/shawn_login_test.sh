#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i -e SHAWN_PW='!Q9wqdF3Sv#t*NdPx7sR' "$API" python - <<'PY'
import os, json, urllib.request, urllib.error
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d=json.dumps(body).encode() if body is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=60) as x:return x.status,x.read()
    except urllib.error.HTTPError as e:return e.code,e.read()
s,b=call("POST","/auth/login",body={"email":"shawnknight@the-master-plan.com","password":os.environ["SHAWN_PW"]})
print(f"  login shawnknight -> {s}")
if s==200:
    tok=json.loads(b)["access_token"]
    import base64
    pl=tok.split(".")[1]; pl+="="*(-len(pl)%4)
    claims=json.loads(base64.urlsafe_b64decode(pl))
    print(f"    token claims: {claims}")
    for p in ("/apps/scores/me","/apps/dashboard/overview","/identity/boot","/apps/identity/boot"):
        s2,_=call("GET",p,tok)
        print(f"    GET {p:28} -> {s2}")
else:
    print(f"    {b[:200]}")
PY
