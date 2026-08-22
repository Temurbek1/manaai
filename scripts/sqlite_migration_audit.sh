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
  migration_version_rows=0
  if [[ "$migration_version_exists" == "1" ]]; then
    migration_version_rows=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
      "SELECT COUNT(*) FROM alembic_version;")
  fi
  if [[ "$operation_schema_exists" == "1" && "$migration_version_rows" == "0" ]]; then
    auth_schema_exists=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
      "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='operation_admin_users';")
    if [[ "$auth_schema_exists" == "1" ]]; then
      .venv/bin/alembic stamp 8b7c2e4d901a
    else
      .venv/bin/alembic stamp 6ddfe7f9abc8
    fi
  fi
  .venv/bin/alembic upgrade head
  .venv/bin/alembic check
  enabled_legacy_schedules=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
    "SELECT COUNT(*) FROM operation_agent_schedules WHERE agent_id='marketing-agent' AND enabled=1;")
  invalid_legacy_payloads=$(sqlite3 "$MIGRATION_TMP_DIR/existing-copy.db" \
    "SELECT COUNT(*) FROM operation_agent_schedules WHERE agent_id='marketing-agent' AND (capability_key!='growth.advertising' OR json_extract(payload, '$.enabled')!=0 OR json_extract(payload, '$.capability_key')!='growth.advertising');")
  if [[ "$enabled_legacy_schedules" != "0" || "$invalid_legacy_payloads" != "0" ]]; then
    echo "Legacy marketing schedules were not safely disabled during Growth cutover" >&2
    exit 1
  fi
  .venv/bin/python - <<'PY'
import asyncio

from app.main import create_app


async def verify_growth_bootstrap() -> None:
    application = create_app()
    async with application.router.lifespan_context(application):
        schedules = await application.state.operation_repository.list_schedules()
        active_ids = {item.schedule_id for item in schedules if item.enabled}
        expected_growth_ids = {
            "growth-advertising-analysis",
            "growth-advertising-nightly-report",
            "growth-funnel-analysis",
        }
        if not expected_growth_ids.issubset(active_ids):
            raise RuntimeError("Growth schedules were not bootstrapped after migration")
        if any(
            item.agent_id == "marketing-agent" and item.enabled
            for item in schedules
        ):
            raise RuntimeError("Legacy marketing schedules remained active after bootstrap")


asyncio.run(verify_growth_bootstrap())
PY
fi

echo "SQLite migration audit passed: clean round trip, drift check, existing-copy upgrade, and legacy schedule cutover"
