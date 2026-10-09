#!/usr/bin/env bash
set -euo pipefail

# Never run destructive migration round trips against a remote Docker daemon.
# An explicit context takes precedence over DOCKER_HOST in the Docker CLI.
if [[ -n "${DOCKER_CONTEXT:-}" ]]; then
  docker_endpoint=$(docker context inspect "${DOCKER_CONTEXT}" --format '{{.Endpoints.docker.Host}}')
elif [[ -n "${DOCKER_HOST:-}" ]]; then
  docker_endpoint="${DOCKER_HOST}"
else
  docker_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
fi
case "${docker_endpoint}" in
  unix:///*) ;;
  *)
    echo "PostgreSQL audit requires a local Unix Docker socket; remote/TCP contexts are refused." >&2
    exit 2
    ;;
esac

audit_docker() {
  # Pin every operation to the validated socket even if another shell changes
  # the active context. These overrides apply only to the child CLI command.
  DOCKER_CONTEXT= DOCKER_HOST="${docker_endpoint}" docker "$@"
}

container_name="manaai-audit-postgres-$$"
container_id=""
database_password="test-postgres-local-only"

cleanup() {
  # A failed create/name collision must not remove somebody else's container.
  # Use the immutable ID, never a name that could be reused after removal.
  if [[ "${container_id}" =~ ^[[:xdigit:]]{64}$ ]]; then
    audit_docker rm -f "${container_id}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

container_id=$(audit_docker run --rm --detach \
  --name "${container_name}" \
  --env POSTGRES_DB=manaai_audit \
  --env POSTGRES_USER=manaai \
  --env "POSTGRES_PASSWORD=${database_password}" \
  --publish 127.0.0.1::5432 \
  postgres:17-alpine)
if [[ ! "${container_id}" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "PostgreSQL audit did not receive a valid isolated container ID." >&2
  exit 2
fi

for _ in $(seq 1 60); do
  if audit_docker exec "${container_id}" pg_isready --username manaai --dbname manaai_audit \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
audit_docker exec "${container_id}" pg_isready --username manaai --dbname manaai_audit >/dev/null

host_port=$(audit_docker port "${container_id}" 5432/tcp | awk -F: '{print $NF}')
export OPERATION_DATABASE_URL="postgresql+asyncpg://manaai:${database_password}@127.0.0.1:${host_port}/manaai_audit"
export TEST_POSTGRES_URL="${OPERATION_DATABASE_URL}"
export OPENAI_API_KEY=test-key

.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/pytest -q tests/test_postgres_repository.py
