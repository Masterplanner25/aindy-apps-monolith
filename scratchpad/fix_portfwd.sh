#!/usr/bin/env bash
set -uo pipefail
echo "=== restart api container so port 8000 re-binds after the WSL relay is up ==="
docker restart aindy-apps-monolith-api-1 >/dev/null 2>&1
for i in $(seq 1 40); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  [ "$st" = "healthy" ] && { echo "  api healthy at t+$((i*4))s"; break; }
  sleep 4
done
