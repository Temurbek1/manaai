#!/usr/bin/env bash
set -euo pipefail

container_name="manaai-audit-postgres-$$"
database_password="test-postgres-local-only"

cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --rm --detach \
  --name "${container_name}" \
  --env POSTGRES_DB=manaai_audit \
  --env POSTGRES_USER=manaai \
  --env "POSTGRES_PASSWORD=${database_password}" \
  --publish 127.0.0.1::5432 \
  postgres:17-alpine >/dev/null

for _ in $(seq 1 60); do
  if docker exec "${container_name}" pg_isready --username manaai --dbname manaai_audit \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${container_name}" pg_isready --username manaai --dbname manaai_audit >/dev/null

host_port=$(docker port "${container_name}" 5432/tcp | awk -F: '{print $NF}')
export OPERATION_DATABASE_URL="postgresql+asyncpg://manaai:${database_password}@127.0.0.1:${host_port}/manaai_audit"
export TEST_POSTGRES_URL="${OPERATION_DATABASE_URL}"
export OPENAI_API_KEY=test-key

.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/pytest -q tests/test_postgres_repository.py
