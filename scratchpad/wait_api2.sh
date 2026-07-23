#!/usr/bin/env bash
for i in $(seq 1 30); do
  st=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null || echo '?')
  echo "t+$((i*4))s health=$st"
  [ "$st" = "healthy" ] && break
  sleep 4
done
docker exec aindy-apps-monolith-api-1 python -c "import os;print('MONGO_URL in api =', repr(os.getenv('MONGO_URL')))"
