#!/usr/bin/env bash
# Quick status dashboard for raqnith.service
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

SERVICE_NAME="raqnith.service"
HOST_HEADER="${DJANGO_ALLOWED_HOSTS:-raqnith.duckdns.org}"
DEPLOY_CONF="/home/ubuntu/deploy/docker/raqnith.conf"
PORT="8002"

echo -e "${BOLD}==============================================${NC}"
echo -e "${BOLD}       Raqnith Production Service Status      ${NC}"
echo -e "${BOLD}==============================================${NC}"

# Check Online / Offline state
if [[ -f "${DEPLOY_CONF}" ]] && grep -q "X-Robots-Tag" "${DEPLOY_CONF}"; then
    echo -e "Public State:      ${RED}${BOLD}OFFLINE (Maintenance / Blocked from Search Engines)${NC}"
else
    echo -e "Public State:      ${GREEN}${BOLD}ONLINE (Publicly Accessible at https://${HOST_HEADER%%,*})${NC}"
fi

# Check systemd state
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "Service State:     ${GREEN}ACTIVE (RUNNING)${NC}"
else
    echo -e "Service State:     ${RED}INACTIVE / STOPPED${NC}"
fi

# Check systemd enable state
ENABLE_STATE=$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || echo "unknown")
echo -e "Boot Persistence:  ${BLUE}${ENABLE_STATE}${NC}"

# HTTP Health check
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${HOST_HEADER%%,*}" -H "X-Forwarded-Proto: https" "http://127.0.0.1:${PORT}/" || echo "000")
if [[ "$HTTP_CODE" =~ ^(200|301|302)$ ]]; then
    echo -e "HTTP Endpoint:     ${GREEN}http://127.0.0.1:${PORT}/ (HTTP ${HTTP_CODE} OK)${NC}"
else
    echo -e "HTTP Endpoint:     ${RED}http://127.0.0.1:${PORT}/ (HTTP ${HTTP_CODE})${NC}"
fi

echo ""
echo -e "${BLUE}==>${NC} Detailed Systemd Unit Info:"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true

echo ""
echo -e "${BLUE}==>${NC} Recent Logs (last 10 lines):"
sudo journalctl -u "${SERVICE_NAME}" -n 10 --no-pager || true
