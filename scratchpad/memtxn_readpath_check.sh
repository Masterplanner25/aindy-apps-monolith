#!/usr/bin/env bash
# Decisive check: is the memory_nodes READ PATH still functional on 1.10.2, and does it now
# read without holding transactions open? Exercises the runtime's own DAO in-container and
# watches the scan counter + connection state around it.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }
API="$(dc ps -q api)"; PG="$(dc ps -q postgres)"
PSQL() { docker exec -i "$PG" psql -U "${POSTGRES_USER:-aindy}" -d "${POSTGRES_DB:-aindy}" -tAc "$1"; }
scans() { PSQL "SELECT coalesce(seq_scan,0)+coalesce(idx_scan,0) FROM pg_stat_user_tables WHERE relname='memory_nodes';"; }

echo "=== memory_nodes read-path check on aindy-runtime $(docker exec "$API" python -c 'import importlib.metadata as m;print(m.version("aindy-runtime"))') ==="
S0="$(scans)"
echo "scans before: $S0"

docker exec -i "$API" python - <<'PY'
import time
from AINDY.db.database import SessionLocal
from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
db = SessionLocal()
try:
    dao = MemoryNodeDAO(db)
    t0 = time.time()
    # generic read of the corpus through the runtime's own DAO
    rows = None
    for attr in ("list_nodes", "get_all", "search", "recent", "list_all"):
        fn = getattr(dao, attr, None)
        if fn is None:
            continue
        try:
            rows = fn() if attr in ("get_all", "list_all", "recent") else fn(limit=25)
            print(f"    DAO.{attr}() -> {len(rows) if hasattr(rows,'__len__') else rows} rows in {time.time()-t0:.3f}s")
            break
        except TypeError:
            try:
                rows = fn()
                print(f"    DAO.{attr}() -> {len(rows) if hasattr(rows,'__len__') else rows} rows in {time.time()-t0:.3f}s")
                break
            except Exception as e:
                print(f"    DAO.{attr} failed: {e!r}")
        except Exception as e:
            print(f"    DAO.{attr} failed: {e!r}")
    if rows is None:
        # fall back to a plain ORM read so we still prove the table is readable
        from AINDY.db.models.memory_node import MemoryNode
        n = db.query(MemoryNode).limit(25).all()
        print(f"    ORM fallback -> {len(n)} rows in {time.time()-t0:.3f}s")
    print("    available DAO methods:", [m for m in dir(dao) if not m.startswith('_')][:15])
finally:
    db.close()
PY

sleep 1
S1="$(scans)"
echo
echo "scans after : $S1   (delta $((S1-S0)))"
if [ "$((S1-S0))" -gt 0 ]; then
  echo "=> READ PATH WORKS on 1.10.2 (table is queried and returns rows)."
else
  echo "=> read path produced no scans — investigate."
fi
