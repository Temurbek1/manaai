#!/usr/bin/env bash
set -euo pipefail

if [[ "${META_LIVE_READONLY_VERIFY:-0}" != "1" ]]; then
  echo "Live admin smoke skipped: set META_LIVE_READONLY_VERIFY=1 after the bounded GET verification."
  exit 0
fi

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SMOKE_TMP_DIR=$(mktemp -d -t manaai-admin-live-readonly.XXXXXX)
API_PORT=${ADMIN_LIVE_API_PORT:-18081}
UI_PORT=${ADMIN_LIVE_UI_PORT:-15174}
BROWSER_SESSION="manaai-live-readonly-ui-$$"
BROWSER_BIN="$PROJECT_ROOT/admin-ui/node_modules/.bin/agent-browser"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM
  set +e
  "$BROWSER_BIN" --session "$BROWSER_SESSION" close >/dev/null 2>&1
  if [[ -n "$FRONTEND_PID" ]]; then kill "$FRONTEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$BACKEND_PID" ]]; then kill "$BACKEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$FRONTEND_PID" ]]; then wait "$FRONTEND_PID" >/dev/null 2>&1; fi
  if [[ -n "$BACKEND_PID" ]]; then wait "$BACKEND_PID" >/dev/null 2>&1; fi
  if [[ $exit_status -ne 0 ]]; then
    tail -n 80 "$SMOKE_TMP_DIR/backend.log" 2>/dev/null
    tail -n 80 "$SMOKE_TMP_DIR/frontend.log" 2>/dev/null
  fi
  rm -r -- "$SMOKE_TMP_DIR"
  exit "$exit_status"
}
trap cleanup EXIT INT TERM

"$BROWSER_BIN" install >/dev/null

CORS_ORIGINS="[\"http://127.0.0.1:${UI_PORT}\"]" \
APP_ENV=local \
APP_API_KEY= \
OPENAI_API_KEY=test-openai-key \
MANA_TELEGRAM_AUTH_ENABLED=true \
MANA_OTP_HMAC_SECRET=test-live-ui-auth-hmac-secret-with-enough-entropy-123456 \
MANA_TELEGRAM_BOT_USERNAME=mana_test_bot \
MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS=976835256,51456737 \
MANA_TRUSTED_ORIGINS="[\"http://127.0.0.1:${UI_PORT}\"]" \
MANA_AUTH_TEST_MODE=true \
MANA_AUTH_TEST_OTP_SINK_PATH="$SMOKE_TMP_DIR/otp-sink.jsonl" \
OPERATION_ALLOW_INSECURE_DEV_HEADERS=false \
OPERATION_DATABASE_URL="sqlite+aiosqlite:///$SMOKE_TMP_DIR/operation.db" \
MARKETING_DATABASE_PATH="$SMOKE_TMP_DIR/legacy.db" \
OPERATION_ADS_PROVIDER=meta \
OPERATION_DRY_RUN=true \
OPERATION_SCHEDULER_ENABLED=false \
META_LIVE_MODE=read_only \
META_REAL_WRITES_ENABLED=false \
"$PROJECT_ROOT/.venv/bin/uvicorn" app.main:create_app --factory \
  --app-dir "$PROJECT_ROOT" --host 127.0.0.1 --port "$API_PORT" \
  >"$SMOKE_TMP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

FASTAPI_BASE_URL="http://127.0.0.1:${API_PORT}" \
npm --prefix "$PROJECT_ROOT/admin-ui" run dev -- --hostname 127.0.0.1 --port "$UI_PORT" \
  >"$SMOKE_TMP_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

for _ in $(seq 1 120); do
  if curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/health/live" >/dev/null \
    && curl --fail --silent "http://127.0.0.1:${UI_PORT}/marketing" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/health/live" >/dev/null
curl --fail --silent "http://127.0.0.1:${UI_PORT}/marketing" >/dev/null

browser() {
  "$BROWSER_BIN" --session "$BROWSER_SESSION" "$@"
}

assert_browser() {
  local condition=$1
  local message=$2
  browser eval "if (!($condition)) { throw new Error('$message'); } 'OK'" >/dev/null
}

browser open "http://127.0.0.1:${UI_PORT}/marketing" >/dev/null
browser wait --load networkidle >/dev/null
browser find label "Telegram ID" fill "976835256" >/dev/null
browser find role button click --name "Получить код" >/dev/null
for _ in $(seq 1 40); do
  if OTP_CODE=$("$PROJECT_ROOT/.venv/bin/python" -c \
    'import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); rows=[json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []; print(rows[-1]["code"] if rows else ""); raise SystemExit(0 if rows else 1)' \
    "$SMOKE_TMP_DIR/otp-sink.jsonl" 2>/dev/null); then break; fi
  sleep 0.1
done
if [[ ! "${OTP_CODE:-}" =~ ^[0-9]{6}$ ]]; then
  echo "Fake Telegram harness did not capture an OTP" >&2
  exit 1
fi
browser find label "Код из Telegram" fill "$OTP_CODE" >/dev/null
unset OTP_CODE
browser find role button click --name "Войти" >/dev/null
browser wait --load networkidle >/dev/null
browser wait --text "READ-ONLY MODE" >/dev/null
browser wait --text "Enforced" >/dev/null

assert_browser 'location.pathname === "/marketing"' 'live Marketing route changed unexpectedly'
assert_browser 'document.body.innerText.includes("LIVE META — READ ONLY")' 'live read-only banner is missing'
assert_browser 'document.body.innerText.includes("Meta Ads intelligence")' 'live Marketing page did not render'
assert_browser '(() => { const term = [...document.querySelectorAll("dt")].find((item) => item.textContent?.trim() === "Read-only mode"); return term?.parentElement?.querySelector("dd")?.textContent?.trim() === "Enforced"; })()' 'read-only provider state is not explicit'
assert_browser '(() => { const term = [...document.querySelectorAll("dt")].find((item) => item.textContent?.trim() === "Selected account"); const value = term?.parentElement?.querySelector("dd")?.textContent?.trim(); return value === "unavailable" || Boolean(value?.match(/^[a-f0-9]{10}$/)); })()' 'selected account is not represented by a safe alias'
assert_browser '![...document.querySelectorAll("button")].some((button) => /execute/i.test(button.textContent ?? ""))' 'an execute control is visible in live read-only mode'
assert_browser 'document.documentElement.scrollWidth <= document.documentElement.clientWidth' 'desktop live page has horizontal overflow'

browser set viewport 390 844 >/dev/null
assert_browser 'getComputedStyle(document.querySelector(".mobile-bar")).display !== "none"' 'mobile navigation is missing on live page'
assert_browser 'document.documentElement.scrollWidth <= document.documentElement.clientWidth' 'mobile live page has horizontal overflow'

echo "Live Meta admin page smoke passed in read-only mode without action mutations"
