#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
dc() { docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml "$@"; }
echo "==> rebuild api"
dc build api >/dev/null 2>&1 || { echo "build failed"; exit 1; }
dc up -d api >/dev/null 2>&1
for i in $(seq 1 45); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  [ "$st" = "healthy" ] && { echo "    healthy at t+$((i*4))s"; break; }
  sleep 4
done
