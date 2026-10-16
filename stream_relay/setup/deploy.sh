#!/usr/bin/env bash
# Copy the relay to the droplet and (re)start it.
#   stream_relay/setup/deploy.sh root@<droplet address>
#
# Refuses unless it can SEE that nobody is streaming: the agent's health
# and MediaMTX's own list of publishers must both answer, and both say
# none. A server that can't tell counts as busy (Codex R10).
#   FIRST=1  the first install, when nothing is running yet
#   FORCE=1  deploy anyway (cuts every stream on this server)
set -euo pipefail
host="${1:?usage: deploy.sh root@<droplet>}"
cd "$(dirname "$0")/.."
if [ "${FORCE:-0}" != "1" ] && [ "${FIRST:-0}" != "1" ]; then
  state=$(ssh "$host" python3 - < setup/busy_check.py || echo "unknown ssh")
  case "$state" in
    idle) ;;
    busy*) echo "A church is streaming or waiting to reconnect ($state). Deploy after the service, or FORCE=1."; exit 1 ;;
    *) echo "Couldn't tell whether anyone is streaming ($state). Look at the server; FIRST=1 for a first install, FORCE=1 to deploy anyway."; exit 1 ;;
  esac
fi
tar czf - --exclude=__pycache__ docker-compose.yml mediamtx.yml .env.example agent setup \
  | ssh "$host" 'mkdir -p /opt/stream_relay && tar xzf - -C /opt/stream_relay'
ssh "$host" 'set -e
  cd /opt/stream_relay
  test -f .env || { echo "No .env on the server yet: copy .env.example to /opt/stream_relay/.env and fill it in."; exit 1; }
  chmod 600 .env
  chmod 755 setup/*.sh
  setup/tls.sh
  docker compose up -d --build
  sleep 3
  docker compose ps
  curl -s --max-time 3 http://127.0.0.1:9100/health; echo'
