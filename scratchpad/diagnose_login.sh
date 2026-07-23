#!/usr/bin/env bash
# Diagnose the login failure WITHOUT changing anyone's password.
#  - what real (non-@local.test) accounts exist, and when were they created?
#  - is the stack even the same DB as yesterday (did the volume survive)?
#  - does login mechanically work right now (register a throwaway, log in)?
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
Q() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" "$@"; }

echo "########## postgres uptime — did the DB volume survive the outage? ##########"
Q -tAc "SELECT 'pg_started: ' || pg_postmaster_start_time();"
Q -tAc "SELECT 'oldest_user: ' || min(created_at)::text FROM users;"

echo
echo "########## real accounts (non-throwaway) ##########"
Q -c "SELECT email, created_at,
             (SELECT count(*) FROM system_events e WHERE e.user_id = u.id) AS events
        FROM users u
       WHERE email NOT LIKE '%@local.test'
       ORDER BY created_at;"

echo "########## does login mechanically work at all right now? ##########"
docker exec -i "$API" python - <<'PY' 2>/dev/null
import json, time, urllib.request, urllib.error
stamp = int(time.time())
email, password = f"logincheck+{stamp}@local.test", f"Pw!{stamp}"
BASE="http://127.0.0.1:8000"
def call(p, body):
    r = urllib.request.Request(BASE+p, data=json.dumps(body).encode(),
                               headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as x: return x.status
    except urllib.error.HTTPError as e: return e.code
call("/auth/register", {"email":email,"password":password,"username":f"lc{stamp}"})
print(f"    fresh register+login: register ok, login -> {call('/auth/login', {'email':email,'password':password})}")
print(f"    wrong password       -> {call('/auth/login', {'email':email,'password':'WRONG'})}   (expect 401)")
print(f"    nonexistent account  -> {call('/auth/login', {'email':'nobody@nowhere.test','password':'x'})}   (expect 401/404)")
PY
