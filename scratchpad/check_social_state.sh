#!/usr/bin/env bash
set -uo pipefail
echo "=== containers (is mongo running?) ==="
docker ps --format '{{.Names}}: {{.Status}}' | grep aindy || echo "(none)"
echo "=== api MONGO_URL ==="
docker exec aindy-apps-monolith-api-1 python -c "import os;print(repr(os.getenv('MONGO_URL')))" 2>/dev/null || echo "(api not up)"
echo "=== GET /apps/social/feed status (fresh user) ==="
docker exec -i aindy-apps-monolith-api-1 python - <<'PY' 2>/dev/null
import json,time,urllib.request,urllib.error
s=int(time.time()); BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,b=None):
    d=json.dumps(b).encode() if b is not None else None
    h={"Content-Type":"application/json"}
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(BASE+p,data=d,headers=h,method=m)
    try:
        with urllib.request.urlopen(r,timeout=30) as x:return x.status
    except urllib.error.HTTPError as e:return e.code
call("POST","/auth/register",b={"email":f"chk{s}@local.test","password":f"Chk!{s}","username":f"chk{s}"})
import urllib.request as u
r=u.Request(BASE+"/auth/login",data=json.dumps({"email":f"chk{s}@local.test","password":f"Chk!{s}"}).encode(),headers={"Content-Type":"application/json"})
tok=json.loads(u.urlopen(r,timeout=30).read())["access_token"]
print("  GET /apps/social/feed ->", call("GET","/apps/social/feed?limit=20",tok))
print("  POST /apps/social/post ->", call("POST","/apps/social/post",tok,{"author_id":"me","author_username":"me","content":"x","trust_tier_required":"observer","tags":[]}))
PY
