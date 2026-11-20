#!/usr/bin/env bash
# Rebind the renewed certificate files only for the configured demo certificate.
set -euo pipefail
[[ -n ${RENEWED_LINEAGE:-} ]] || exit 0
selected=$(sed -n 's/^DEMO_TLS_CERT=//p' /etc/agentledger-demo/production.env | tr -d '\r')
[[ "$RENEWED_LINEAGE/fullchain.pem" == "$selected" ]] || exit 0
exec bash /opt/agentledger-demo/bin/deploy.sh renew-tls
