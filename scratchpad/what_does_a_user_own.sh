#!/usr/bin/env bash
# Does a real signed-in user actually HAVE the records the UI will ask for?
# Registers a fresh account (a real signup), logs in (a real system event), then reports
# what rows exist for (a) that fresh user and (b) the existing real account.
# This tests the HAPPY path with REAL ids — the sweep only tested error paths with fake ids.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c "$1"; }

echo "########## 1. fresh signup — what does registration+login create? ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"own+{stamp}@local.test", f"OwnPass!{stamp}"
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8000"+p,data=json.dumps(b).encode(),
                             headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x: return x.status, x.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
s,_ = post("/auth/register", {"email":email,"password":password,"username":f"own{stamp}"})
s2,b = post("/auth/login", {"email":email,"password":password})
tok = json.loads(b).get("access_token","")
print(f"  register={s} login={s2}")
open("/tmp/own_email.txt","w").write(email)
open("/tmp/own_token.txt","w").write(tok)
PY

EMAIL="$(docker exec -i "$API" cat /tmp/own_email.txt 2>/dev/null)"
echo "  fresh account: $EMAIL"
echo
echo "-- rows created for that fresh user --"
Q "SELECT 'system_events'   AS t, count(*) FROM system_events   WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'user_identity',   count(*) FROM user_identity   WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'user_scores',     count(*) FROM user_scores     WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'master_plans',    count(*) FROM master_plans    WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'memory_nodes',    count(*) FROM memory_nodes    WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'memory_traces',   count(*) FROM memory_traces   WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'tasks',           count(*) FROM tasks           WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'goals',           count(*) FROM goals           WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL');"

echo "########## 2. the REAL account (kingknight845) — what will the walkthrough see? ##########"
Q "SELECT 'system_events'   AS t, count(*) FROM system_events   WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'user_identity',   count(*) FROM user_identity   WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'user_scores',     count(*) FROM user_scores     WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'master_plans',    count(*) FROM master_plans    WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'memory_nodes',    count(*) FROM memory_nodes    WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'memory_traces',   count(*) FROM memory_traces   WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'tasks',           count(*) FROM tasks           WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com')
   UNION ALL SELECT 'goals',           count(*) FROM goals           WHERE user_id=(SELECT id FROM users WHERE email='kingknight845@gmail.com');"

echo "########## 3. system_events globally — is login recorded at all? ##########"
Q "SELECT count(*) AS total_system_events FROM system_events;"
Q "SELECT event_type, count(*) FROM system_events GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
