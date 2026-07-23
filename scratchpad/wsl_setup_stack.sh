#!/usr/bin/env bash
# Native-Docker stack bring-up inside a WSL2 Ubuntu distro.
# Purpose: run docker-compose.prod.yml on a NATIVE Linux docker engine (not Docker
# Desktop's VM), to sidestep the Windows/Docker Postgres degradation that blocked the
# full agent-run -> completed capstone. Run this from INSIDE Ubuntu (wsl -d Ubuntu),
# after the distro's first-run user setup.
#
#   bash /mnt/c/dev/aindy-apps-monolith/scratchpad/wsl_setup_stack.sh
#
# Idempotent. Uses sudo for the docker engine install + the first run (group membership
# needs a re-login to take effect); after re-logging into Ubuntu, `docker` works w/o sudo.
set -euo pipefail

REPO="/mnt/c/dev/aindy-apps-monolith"
COMPOSE="docker-compose.prod.yml"

echo "==> [1/5] sanity: are we in a real Ubuntu WSL distro (not docker-desktop)?"
. /etc/os-release 2>/dev/null || true
echo "    distro: ${PRETTY_NAME:-unknown}"
case "${ID:-}" in
  ubuntu|debian) : ;;
  *) echo "    !! This doesn't look like Ubuntu/Debian. Run inside 'wsl -d Ubuntu'."; exit 1 ;;
esac

echo "==> [2/5] install native docker engine + compose plugin (if missing)"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  echo "    docker installed. (group 'docker' added -> re-login to use docker without sudo)"
else
  echo "    docker already present: $(docker --version)"
fi

echo "==> [3/5] ensure the docker daemon is running"
if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then
  sudo systemctl enable --now docker || true
else
  sudo service docker start || true      # WSL without systemd
fi
# wait for the daemon socket
for i in $(seq 1 20); do
  if sudo docker info >/dev/null 2>&1; then echo "    daemon up"; break; fi
  sleep 1
done

echo "==> [4/5] build + start the stack from $REPO (reads its .env there)"
cd "$REPO"
if [ ! -f .env ]; then echo "    !! no .env at $REPO — aborting"; exit 1; fi
sudo docker compose -f "$COMPOSE" --profile full up -d --build

echo "==> [5/5] wait for api health, then report"
CID="$(sudo docker compose -f "$COMPOSE" ps -q api)"
for i in $(seq 1 30); do
  st="$(sudo docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  echo "    t+$((i*4))s health=$st"
  [ "$st" = "healthy" ] && break
  sleep 4
done
echo "---- /api/version runtime block ----"
sudo docker exec "$CID" python -c "import json,urllib.request as u; d=json.load(u.urlopen('http://127.0.0.1:8000/api/version')); print(json.dumps(d.get('runtime',{}), indent=2))" 2>/dev/null \
  | grep -E "boot_profile|app_plugins_loaded|app_plugin_count" || echo "    (version probe failed — check: sudo docker compose -f $COMPOSE logs api)"
echo "==> done. Next: register a user + POST /apps/agent/run to drive a Claude-planned run to completion."
