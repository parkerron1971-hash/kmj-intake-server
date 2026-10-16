#!/usr/bin/env bash
# Copy the relay to the droplet and (re)start it.
#   stream_relay/setup/deploy.sh root@<droplet address>
# Refuses while a church is live: restarting the agent mid-service would
# drop the stream for every church on this server. FORCE=1 overrides.
set -euo pipefail
host="${1:?usage: deploy.sh root@<droplet>}"
cd "$(dirname "$0")/.."
live=$(ssh "$host" 'curl -s --max-time 3 http://127.0.0.1:9100/health || true' | sed -n 's/.*"live": *\([0-9]*\).*/\1/p')
if [ "${live:-0}" != "0" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "A church is live right now ($live stream(s)). Deploy after the service, or FORCE=1."
  exit 1
fi
tar czf - docker-compose.yml mediamtx.yml player.html agent \
  | ssh "$host" 'mkdir -p /opt/stream_relay && tar xzf - -C /opt/stream_relay'
ssh "$host" 'set -e
  cd /opt/stream_relay
  test -f .env || { echo "No .env on the server yet: copy .env.example to /opt/stream_relay/.env and fill it in."; exit 1; }
  chmod 600 .env
  docker compose up -d --build
  sleep 3
  docker compose ps
  curl -s --max-time 3 http://127.0.0.1:9100/health; echo'
