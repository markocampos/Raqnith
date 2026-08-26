#!/usr/bin/env bash
# Raqnith Offline Mode Switch
# Switches raqnith.duckdns.org to offline/maintenance mode and stops the backend service.
# Site remains offline and unsearchable until deploy.sh is executed.
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_DIR="/home/ubuntu/raqnith"
DEPLOY_DIR="/home/ubuntu/deploy/docker"
SERVICE_NAME="raqnith.service"
NGINX_CONTAINER="portfolio-nginx-1"
HOST_DOMAIN="raqnith.duckdns.org"

echo -e "${BOLD}==============================================${NC}"
echo -e "${BOLD}         Raqnith Offline Mode Activation       ${NC}"
echo -e "${BOLD}==============================================${NC}"

# 1. Update Nginx configuration to offline mode
echo -e "\n${BLUE}[1/3]${NC} Activating Nginx offline configuration..."
if [[ -f "${PROJECT_DIR}/infra/nginx-offline.conf" ]]; then
    cp "${PROJECT_DIR}/infra/nginx-offline.conf" "${DEPLOY_DIR}/raqnith.conf"
    echo -e "${GREEN}✓${NC} Applied offline Nginx configuration (503 + branded maintenance page, auto-refresh)"
else
    echo -e "${RED}✗${NC} Error: ${PROJECT_DIR}/infra/nginx-offline.conf not found!"
    exit 1
fi

# 2. Reload Nginx container
echo -e "\n${BLUE}[2/3]${NC} Reloading reverse proxy..."
if sudo docker ps --format '{{.Names}}' | grep -q "^${NGINX_CONTAINER}$"; then
    sudo docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null 2>&1
    sudo docker exec "${NGINX_CONTAINER}" nginx -s reload
    echo -e "${GREEN}✓${NC} Nginx reloaded successfully"
else
    echo -e "${YELLOW}!${NC} Container ${NGINX_CONTAINER} is not running; configuration updated on disk."
fi

# 3. Stop backend Django systemd service
echo -e "\n${BLUE}[3/3]${NC} Stopping ${YELLOW}${SERVICE_NAME}${NC}..."
sudo systemctl stop "${SERVICE_NAME}"
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "${GREEN}✓${NC} ${SERVICE_NAME} stopped (zero active backend processes)"
else
    echo -e "${RED}✗${NC} Failed to stop ${SERVICE_NAME}"
fi

echo -e "\n${BOLD}==============================================${NC}"
echo -e "${GREEN}${BOLD}✓ RAQNITH IS NOW OFFLINE${NC}"
echo -e "${BOLD}==============================================${NC}"
echo -e "• Domain:       ${YELLOW}https://${HOST_DOMAIN}${NC}"
echo -e "• Status:       ${RED}OFFLINE (HTTP 503 Maintenance)${NC}"
echo -e "• Indexing:     ${YELLOW}BLOCKED (X-Robots-Tag: noindex, nofollow)${NC}"
echo -e "• Django App:   ${RED}STOPPED${NC}"
echo -e "\nTo bring the site back online, run:"
echo -e "  ${GREEN}${PROJECT_DIR}/infra/deploy.sh${NC} or ${GREEN}${PROJECT_DIR}/infra/service.sh deploy${NC}\n"
