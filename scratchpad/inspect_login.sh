#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"insp+{stamp}@local.test", f"InspPass!{stamp}"
def post(path, payload):
    req = urllib.request.Request("http://127.0.0.1:8000"+path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
s,b = post("/auth/register", {"email":email,"password":password,"username":f"insp{stamp}"})
print("REGISTER", s, b[:300])
s,b = post("/auth/login", {"email":email,"password":password})
print("LOGIN", s)
try:
    d = json.loads(b)
    print("LOGIN keys:", list(d.keys()))
    print(json.dumps(d, indent=2)[:700])
except Exception as e:
    print("raw:", b[:400])
PY
