#!/usr/bin/env bash
# What survives navigating away from Genesis and back?
#  - does POST /genesis/session resume the active session, or create a new one?
#  - does GET /genesis/session/{id} return the transcript, or only distilled state?
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"

docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"gp+{stamp}@local.test", f"GpPass!{stamp}"
BASE = "http://127.0.0.1:8000"
def call(method, path, tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(BASE+path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as x: return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}
    except Exception as e: return None, {"err": repr(e)}

call("POST","/auth/register",body={"email":email,"password":password,"username":f"gp{stamp}"})
_, d = call("POST","/auth/login",body={"email":email,"password":password})
tok = d.get("access_token","")
open("/tmp/gp_email.txt","w").write(email)

s, d1 = call("POST","/apps/genesis/session", tok, {})
sid = d1.get("session_id")
print(f"  1st POST /genesis/session -> {s}  session_id={sid}")

s, d = call("POST","/apps/genesis/message", tok,
            {"session_id": sid, "message": "I want to run an AI consulting studio in 5 years."})
print(f"  POST /genesis/message      -> {s}  reply={str(d.get('reply'))[:70]!r}")

# Simulate: user navigates away and comes back -> component mounts -> starts a session again
s, d2 = call("POST","/apps/genesis/session", tok, {})
sid2 = d2.get("session_id")
print(f"  2nd POST /genesis/session -> {s}  session_id={sid2}   {'SAME (resumes)' if sid2==sid else 'NEW SESSION (does not resume)'}")

s, d3 = call("GET", f"/apps/genesis/session/{sid}", tok)
print(f"\n  GET /genesis/session/{sid} -> {s}")
print(f"    keys returned: {sorted(d3.keys())}")
for k in ("messages","transcript","history","summarized_state","status"):
    if k in d3:
        v = json.dumps(d3[k])
        print(f"    {k}: {v[:180]}")
PY

EMAIL="$(docker exec -i "$API" cat /tmp/gp_email.txt 2>/dev/null)"
echo
echo "  === rows in genesis_sessions for that user ==="
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT id, status, synthesis_ready, (summarized_state IS NOT NULL) AS has_state
   FROM genesis_sessions WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL') ORDER BY id;"
echo "  === any column holding the transcript? ==="
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT column_name, data_type FROM information_schema.columns
  WHERE table_name='genesis_sessions' ORDER BY ordinal_position;"
