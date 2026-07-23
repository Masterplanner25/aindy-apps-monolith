#!/usr/bin/env bash
# Dump the EXACT payloads the dashboard receives for a provisioned account with history,
# so the render can be reproduced against real data instead of a guessed fixture.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"dd+{stamp}@local.test", f"DdPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type":"application/json"}
    if tok: h["Authorization"]=f"Bearer {tok}"
    r = urllib.request.Request(BASE+p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(r,timeout=180) as x: return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"dd{stamp}"})
_,d = call("POST","/auth/login",body={"email":email,"password":password})
tok=d["access_token"]

# force score computation twice so history has >1 entry (the chart only renders then)
for _ in range(2):
    s,_r = call("POST","/apps/scores/me/recalculate", tok, {})
    print(f"  recalculate -> {s}")
    time.sleep(1)

for label, path in [("SCORE","/apps/scores/me"),
                    ("HISTORY","/apps/scores/me/history?days=14"),
                    ("OVERVIEW","/apps/dashboard/overview")]:
    s, body = call("GET", path, tok)
    print(f"\n===== {label} ({s}) =====")
    body.pop("execution_envelope", None)
    print(json.dumps(body, indent=2)[:1500])
PY
