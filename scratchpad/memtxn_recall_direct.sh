#!/usr/bin/env bash
# THE decisive test: call MemoryNodeDAO.recall() — the exact path that held 60 open
# transactions on 1.10.1 — and measure both that it WORKS (rows + scan delta) and that it
# no longer LEAKS (peak idle-in-transaction while it runs).
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
PSQL() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc "$1"; }
scans() { PSQL "SELECT coalesce(seq_scan,0)+coalesce(idx_scan,0) FROM pg_stat_user_tables WHERE relname='memory_nodes';"; }

echo "=== MemoryNodeDAO.recall() on aindy-runtime $(docker exec "$API" python -c 'import importlib.metadata as m;print(m.version("aindy-runtime"))') ==="
S0="$(scans)"; echo "scans before: $S0"

# sample connection state while recall runs
( for i in $(seq 1 200); do
    PSQL "SELECT count(*) FILTER (WHERE state='idle in transaction' AND query ILIKE '%memory_nodes%')
          FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();" 2>/dev/null
    sleep 0.1
  done ) > /tmp/recall_samples.txt &
SAMPLER=$!

docker exec -i "$API" python - <<'PY'
import inspect, time
from AINDY.db.database import SessionLocal
from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
db = SessionLocal()
try:
    dao = MemoryNodeDAO(db)
    print("    recall signature:", str(inspect.signature(dao.recall))[:160])
    t0 = time.time()
    try:
        rows = dao.recall(query="project status", limit=10)
    except TypeError:
        try:
            rows = dao.recall("project status")
        except TypeError as e:
            print("    could not call recall:", e); rows = None
    if rows is not None:
        n = len(rows) if hasattr(rows, "__len__") else rows
        print(f"    recall() -> {n} rows in {time.time()-t0:.3f}s")
finally:
    db.close()
PY

kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null
sleep 1
S1="$(scans)"
PEAK="$(sort -nr /tmp/recall_samples.txt 2>/dev/null | head -1)"

echo
echo "=================== VERDICT ==================="
echo "  memory_nodes scan delta      : $((S1-S0))"
echo "  peak idle_in_txn on memory   : ${PEAK:-0}   (was 60 on 1.10.1)"
if [ "$((S1-S0))" -gt 0 ] && [ "${PEAK:-0}" -lt 10 ]; then
  echo "  => FIXED AND FUNCTIONAL: recall reads the table without holding transactions open."
elif [ "$((S1-S0))" -eq 0 ]; then
  echo "  => recall did not read memory_nodes — functional concern, investigate."
else
  echo "  => still holding ${PEAK} open transactions — NOT fixed."
fi
echo "==============================================="
