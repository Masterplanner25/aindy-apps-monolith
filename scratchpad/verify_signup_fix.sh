#!/usr/bin/env bash
# Rebuild with the signup-init fix, register a fresh account, and confirm the state that
# SHOULD be provisioned now actually is.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
PG="$(dc ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c "$1"; }

echo "==> rebuilding api with the fix"
dc build api >/dev/null 2>&1 || { echo "build failed"; exit 1; }
dc up -d api >/dev/null 2>&1
CID="$(dc ps -q api)"
for i in $(seq 1 45); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  [ "$st" = "healthy" ] && { echo "    healthy at t+$((i*4))s"; break; }
  sleep 4
done

echo
echo "==> registering a fresh account on the fixed build"
docker exec -i "$CID" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"fix+{stamp}@local.test", f"FixPass!{stamp}"
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8000"+p,data=json.dumps(b).encode(),
                             headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return x.status
    except urllib.error.HTTPError as e: return e.code
print("    register ->", post("/auth/register", {"email":email,"password":password,"username":f"fix{stamp}"}))
print("    login    ->", post("/auth/login", {"email":email,"password":password}))
open("/tmp/fix_email.txt","w").write(email)
PY

EMAIL="$(docker exec -i "$CID" cat /tmp/fix_email.txt 2>/dev/null)"
echo "    account: $EMAIL"
sleep 2

echo
echo "==> state provisioned for that account (was ALL ZERO before the fix)"
Q "SELECT 'user_identity'  AS t, count(*) FROM user_identity  WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'user_scores',   count(*) FROM user_scores   WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'memory_nodes',  count(*) FROM memory_nodes  WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'agent_runs',    count(*) FROM agent_runs    WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL')
   UNION ALL SELECT 'system_events', count(*) FROM system_events WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL');"

echo "==> the initial memory node"
Q "SELECT content, source FROM memory_nodes
    WHERE user_id=(SELECT id FROM users WHERE email='$EMAIL') LIMIT 3;"

echo "==> signup-init log lines"
docker logs "$CID" --since 90s 2>&1 | grep -iE "signup (state|initialization)" | tail -5
