#!/usr/bin/env bash
# Install a NATIVE Linux docker engine inside WSL2 Ubuntu (NOT Docker Desktop's VM) and
# bring the stack up on it. Docker Desktop has been stopped Windows-side; this gives Ubuntu
# its own dockerd so Postgres runs at native-Linux speed (the fix for the pool-exhaustion
# wall that blocked run->completed).
#
#   Run inside a FRESH Ubuntu shell (wsl -d Ubuntu):
#   bash /mnt/c/dev/aindy-apps-monolith/scratchpad/wsl_native_docker.sh
#
# Asks for your sudo password (the Ubuntu one). Idempotent.
set -euo pipefail
REPO="/mnt/c/dev/aindy-apps-monolith"
COMPOSE="docker-compose.prod.yml"

echo "==> [1/6] sanity"
. /etc/os-release; echo "    distro: ${PRETTY_NAME:-?}"
[ "${ID:-}" = "ubuntu" ] || { echo "    !! not Ubuntu"; exit 1; }

echo "==> [2/6] install native docker engine (Ubuntu's docker.io + compose v2)"
if ! dpkg -s docker.io >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y docker.io docker-compose-v2 || sudo apt-get install -y docker.io docker-compose
else
  echo "    docker.io already installed"
fi

echo "==> [3/6] start native dockerd (systemd) and join the docker group"
sudo systemctl enable --now docker 2>/dev/null || sudo service docker start || true
sudo usermod -aG docker "$USER" || true
for i in $(seq 1 20); do sudo docker info >/dev/null 2>&1 && break; sleep 1; done

echo "==> [4/6] VERIFY this is a native engine, not Docker Desktop"
INFO="$(sudo docker info --format '{{.Name}} | {{.OperatingSystem}}' 2>&1 || true)"
echo "    docker info: $INFO"
case "$INFO" in
  *docker-desktop*|*Docker\ Desktop*)
    echo "    !! STILL Docker Desktop's engine. Ensure Docker Desktop is fully quit on Windows,"
    echo "       run 'wsl --shutdown' from PowerShell, reopen Ubuntu, and re-run this script."
    exit 1 ;;
  *) echo "    OK — native Linux engine." ;;
esac

echo "==> [5/6] build + start the stack on the native engine"
cd "$REPO"
[ -f .env ] || { echo "    !! no .env at $REPO"; exit 1; }
sudo docker compose -f "$COMPOSE" --profile full up -d --build

echo "==> [6/6] wait for api health"
CID="$(sudo docker compose -f "$COMPOSE" ps -q api)"
for i in $(seq 1 45); do
  st="$(sudo docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo '?')"
  echo "    t+$((i*4))s health=$st"; [ "$st" = "healthy" ] && break; sleep 4
done
echo "---- /api/version ----"
sudo docker exec "$CID" python -c "import json,urllib.request as u; print(json.dumps(json.load(u.urlopen('http://127.0.0.1:8000/api/version')).get('runtime',{}),indent=2))" 2>/dev/null \
  | grep -E "boot_profile|app_plugin_count" || echo "    (probe failed)"
echo "==> NATIVE stack up. Tell Claude — it will drive the agent run to completion."
