#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AUDIT_TMP_DIR=$(mktemp -d -t manaai-browser-audit.XXXXXX)
AUDIT_API_PORT=${AUDIT_API_PORT:-18080}
AUDIT_UI_PORT=${AUDIT_UI_PORT:-15173}
AUDIT_BROWSER_SESSION="manaai-e2e-$$"
BACKEND_PID=""
FRONTEND_PID=""
BROWSER_BIN="$PROJECT_ROOT/admin-ui/node_modules/.bin/agent-browser"

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM
  set +e
  "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" close >/dev/null 2>&1
  if [[ -n "$FRONTEND_PID" ]]; then kill "$FRONTEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$BACKEND_PID" ]]; then kill "$BACKEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$FRONTEND_PID" ]]; then wait "$FRONTEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$BACKEND_PID" ]]; then wait "$BACKEND_PID" >/dev/null 2>&1; fi
  if [[ $exit_status -ne 0 ]]; then
    tail -n 80 "$AUDIT_TMP_DIR/backend.log" 2>/dev/null
    tail -n 80 "$AUDIT_TMP_DIR/frontend.log" 2>/dev/null
  fi
  if [[ -n "$AUDIT_TMP_DIR" && -d "$AUDIT_TMP_DIR" ]]; then
    rm -r -- "$AUDIT_TMP_DIR"
  fi
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

if [[ ! -x "$BROWSER_BIN" ]]; then
  echo "agent-browser is not installed; run npm ci in admin-ui" >&2
  exit 1
fi

"$BROWSER_BIN" install >/dev/null

CORS_ORIGINS="[\"http://127.0.0.1:${AUDIT_UI_PORT}\"]" \
APP_ENV=local \
APP_API_KEY= \
OPENAI_API_KEY=test-openai-key \
META_ACCESS_TOKEN= \
OPERATION_ADS_PROVIDER=fake_meta \
OPERATION_DRY_RUN=false \
OPERATION_ALLOW_SELF_APPROVAL=false \
OPERATION_SCHEDULER_ENABLED=false \
OPERATION_AUTO_CREATE_SCHEMA=true \
OPERATION_DATABASE_URL="sqlite+aiosqlite:///$AUDIT_TMP_DIR/operation.db" \
MARKETING_DATABASE_PATH="$AUDIT_TMP_DIR/legacy.db" \
"$PROJECT_ROOT/.venv/bin/uvicorn" app.main:create_app --factory \
  --app-dir "$PROJECT_ROOT" --host 127.0.0.1 --port "$AUDIT_API_PORT" \
  >"$AUDIT_TMP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

VITE_API_BASE="http://127.0.0.1:${AUDIT_API_PORT}" \
npm --prefix "$PROJECT_ROOT/admin-ui" run dev -- --host 127.0.0.1 --port "$AUDIT_UI_PORT" \
  >"$AUDIT_TMP_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

for _ in $(seq 1 80); do
  if curl --fail --silent "http://127.0.0.1:${AUDIT_API_PORT}/api/v1/health/live" >/dev/null && \
    curl --fail --silent "http://127.0.0.1:${AUDIT_UI_PORT}/" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl --fail --silent "http://127.0.0.1:${AUDIT_API_PORT}/api/v1/health/live" >/dev/null
curl --fail --silent "http://127.0.0.1:${AUDIT_UI_PORT}/" >/dev/null

browser() {
  "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" "$@"
}

assert_browser() {
  local condition=$1
  local message=$2
  browser eval "if (!($condition)) { throw new Error('$message'); } 'OK'" >/dev/null
}

browser open "http://127.0.0.1:${AUDIT_UI_PORT}/" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Sign in to the control room")' 'login did not render'
assert_browser '!document.querySelector(".vite-error-overlay")' 'Vite error overlay is visible'

browser find label "Development actor ID" fill "browser-operator" >/dev/null
browser eval '(() => { const select = [...document.querySelectorAll("select")].find((item) => item.closest("label")?.textContent?.includes("Development role")); if (!(select instanceof HTMLSelectElement)) throw new Error("development role selector missing"); const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set; setter?.call(select, "admin"); select.dispatchEvent(new Event("change", { bubbles: true })); return "selected"; })()' >/dev/null
browser find role button click --name "Sign in" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Operation overview")' 'dashboard did not render'

