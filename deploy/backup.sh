#!/usr/bin/env bash
# Nightly database dump. Keeps 14 days.
#   crontab -e
#   0 5 * * * /opt/lyfe/deploy/backup.sh >> /var/log/lyfe-backup.log 2>&1
set -euo pipefail

cd /opt/lyfe
mkdir -p backups

STAMP=$(date +%Y-%m-%d_%H%M)
FILE="backups/lyfe_${STAMP}.sql.gz"

docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-lyfe}" "${POSTGRES_DB:-lyfe}" \
  | gzip > "$FILE"

echo "$(date -Is) backup written: $FILE ($(du -h "$FILE" | cut -f1))"

find backups -name "lyfe_*.sql.gz" -mtime +14 -delete
