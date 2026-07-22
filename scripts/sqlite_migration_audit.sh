#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MIGRATION_TMP_DIR=$(mktemp -d -t manaai-migration-audit.XXXXXX)

cleanup() {
  if [[ -n "$MIGRATION_TMP_DIR" && -d "$MIGRATION_TMP_DIR" ]]; then
    rm -r -- "$MIGRATION_TMP_DIR"
  fi
}
trap cleanup EXIT

export OPENAI_API_KEY=test-openai-key
export OPERATION_DATABASE_URL="sqlite+aiosqlite:///$MIGRATION_TMP_DIR/clean.db"

cd "$PROJECT_ROOT"
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
.venv/bin/alembic check

if [[ -f "$PROJECT_ROOT/data/manaai.db" ]]; then
  cp "$PROJECT_ROOT/data/manaai.db" "$MIGRATION_TMP_DIR/existing-copy.db"
  export OPERATION_DATABASE_URL="sqlite+aiosqlite:///$MIGRATION_TMP_DIR/existing-copy.db"
  operation_schema_exists=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='operation_agents';")
  migration_version_exists=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='alembic_version';")
  if [[ "$operation_schema_exists" == "1" && "$migration_version_exists" == "0" ]]; then
    auth_schema_exists=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
      "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='operation_admin_users';")
    if [[ "$auth_schema_exists" == "1" ]]; then
      .venv/bin/alembic stamp head
    else
      .venv/bin/alembic stamp 6ddfe7f9abc8
    fi
  fi
  .venv/bin/alembic upgrade head
  .venv/bin/alembic check
fi

echo "SQLite migration audit passed: clean round trip, drift check, and existing-copy upgrade"