browser find role button click --name "Run now" >/dev/null
browser wait --load networkidle >/dev/null
browser find role button click --name "Marketing Agent" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Best-performing creative")' 'finding was not rendered'
assert_browser 'document.body.innerText.includes("scale_audience")' 'scale proposal was not rendered'

browser find role button click --name "Sign out" >/dev/null
browser find label "Development actor ID" fill "browser-approver" >/dev/null
browser eval '(() => { const select = [...document.querySelectorAll("select")].find((item) => item.closest("label")?.textContent?.includes("Development role")); if (!(select instanceof HTMLSelectElement)) throw new Error("development role selector missing"); const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set; setter?.call(select, "admin"); select.dispatchEvent(new Event("change", { bubbles: true })); return "selected"; })()' >/dev/null
browser find role button click --name "Sign in" >/dev/null
browser wait --load networkidle >/dev/null
browser find role button click --name "Approvals" >/dev/null
browser wait --load networkidle >/dev/null

browser eval '(() => { const card = [...document.querySelectorAll(".approval-card")].find((item) => item.textContent?.includes("scale audience")); if (!card) throw new Error("scale approval card missing"); const input = card.querySelector("textarea"); const button = [...card.querySelectorAll("button")].find((item) => item.textContent?.trim() === "Approve"); if (!(input instanceof HTMLTextAreaElement) || !(button instanceof HTMLButtonElement)) throw new Error("scale controls missing"); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set; setter?.call(input, "Browser E2E reviewed evidence and policy limits"); input.dispatchEvent(new Event("input", { bubbles: true })); button.click(); return "submitted"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Approved and succeeded")' 'approved write did not succeed'

browser eval '(() => { const card = document.querySelector(".approval-card"); if (!card) throw new Error("remaining approval card missing"); const input = card.querySelector("textarea"); const button = [...card.querySelectorAll("button")].find((item) => item.textContent?.trim() === "Reject"); if (!(input instanceof HTMLTextAreaElement) || !(button instanceof HTMLButtonElement)) throw new Error("rejection controls missing"); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set; setter?.call(input, "Browser E2E rejects the remaining financial increase"); input.dispatchEvent(new Event("input", { bubbles: true })); button.click(); return "submitted"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Queue is clear")' 'approval queue did not clear'

browser find role button click --name "Marketing Agent" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("SUCCEEDED")' 'execution status was not rendered'
assert_browser 'document.querySelector(".report-copy")?.textContent?.includes("Marketing report")' 'report was not rendered'

browser find role button click --name "Runs & audit" >/dev/null
browser wait --load networkidle >/dev/null
browser eval 'document.querySelector(".link-button")?.click(); "opened"' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("action_verified")' 'verification audit event was not rendered'
assert_browser 'document.body.innerText.includes("report_created")' 'report audit event was not rendered'
assert_browser 'document.body.innerText.includes("COMPLETED")' 'run did not complete'
assert_browser '!document.querySelector("script .provider-payload")' 'untrusted provider markup rendered as HTML'
assert_browser '!document.querySelector(".vite-error-overlay")' 'Vite error overlay appeared'

browser set viewport 390 844 >/dev/null
assert_browser 'getComputedStyle(document.querySelector(".mobile-bar")).display !== "none"' 'responsive navigation did not render'
browser eval 'document.querySelector("[aria-label=\"Open menu\"]")?.click(); "opened"' >/dev/null
assert_browser 'document.querySelector("[aria-label=\"Open menu\"]")?.getAttribute("aria-expanded") === "true"' 'mobile menu did not open'
browser press Escape >/dev/null
assert_browser 'document.querySelector("[aria-label=\"Open menu\"]")?.getAttribute("aria-expanded") === "false"' 'Escape did not close the mobile menu'

echo "Browser E2E passed: fake data -> run -> finding -> approve -> execute -> verify -> audit/report"
