#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-http://127.0.0.1:8080}"
base_url="${base_url%/}"

curl --fail --silent --show-error --max-time 10 "${base_url}/health/ready" >/dev/null
curl --fail --silent --show-error --max-time 10 "${base_url}/" >/dev/null

handshake="$(curl --fail --silent --show-error --max-time 10 "${base_url}/socket.io/?EIO=4&transport=polling")"
if [[ "${handshake}" != 0\{* ]]; then
    echo "Socket.IO handshake failed" >&2
    exit 1
fi

echo "Smoke checks passed: health, frontend and Socket.IO handshake"
