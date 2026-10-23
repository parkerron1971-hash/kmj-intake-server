#!/usr/bin/env bash
# certbot's deploy hook: copy the certificate to where MediaMTX reads it
# (/opt/stream_relay/tls, mounted read-only). MediaMTX reloads it by
# itself, so nothing restarts and a renewal never interrupts a service.
set -euo pipefail
src="${RENEWED_LINEAGE:?run by certbot, or with RENEWED_LINEAGE set}"
dst=/opt/stream_relay/tls
install -d -m 755 "$dst"
install -m 644 "$src/fullchain.pem" "$dst/fullchain.pem.new"
install -m 600 "$src/privkey.pem" "$dst/privkey.pem.new"
mv -f "$dst/privkey.pem.new" "$dst/privkey.pem"
mv -f "$dst/fullchain.pem.new" "$dst/fullchain.pem"
