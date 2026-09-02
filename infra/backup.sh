#!/usr/bin/env bash
# Virtus PostgreSQL daily backup.
set -euo pipefail

BACKUP_DIR="${RAQNITH_BACKUP_DIR:-/opt/raqnith/backups}"
RETENTION_DAYS="${RAQNITH_BACKUP_RETENTION_DAYS:-30}"

# Load DB credentials from the Django .env (parsed with python-decouple-safe rules).
ENV_FILE="/home/ubuntu/raqnith/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source <(grep -E '^POSTGRES_(DB|USER|PASSWORD|HOST|PORT)=' "$ENV_FILE")
    set +a
fi

PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5433}"
PGDATABASE="${POSTGRES_DB:-raqnith}"
PGUSER="${POSTGRES_USER:-postgres}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DUMP="${BACKUP_DIR}/raqnith-${STAMP}.sql"

echo "Creating backup: ${DUMP}"
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    --host "$PGHOST" \
    --port "$PGPORT" \
    --dbname "$PGDATABASE" \
    --username "$PGUSER" \
    --no-owner \
    --no-privileges \
    --no-comments \
    > "$DUMP"

gzip -f "$DUMP"
echo "Backup complete: ${DUMP}.gz ($(du -h "${DUMP}.gz" | cut -f1))"

# Retention: prune backups older than RETENTION_DAYS.
find "$BACKUP_DIR" -name 'raqnith-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete