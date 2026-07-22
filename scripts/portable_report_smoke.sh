#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REPORT_PATH=${1:-docs/artifacts/meta-live-readonly-report.html}
REPORT_PORT=${PORTABLE_REPORT_SMOKE_PORT:-15175}
REPORT_SESSION="manaai-portable-report-$$"
BROWSER_BIN="$PROJECT_ROOT/admin-ui/node_modules/.bin/agent-browser"
SERVER_PID=""

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM
  set +e
  "$BROWSER_BIN" --session "$REPORT_SESSION" close >/dev/null 2>&1
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" >/dev/null 2>&1; fi
  if [[ -n "$SERVER_PID" ]]; then wait "$SERVER_PID" >/dev/null 2>&1; fi
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

if [[ ! -f "$PROJECT_ROOT/$REPORT_PATH" ]]; then
  echo "Portable report is missing: $REPORT_PATH" >&2
  exit 1
fi

"$PROJECT_ROOT/.venv/bin/python" -m http.server "$REPORT_PORT" \
  --bind 127.0.0.1 --directory "$PROJECT_ROOT" >/dev/null 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl --fail --silent "http://127.0.0.1:${REPORT_PORT}/${REPORT_PATH}" >/dev/null; then break; fi
  sleep 0.25
done
curl --fail --silent "http://127.0.0.1:${REPORT_PORT}/${REPORT_PATH}" >/dev/null

browser() {
  "$BROWSER_BIN" --session "$REPORT_SESSION" "$@"
}

assert_browser() {
  local condition=$1
  local message=$2
  browser eval "if (!($condition)) { throw new Error('$message'); } 'OK'" >/dev/null
}

browser open "http://127.0.0.1:${REPORT_PORT}/${REPORT_PATH}" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Meta live read-only validation")' 'report title is missing'
assert_browser 'document.documentElement.scrollWidth <= document.documentElement.clientWidth' 'desktop report overflows'
browser eval 'document.querySelector("#source-toggle")?.click(); "clicked"' >/dev/null
assert_browser 'document.querySelector("#source-toggle")?.getAttribute("aria-expanded") === "true"' 'source interaction failed'
assert_browser '!document.querySelector("#sources")?.hidden' 'source evidence did not open'
assert_browser 'performance.getEntriesByType("resource").every((entry) => new URL(entry.name).origin === location.origin)' 'report made an external request'
browser set viewport 390 844 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= document.documentElement.clientWidth' 'mobile report overflows'

echo "Portable report smoke passed for source interaction, desktop/mobile layout, and external requests"
