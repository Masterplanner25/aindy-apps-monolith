#!/usr/bin/env bash
# Verify the resume fix against the live stack (requires api rebuilt with the flow change).
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }

echo "==> rebuilding api with the idempotent session flow"
dc build api >/dev/null 2>&1 || { echo "build failed"; exit 1; }
dc up -d api >/dev/null 2>&1
CID="$(dc ps -q api)"
for i in $(seq 1 45); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  [ "$st" = "healthy" ] && { echo "    healthy at t+$((i*4))s"; break; }
  sleep 4
done

PG="$(dc ps -q postgres)"
docker exec -i "$CID" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"gr+{stamp}@local.test", f"GrPass!{stamp}"
BASE="http://127.0.0.1:8000"
def call(m,p,tok=None,body=None):
    d = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type":"application/json"}
    if tok: h["Authorization"]=f"Bearer {tok}"
    r = urllib.request.Request(BASE+p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}
call("POST","/auth/register",body={"email":email,"password":password,"username":f"gr{stamp}"})
_,d = call("POST","/auth/login",body={"email":email,"password":password})
tok = d["access_token"]
open("/tmp/gr_email.txt","w").write(email)

_, a = call("POST","/apps/genesis/session", tok, {})
sid = a.get("session_id")
print(f"  1st POST  -> session_id={sid} resumed={a.get('resumed')}")

call("POST","/apps/genesis/message", tok,
     {"session_id": sid, "message": "I want to run an AI consulting studio in 5 years."})

_, b = call("POST","/apps/genesis/session", tok, {})
print(f"  2nd POST  -> session_id={b.get('session_id')} resumed={b.get('resumed')}  "
      f"{'RESUMED' if b.get('session_id')==sid else 'CREATED NEW (BUG)'}")
st = b.get("summarized_state") or {}
print(f"     restored vision   : {st.get('vision_summary')!r}")
print(f"     restored horizon  : {st.get('time_horizon')!r}")

_, g = call("GET", f"/apps/genesis/session/{sid}", tok)
print(f"  GET session -> status={g.get('status')} (client resume path uses this)")
PY

EMAIL="$(docker exec -i "$CID" cat /tmp/gr_email.txt 2>/dev/null)"
echo
echo "  === active sessions for that user (must be exactly 1) ==="
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT count(*) AS active_sessions FROM genesis_sessions
  WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL') AND status='active';"
