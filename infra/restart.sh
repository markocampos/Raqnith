#!/usr/bin/env bash
# Smooth restart script for raqnith.service with static assets collection and health validation.
set -euo pipefail

# ANSI color helpers
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/manage.py" ]]; then
    PROJECT_DIR="${SCRIPT_DIR}"
elif [[ -f "${SCRIPT_DIR}/../manage.py" ]]; then
    PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_DIR="/home/ubuntu/raqnith"
fi

if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_EXEC="${PROJECT_DIR}/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_EXEC="$(command -v python3)"
else
    PYTHON_EXEC="$(command -v python)"
fi

SERVICE_NAME="raqnith.service"
HOST_HEADER="${DJANGO_ALLOWED_HOSTS:-raqnith.duckdns.org}"
PORT="8002"

cd "${PROJECT_DIR}"

# 1. Update and collect static files
echo -e "${BLUE}==>${NC} Updating and collecting static assets..."
"${PYTHON_EXEC}" manage.py collectstatic --no-input

# 2. Restart systemd service
echo -e "${BLUE}==>${NC} Restarting ${YELLOW}${SERVICE_NAME}${NC}..."
sudo systemctl restart "${SERVICE_NAME}"

# Allow a moment for workers to bind
sleep 1

# 3. Check systemd status
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "${GREEN}✓${NC} ${SERVICE_NAME} is ${GREEN}active (running)${NC}."
else
    echo -e "${RED}✗${NC} ${SERVICE_NAME} failed to start."
    sudo systemctl status "${SERVICE_NAME}" --no-pager
    exit 1
fi

# 4. Probe local endpoint
echo -e "${BLUE}==>${NC} Performing HTTP health check on port ${PORT}..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${HOST_HEADER%%,*}" -H "X-Forwarded-Proto: https" "http://127.0.0.1:${PORT}/" || echo "000")

if [[ "$HTTP_CODE" =~ ^(200|301|302)$ ]]; then
    echo -e "${GREEN}✓${NC} HTTP Health Probe: ${GREEN}HTTP ${HTTP_CODE} OK${NC}"
else
    echo -e "${YELLOW}!${NC} HTTP Health Probe returned: HTTP ${HTTP_CODE} (service may still be initializing)"
fi

echo ""
sudo systemctl status "${SERVICE_NAME}" --no-pager -l

