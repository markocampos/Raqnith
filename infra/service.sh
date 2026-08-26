#!/usr/bin/env bash
# Unified Raqnith Management & Service CLI
set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND="${1:-help}"

case "$COMMAND" in
    restart)
        "${INFRA_DIR}/restart.sh"
        ;;
    status)
        "${INFRA_DIR}/status.sh"
        ;;
    logs)
        shift || true
        "${INFRA_DIR}/logs.sh" "$@"
        ;;
    deploy)
        "${INFRA_DIR}/deploy.sh"
        ;;
    offline)
        "${INFRA_DIR}/offline.sh"
        ;;
    online)
        "${INFRA_DIR}/deploy.sh"
        ;;
    backup)
        "${INFRA_DIR}/backup.sh"
        ;;
    start)
        echo "Starting raqnith.service..."
        sudo systemctl start raqnith.service
        "${INFRA_DIR}/status.sh"
        ;;
    stop)
        echo "Stopping raqnith.service..."
        sudo systemctl stop raqnith.service
        echo "Service stopped."
        ;;
    reload)
        echo "Reloading gunicorn workers..."
        sudo systemctl reload-or-restart raqnith.service
        "${INFRA_DIR}/status.sh"
        ;;
    check)
        /home/ubuntu/raqnith/.venv/bin/python /home/ubuntu/raqnith/manage.py check --deploy --settings=config.settings.production
        ;;
    help|--help|-h|*)
        echo "Raqnith Service Management CLI"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  offline       Put raqnith.duckdns.org in offline mode (503 + block search indexing)"
        echo "  deploy        Deploy updates, bring site online, run migrations, collectstatic & restart"
        echo "  online        Alias for deploy (brings site online)"
        echo "  restart       Restart raqnith.service with status and health probe"
        echo "  status        Display production status (online/offline state, service state, logs)"
        echo "  logs [-f]     View or stream systemd journal logs"
        echo "  start         Start the raqnith.service"
        echo "  stop          Stop the raqnith.service"
        echo "  reload        Gracefully reload service workers"
        echo "  backup        Run PostgreSQL database backup"
        echo "  check         Run Django deployment security check"
        echo ""
        ;;
esac
