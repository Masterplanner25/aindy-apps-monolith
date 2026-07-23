#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
API="$(docker compose -f docker-compose.prod.yml ps -q api)"
docker exec -i "$API" python - <<'PY'
from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
print("DAO methods:", [m for m in dir(MemoryNodeDAO) if not m.startswith('_')])
import AINDY.db.dao.memory_node_dao as mod
import inspect
src = inspect.getsource(mod)
for line in src.splitlines():
    if "import" in line and "memory" in line.lower():
        print("IMPORT:", line.strip())
    if line.strip().startswith("def "):
        print("DEF:", line.strip()[:110])
PY
