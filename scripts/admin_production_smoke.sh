#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ADMIN_PORT=${ADMIN_PRODUCTION_SMOKE_PORT:-13000}
SMOKE_TMP_DIR=$(mktemp -d -t manaai-admin-production.XXXXXX)
SERVER_PID=""

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" >/dev/null 2>&1; fi
  if [[ -n "$SERVER_PID" ]]; then wait "$SERVER_PID" >/dev/null 2>&1; fi
  if [[ $exit_status -ne 0 ]]; then tail -n 100 "$SMOKE_TMP_DIR/server.log" 2>/dev/null; fi
  rm -r -- "$SMOKE_TMP_DIR"
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

if [[ ! -f "$PROJECT_ROOT/admin-ui/.next/standalone/server.js" ]]; then
  echo "Standalone build is missing; run npm run build in admin-ui first" >&2
  exit 1
fi

cd "$PROJECT_ROOT/admin-ui/.next/standalone"
HOSTNAME=127.0.0.1 PORT="$ADMIN_PORT" node server.js >"$SMOKE_TMP_DIR/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 80); do
  if curl --fail --silent "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null; then break; fi
  sleep 0.25
done

curl --fail --silent "http://127.0.0.1:${ADMIN_PORT}/healthz" | rg --fixed-strings '"status":"ok"' >/dev/null
curl --fail --silent "http://127.0.0.1:${ADMIN_PORT}/" | rg --fixed-strings "Проверяем защищённую сессию" >/dev/null
curl --fail --silent "http://127.0.0.1:${ADMIN_PORT}/runs" | rg --fixed-strings "Проверяем защищённую сессию" >/dev/null
curl --fail --silent --head "http://127.0.0.1:${ADMIN_PORT}/runs" | rg --ignore-case '^content-security-policy:' >/dev/null

echo "Next.js standalone smoke passed for health, root, and direct nested route"
