#!/usr/bin/env bash
# Quick log tailing and streaming for raqnith.service
set -euo pipefail

SERVICE_NAME="raqnith.service"

if [[ "${1:-}" == "-f" || "${1:-}" == "--follow" ]]; then
    echo "Streaming live logs for ${SERVICE_NAME} (Ctrl+C to exit)..."
    sudo journalctl -u "${SERVICE_NAME}" -f -o cat
else
    LINES="${1:-30}"
    echo "Displaying last ${LINES} log lines for ${SERVICE_NAME}:"
    sudo journalctl -u "${SERVICE_NAME}" -n "${LINES}" --no-pager
fi
