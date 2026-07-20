#!/usr/bin/env bash
# RT-MEMTXN-LEAK-1 live verification on aindy-runtime 1.10.1.
#
# Registers a throwaway account, then fires a LOGIN and samples pg_stat_activity every 1s
# WHILE THE REQUEST IS IN FLIGHT. Sampling after the request completes proves nothing —
# 1.10.0 already fixed post-request draining, so the tail looks clean either way.
#
# Validity guard: a fast login with ZERO memory_nodes queries is NOT a pass — it may mean the
# recall never ran. We count memory_nodes queries seen during the window to tell those apart.
set -uo pipefail

REPO="/mnt/c/dev/aindy-apps-monolith"
cd "$REPO"
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"
PG="$(dc ps -q postgres)"
PSQL() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc "$1"; }

STAMP="$(date +%s)"
EMAIL="memtxn+${STAMP}@local.test"
PASSWORD="ReproPass!${STAMP}"

echo "=== RT-MEMTXN-LEAK-1 verification on $(docker exec "$API" python -c 'import importlib.metadata as m;print("aindy-runtime==" + m.version("aindy-runtime"))') ==="
echo "repro account: $EMAIL"
echo

echo "--- baseline (idle stack) ---"
PSQL "SELECT 'idle_in_txn=' || count(*) FILTER (WHERE state='idle in transaction')
          || ' on_memory=' || count(*) FILTER (WHERE state='idle in transaction' AND query ILIKE '%memory_nodes%')
          || ' total_conns=' || count(*)
      FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();"
echo

# ---- register (also a memory-touching endpoint) ----
echo "--- registering repro account ---"
docker exec -i "$API" python - "$EMAIL" "$PASSWORD" <<'PY'
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
for path, payload in (("/auth/register", {"email": email, "password": password, "username": email.split("@")[0]}),):
    body = json.dumps(payload).encode()
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            print(f"    {path} -> {r.status} in {time.time()-t0:.1f}s")
    except urllib.error.HTTPError as e:
        print(f"    {path} -> {e.code} in {time.time()-t0:.1f}s :: {e.read()[:200]!r}")
    except Exception as e:
        print(f"    {path} -> ERROR after {time.time()-t0:.1f}s :: {e!r}")
PY
echo

# ---- login under observation ----
echo "--- firing LOGIN, sampling every 1s while in flight ---"
docker exec -i "$API" python - "$EMAIL" "$PASSWORD" > /tmp/login_out.txt 2>&1 <<'PY' &
import json, sys, time, urllib.request, urllib.error
email, password = sys.argv[1], sys.argv[2]
body = json.dumps({"email": email, "password": password}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/auth/login", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print(f"LOGIN status={r.status} elapsed={time.time()-t0:.1f}s")
except urllib.error.HTTPError as e:
    print(f"LOGIN status={e.code} elapsed={time.time()-t0:.1f}s body={e.read()[:200]!r}")
except Exception as e:
    print(f"LOGIN ERROR after {time.time()-t0:.1f}s: {e!r}")
PY
LOGIN_PID=$!

PEAK_IDLE=0; PEAK_MEM=0; SAW_MEMQ=0
T0=$(date +%s)
for i in $(seq 1 90); do
  ROW="$(PSQL "SELECT count(*) FILTER (WHERE state='idle in transaction')
                    || ' ' || count(*) FILTER (WHERE state='idle in transaction' AND query ILIKE '%memory_nodes%')
                    || ' ' || count(*) FILTER (WHERE query ILIKE '%memory_nodes%')
                    || ' ' || count(*)
                    || ' ' || coalesce(round(max(EXTRACT(epoch FROM (now()-xact_start)))::numeric,1),0)
               FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();" 2>/dev/null)"
  set -- $ROW
  IDLE="${1:-0}"; MEM="${2:-0}"; ANYMEM="${3:-0}"; TOT="${4:-0}"; OLD="${5:-0}"
  [ "${IDLE:-0}" -gt "$PEAK_IDLE" ] 2>/dev/null && PEAK_IDLE=$IDLE
  [ "${MEM:-0}" -gt "$PEAK_MEM" ] 2>/dev/null && PEAK_MEM=$MEM
  [ "${ANYMEM:-0}" -gt 0 ] 2>/dev/null && SAW_MEMQ=1
  printf "  t+%02ds  idle_in_txn=%-3s on_memory=%-3s any_memory_q=%-3s total=%-3s oldest_xact=%ss\n" \
         "$(( $(date +%s) - T0 ))" "$IDLE" "$MEM" "$ANYMEM" "$TOT" "$OLD"
  kill -0 $LOGIN_PID 2>/dev/null || break
  sleep 1
done

wait $LOGIN_PID 2>/dev/null
echo
echo "--- result ---"
cat /tmp/login_out.txt
ELAPSED=$(( $(date +%s) - T0 ))
echo "  peak idle_in_transaction         : $PEAK_IDLE"
echo "  peak idle_in_txn ON memory_nodes : $PEAK_MEM"
echo "  memory_nodes query observed      : $([ $SAW_MEMQ -eq 1 ] && echo yes || echo 'NO  <-- validity warning')"
echo
echo "--- full fingerprint table (xact_age_s vs idle_s) ---"
docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -c \
"SELECT count(*) AS count, state, wait_event_type,
        round(EXTRACT(epoch FROM (now()-xact_start))::numeric,1)   AS xact_age_s,
        round(EXTRACT(epoch FROM (now()-state_change))::numeric,1) AS idle_s,
        left(regexp_replace(query,'\s+',' ','g'),50) AS query
   FROM pg_stat_activity
  WHERE datname=current_database() AND pid<>pg_backend_pid()
  GROUP BY state,wait_event_type,xact_age_s,idle_s,query
  ORDER BY xact_age_s DESC NULLS LAST LIMIT 15;"
