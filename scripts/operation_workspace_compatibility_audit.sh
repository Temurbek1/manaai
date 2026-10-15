#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
legacy_image="${WORKSPACE_LEGACY_IMAGE:-mana-ai-operation:2ea7b9a}"
current_image="${WORKSPACE_CURRENT_IMAGE:-}"
if [[ -n "${DOCKER_CONTEXT:-}" ]]; then
  docker_endpoint=$(docker context inspect "${DOCKER_CONTEXT}" --format '{{.Endpoints.docker.Host}}')
elif [[ -n "${DOCKER_HOST:-}" ]]; then
  docker_endpoint="${DOCKER_HOST}"
else
  docker_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
fi
case "${docker_endpoint}" in
  unix:///*) ;;
  *) echo "Workspace audit refuses remote/TCP Docker contexts." >&2; exit 2 ;;
esac
audit_docker() {
  DOCKER_CONTEXT= DOCKER_HOST="${docker_endpoint}" docker "$@"
}

# Never pull an unreviewed image or mount project configuration/customer data.
audit_docker image inspect "${legacy_image}" >/dev/null
if [[ -n "${current_image}" ]]; then
  audit_docker image inspect "${current_image}" >/dev/null
fi
audit_dir=$(mktemp -d -t manaai-workspace-compat.XXXXXX)
cleanup() { rm -r -- "${audit_dir}"; }
trap cleanup EXIT
chmod 755 "${audit_dir}"
cd "${project_root}"
database_file="${audit_dir}/synthetic.db"
probe_script="${project_root}/scripts/operation_workspace_compatibility_probe.py"
catalog_args=()
if [[ "${WORKSPACE_REPORT_DISCOVERY_AUDIT:-false}" == true ]]; then
  catalog_args=(--catalog)
fi
if [[ "${WORKSPACE_SNAPSHOT_REPLACEMENT_AUDIT:-false}" == true ]]; then
  catalog_args=(--catalog --snapshots)
fi
if [[ "${WORKSPACE_PAGE_PROJECTION_AUDIT:-false}" == true ]]; then
  catalog_args=(--catalog --snapshots --pages)
fi
if [[ "${WORKSPACE_REVIEW_VERDICTS_AUDIT:-false}" == true ]]; then
  catalog_args=(--catalog --snapshots --pages --verdicts)
fi
if [[ "${WORKSPACE_RETENTION_CONTACT_MEMORY_AUDIT:-false}" == true ]]; then
  catalog_args+=(--contacts)
fi
if [[ "${WORKSPACE_NATIVE_CONTACT_TOOL_AUDIT:-false}" == true ]]; then
  catalog_args+=(--contacts --native-contact)
fi
if [[ "${WORKSPACE_CONTACT_CONTINUATION_AUDIT:-false}" == true ]]; then
  catalog_args+=(--contacts --native-contact --contact-continuation)
fi

.venv/bin/python "${probe_script}" --database-file "${database_file}" --stage setup "${catalog_args[@]}"
run_legacy() {
  audit_docker run --rm --pull never --network none \
    --user "$(id -u):$(id -g)" --workdir /app \
    --mount "type=bind,source=${audit_dir},target=/audit-data" \
    --mount "type=bind,source=${probe_script},target=/audit/probe.py,readonly" \
    --entrypoint python "${legacy_image}" /audit/probe.py \
    --database-file /audit-data/synthetic.db --stage legacy "${catalog_args[@]}" "$@"
}
run_current() {
  if [[ -n "${current_image}" ]]; then
    audit_docker run --rm --pull never --network none \
      --user "$(id -u):$(id -g)" --workdir /app \
      --mount "type=bind,source=${audit_dir},target=/audit-data" \
      --mount "type=bind,source=${probe_script},target=/audit/probe.py,readonly" \
      --entrypoint python "${current_image}" /audit/probe.py \
      --database-file /audit-data/synthetic.db --stage verify "${catalog_args[@]}" "$@"
  fi
}
run_legacy
.venv/bin/python "${probe_script}" --database-file "${database_file}" --stage verify "${catalog_args[@]}"
run_current
export OPERATION_DATABASE_URL="sqlite+aiosqlite:///${database_file}"
export OPENAI_API_KEY=test-key
.venv/bin/python scripts/operation_workspace_rollback.py
.venv/bin/python scripts/operation_workspace_rollback.py --apply-pause --workers-stopped
run_legacy --paused
.venv/bin/python "${probe_script}" --database-file "${database_file}" --stage verify --paused "${catalog_args[@]}"
run_current --paused
echo "Workspace application rollback audit passed; no source requests or production changes."
