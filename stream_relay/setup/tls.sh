#!/usr/bin/env bash
# On the droplet (deploy.sh runs it): make the RTMPS certificate for
# STREAM_HOST once, and put it where MediaMTX reads it. Renewals happen on
# their own (certbot's timer), through install-cert.sh.
# Needs: the DNS A record for STREAM_HOST pointing here, port 80 open.
set -euo pipefail
cd /opt/stream_relay
host=$(sed -n 's/^STREAM_HOST=\([^ #]*\).*/\1/p' .env | head -1)
[ -n "$host" ] || { echo "Set STREAM_HOST in /opt/stream_relay/.env first."; exit 1; }
if [ ! -f "/etc/letsencrypt/live/$host/fullchain.pem" ]; then
  certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email \
    -d "$host" --deploy-hook /opt/stream_relay/setup/install-cert.sh
fi
RENEWED_LINEAGE="/etc/letsencrypt/live/$host" /opt/stream_relay/setup/install-cert.sh
