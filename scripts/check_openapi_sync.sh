#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCHEMA_TMP_DIR=$(mktemp -d -t manaai-schema-audit.XXXXXX)

cleanup() {
  if [[ -n "$SCHEMA_TMP_DIR" && -d "$SCHEMA_TMP_DIR" ]]; then
    rm -r -- "$SCHEMA_TMP_DIR"
  fi
}
trap cleanup EXIT

cp "$PROJECT_ROOT/admin-ui/openapi.json" "$SCHEMA_TMP_DIR/openapi.json"
cp "$PROJECT_ROOT/admin-ui/src/api/schema.d.ts" "$SCHEMA_TMP_DIR/schema.d.ts"

cd "$PROJECT_ROOT/admin-ui"
npm run generate:api >/dev/null

cmp "$SCHEMA_TMP_DIR/openapi.json" "$PROJECT_ROOT/admin-ui/openapi.json"
cmp "$SCHEMA_TMP_DIR/schema.d.ts" "$PROJECT_ROOT/admin-ui/src/api/schema.d.ts"
echo "Generated OpenAPI document and TypeScript client are synchronized"
