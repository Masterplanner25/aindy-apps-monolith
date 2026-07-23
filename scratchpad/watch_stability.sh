#!/usr/bin/env bash
# Watch the api container for ~90s: is its Started timestamp stable, or does it keep recreating?
for i in $(seq 1 9); do
  started=$(docker inspect --format '{{.State.StartedAt}}' aindy-apps-monolith-api-1 2>/dev/null)
  health=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null)
  rc=$(docker inspect --format '{{.RestartCount}}' aindy-apps-monolith-api-1 2>/dev/null)
  echo "t+$((i*10))s  started=$started  health=$health  restarts=$rc"
  sleep 10
done
