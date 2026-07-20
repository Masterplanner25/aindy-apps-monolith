#!/usr/bin/env bash
# Rebuild the api image from scratch so it installs the REAL aindy-runtime 1.10.2 wheel,
# replacing the runtime team's hot-patched files. --no-cache is required: a plain
# --force-recreate would revert to the 1.10.1 image and reintroduce the bug.
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml "$@"; }

echo "==> version BEFORE rebuild (hot-patched copy)"
docker exec "$(dc ps -q api)" python -c 'import importlib.metadata as m; print("    aindy-runtime==" + m.version("aindy-runtime"))' 2>/dev/null || echo "    (api not running)"

echo "==> build --no-cache api"
dc build --no-cache --pull api || exit 1

echo "==> up -d api"
dc up -d api || exit 1

echo "==> waiting for health"
CID="$(dc ps -q api)"
for i in $(seq 1 60); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  echo "    t+$((i*4))s health=$st"
  [ "$st" = "healthy" ] && break
  sleep 4
done

echo "==> version AFTER rebuild (real wheel)"
docker exec "$CID" python -c 'import importlib.metadata as m; print("    aindy-runtime==" + m.version("aindy-runtime"))'
