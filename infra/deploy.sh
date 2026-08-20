#!/usr/bin/env bash
# Raqnith Smooth Deployment & Reload Script
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_DIR="/home/ubuntu/raqnith"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
SERVICE_NAME="raqnith.service"
HOST_HEADER="${DJANGO_ALLOWED_HOSTS:-raqnith.duckdns.org}"
PORT="8002"

cd "${PROJECT_DIR}"

echo -e "${BOLD}==============================================${NC}"
echo -e "${BOLD}       Raqnith Production Deployment          ${NC}"
echo -e "${BOLD}==============================================${NC}"

# 1. Run migrations
echo -e "\n${BLUE}[1/4]${NC} Running database migrations..."
"${VENV_PYTHON}" manage.py migrate --no-input

# 2. Collect static files
echo -e "\n${BLUE}[2/4]${NC} Collecting static assets..."
"${VENV_PYTHON}" manage.py collectstatic --no-input

# 3. Restart gunicorn via systemd
echo -e "\n${BLUE}[3/4]${NC} Restarting ${YELLOW}${SERVICE_NAME}${NC}..."
sudo systemctl restart "${SERVICE_NAME}"
sleep 1

# 4. Validate health
echo -e "\n${BLUE}[4/4]${NC} Validating deployment health..."
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "${GREEN}✓${NC} Systemd unit: ${GREEN}Active & Running${NC}"
else
    echo -e "${RED}✗${NC} Systemd unit failed to start!"
    sudo systemctl status "${SERVICE_NAME}" --no-pager
    exit 1
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${HOST_HEADER%%,*}" -H "X-Forwarded-Proto: https" "http://127.0.0.1:${PORT}/" || echo "000")
if [[ "$HTTP_CODE" =~ ^(200|301|302)$ ]]; then
    echo -e "${GREEN}✓${NC} Health Check: ${GREEN}HTTP ${HTTP_CODE} OK${NC}"
    echo -e "\n${GREEN}${BOLD}Deployment completed successfully!${NC}"
else
    echo -e "${YELLOW}!${NC} Health Check returned: HTTP ${HTTP_CODE}"
fi
