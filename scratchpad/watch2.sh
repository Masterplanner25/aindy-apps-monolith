#!/usr/bin/env bash
prev=""
for i in $(seq 1 12); do
  s=$(docker inspect --format '{{.State.StartedAt}}' aindy-apps-monolith-api-1 2>/dev/null)
  h=$(docker inspect --format '{{.State.Health.Status}}' aindy-apps-monolith-api-1 2>/dev/null)
  flag=""
  [ -n "$prev" ] && [ "$s" != "$prev" ] && flag="  <<< RECREATED"
  echo "t+$((i*10))s health=$h started=${s:11:8}$flag"
  prev="$s"
  sleep 10
done
