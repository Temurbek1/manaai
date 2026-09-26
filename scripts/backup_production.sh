#!/bin/sh
set -eu

compose_dir=${MANA_AI_COMPOSE_DIR:-/root/mana-ai}
backup_root=${MANA_AI_BACKUP_ROOT:-/var/backups/mana-ai}
retention_days=${MANA_AI_BACKUP_RETENTION_DAYS:-14}

if [ ! -f "$compose_dir/docker-compose.yml" ] || [ ! -f "$compose_dir/.env" ]; then
  echo "MANA AI Compose deployment is incomplete: $compose_dir" >&2
  exit 1
fi
case "$backup_root" in
  /|/root|/var|/var/backups)
    echo "Refusing unsafe backup root: $backup_root" >&2
    exit 1
    ;;
esac
case "$retention_days" in
  ''|*[!0-9]*)
    echo "MANA_AI_BACKUP_RETENTION_DAYS must be an integer" >&2
    exit 1
    ;;
esac

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="$backup_root/$timestamp"
temporary="$backup_root/.partial-$timestamp"
umask 077
mkdir -p "$backup_root" "$temporary"
cleanup() {
  rm -rf -- "$temporary"
}
trap cleanup EXIT INT TERM

compose() {
  docker compose --project-name mana-ai --project-directory "$compose_dir" "$@"
}

compose exec -T postgres sh -c \
  'exec pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_USER" "$POSTGRES_DB"' \
  >"$temporary/postgres.dump"

compose exec -T api python - <<'PY'
import sqlite3
from pathlib import Path

source_path = Path("/data/manaai.db")
backup_path = Path("/tmp/manaai-marketing-backup.db")
if backup_path.exists():
    backup_path.unlink()
with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
    source.backup(backup)
PY
compose cp api:/tmp/manaai-marketing-backup.db "$temporary/marketing.db"
compose exec -T api rm -f /tmp/manaai-marketing-backup.db

install -m 600 "$compose_dir/.env" "$temporary/environment.env"
install -m 600 "$compose_dir/docker-compose.yml" "$temporary/docker-compose.yml"
if [ -d /etc/nginx/sites-enabled ]; then
  set -- nginx.conf sites-enabled
  [ ! -d /etc/nginx/sites-available ] || set -- "$@" sites-available
  [ ! -d /etc/nginx/ssl ] || set -- "$@" ssl
  tar -C /etc/nginx -czf "$temporary/nginx-config.tar.gz" "$@"
fi

docker run --rm -v "$temporary:/backup:ro" postgres:17-alpine \
  pg_restore --list /backup/postgres.dump >/dev/null
(
  cd "$temporary"
  sha256sum ./* >SHA256SUMS
)
mv "$temporary" "$destination"
trap - EXIT INT TERM

find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -mtime "+$retention_days" -exec rm -rf -- {} +

echo "MANA AI backup completed: $destination"
