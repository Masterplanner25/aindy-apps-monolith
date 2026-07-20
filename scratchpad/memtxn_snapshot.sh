#!/usr/bin/env bash
# Capture the RT-MEMTXN-LEAK-1 fingerprint table MID-REQUEST (the artifact the runtime team needs).
# Fires a login, waits for the fan-out to build, then snapshots pg_stat_activity while the
# request is still in flight — xact_age_s == idle_s is the signature.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"

STAMP="$(date +%s)"
EMAIL="snap+${STAMP}@local.test"; PASSWORD="SnapPass!${STAMP}"

docker exec -i "$API" python - "$EMAIL" "$PASSWORD" >/dev/null 2>&1 <<'PY'
import json, sys, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password, "username": email.split("@")[0]}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/register", data=body,
                             headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=180)
except Exception:
    pass
PY

echo "=== firing login; snapshotting mid-request ==="
docker exec -i "$API" python - "$EMAIL" "$PASSWORD" > /tmp/snap_login.txt 2>&1 <<'PY' &
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/login", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print(f"LOGIN status={r.status} elapsed={time.time()-t0:.1f}s")
except Exception as e:
    print(f"LOGIN ERROR after {time.time()-t0:.1f}s: {e!r}")
PY
LOGIN_PID=$!

sleep 18   # let the fan-out build to its plateau

echo
echo "########## MID-REQUEST pg_stat_activity (t+18s into /auth/login) ##########"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT count(*) AS count,
        state,
        wait_event_type,
        round(EXTRACT(epoch FROM (now()-xact_start))::numeric,1)   AS xact_age_s,
        round(EXTRACT(epoch FROM (now()-state_change))::numeric,1) AS idle_s,
        left(regexp_replace(query,'\s+',' ','g'),58) AS query
   FROM pg_stat_activity
  WHERE datname=current_database() AND pid<>pg_backend_pid()
  GROUP BY state,wait_event_type,xact_age_s,idle_s,query
  ORDER BY xact_age_s DESC NULLS LAST
  LIMIT 20;"

echo
echo "########## rollup: is xact_age_s == idle_s? ##########"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT state,
        count(*) AS conns,
        count(*) FILTER (WHERE abs(EXTRACT(epoch FROM (xact_start - state_change))) < 0.05) AS xact_age_eq_idle,
        round(min(EXTRACT(epoch FROM (now()-xact_start)))::numeric,1) AS min_xact_s,
        round(max(EXTRACT(epoch FROM (now()-xact_start)))::numeric,1) AS max_xact_s
   FROM pg_stat_activity
  WHERE datname=current_database() AND pid<>pg_backend_pid() AND xact_start IS NOT NULL
  GROUP BY state;"

echo
echo "########## what exactly are they running? ##########"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT left(regexp_replace(query,'\s+',' ','g'),200) AS full_query, count(*)
   FROM pg_stat_activity
  WHERE datname=current_database() AND pid<>pg_backend_pid()
    AND state='idle in transaction'
  GROUP BY 1 ORDER BY 2 DESC LIMIT 5;"

wait $LOGIN_PID 2>/dev/null
echo; cat /tmp/snap_login.txt
