#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/dev/aindy-apps-monolith
echo "=== bring the full stack up (mongo overlay), recreate cleanly ==="
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml up -d 2>&1 | tail -6
echo "=== wait for api healthy ==="
for i in $(seq 1 40); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  [ "$st" = "healthy" ] && { echo "  healthy at t+$((i*4))s"; break; }
  sleep 4
done
