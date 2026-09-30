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
  if [[ $exit_status -ne 0 && -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" screenshot "$AUDIT_SCREENSHOT_DIRECTORY/failure.png" --full >/dev/null 2>&1
    "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" errors 2>/dev/null
  fi
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
MANA_TELEGRAM_AUTH_ENABLED=true \
MANA_OTP_HMAC_SECRET=test-browser-auth-hmac-secret-with-enough-entropy-123456 \
MANA_TELEGRAM_BOT_USERNAME=mana_test_bot \
MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS=976835256,51456737 \
MANA_TRUSTED_ORIGINS="[\"http://127.0.0.1:${AUDIT_UI_PORT}\"]" \
MANA_AUTH_TEST_MODE=true \
MANA_AUTH_TEST_OTP_SINK_PATH="$AUDIT_TMP_DIR/otp-sink.jsonl" \
OPERATION_ALLOW_INSECURE_DEV_HEADERS=false \
OPERATION_ADS_PROVIDER=fake_meta \
OPERATION_PRODUCT_ACTIVITY_PROVIDER=fake \
AUDIO_MODERATION_ENABLED=false \
OPERATION_DRY_RUN=false \
OPERATION_ALLOW_SELF_APPROVAL=false \
OPERATION_SCHEDULER_ENABLED=false \
OPERATION_AUTO_CREATE_SCHEMA=true \
OPERATION_DATABASE_URL="sqlite+aiosqlite:///$AUDIT_TMP_DIR/operation.db" \
MARKETING_DATABASE_PATH="$AUDIT_TMP_DIR/legacy.db" \
"$PROJECT_ROOT/.venv/bin/uvicorn" scripts.browser_chat_app:create_app --factory \
  --app-dir "$PROJECT_ROOT" --host 127.0.0.1 --port "$AUDIT_API_PORT" \
  >"$AUDIT_TMP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

FASTAPI_BASE_URL="http://127.0.0.1:${AUDIT_API_PORT}" \
npm --prefix "$PROJECT_ROOT/admin-ui" run dev -- --hostname 127.0.0.1 --port "$AUDIT_UI_PORT" \
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

assert_accessible() {
  browser eval --stdin < "$PROJECT_ROOT/admin-ui/node_modules/axe-core/axe.min.js" >/dev/null
  browser eval '(async () => { const result = await axe.run(document, {runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa","wcag22aa"]}}); if (result.violations.length) throw new Error(JSON.stringify(result.violations.map(v => ({id:v.id,impact:v.impact,nodes:v.nodes.map(n => ({target:n.target,summary:n.failureSummary}))})))); return "Accessibility checks passed"; })()' >/dev/null
}

login_browser() {
  local telegram_id=$1
  local otp_code=""
  browser find label "Telegram ID" fill "$telegram_id" >/dev/null
  browser find role button click --name "Получить код" >/dev/null
  for _ in $(seq 1 40); do
    if otp_code=$("$PROJECT_ROOT/.venv/bin/python" -c \
      'import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); target=int(sys.argv[2]); rows=[json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []; matches=[row for row in rows if row.get("telegram_id") == target]; print(matches[-1]["code"] if matches else ""); raise SystemExit(0 if matches else 1)' \
      "$AUDIT_TMP_DIR/otp-sink.jsonl" "$telegram_id" 2>/dev/null); then
      break
    fi
    sleep 0.1
  done
  if [[ ! "$otp_code" =~ ^[0-9]{6}$ ]]; then
    echo "Fake Telegram harness did not capture a six-digit OTP" >&2
    return 1
  fi
  browser find label "Код из Telegram" fill "$otp_code" >/dev/null
  unset otp_code
  browser find role button click --name "Войти" >/dev/null
  browser wait --load networkidle >/dev/null
}

browser open "http://127.0.0.1:${AUDIT_UI_PORT}/" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Вход в MANA")' 'Telegram login did not render'
assert_browser '!document.body.innerText.includes("Internal API key")' 'human login still exposes API-key input'
assert_browser '!document.querySelector("nextjs-portal")?.shadowRoot?.querySelector("[data-nextjs-dialog-overlay]")' 'Next.js error overlay is visible'
assert_accessible

login_browser 976835256
assert_browser 'document.body.innerText.includes("Над чем поработаем?")' 'chat-first home did not render'
assert_browser 'document.querySelectorAll(".agent-nav-group").length === 4' 'four agent chats are missing'
assert_browser '!document.querySelector(".task-grid") && !document.querySelector("a[href=\"/users\"]")' 'professional controls leaked into chat mode'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser set viewport 1440 1000 >/dev/null
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-desktop.png" >/dev/null
fi
browser find label "Сообщение агенту" fill 'Помоги разобраться с удержанием' >/dev/null
browser find role button click --name "Отправить сообщение" >/dev/null
browser wait --fn 'document.body.innerText.includes("Это тестовый ответ")' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'location.pathname.includes("/topic/")' 'topic was not persisted in navigation'
assert_browser 'document.querySelectorAll(".topic-link").length === 1' 'topic did not appear under its agent'
browser eval '(async () => { const r = await fetch("/api/v1/admin/operation/chat/topics", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({agent_id:"growth-agent",product:"mana",title:"forbidden-without-csrf"})}); if(r.status !== 403) throw new Error("Chat mutation bypassed CSRF"); return "CSRF enforced"; })()' >/dev/null
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-conversation.png" >/dev/null
fi
browser reload >/dev/null
browser wait --fn 'document.body.innerText.includes("Это тестовый ответ")' >/dev/null
browser set viewport 320 812 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'chat overflows on mobile'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-mobile.png" >/dev/null
fi
browser set viewport 1440 1000 >/dev/null
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/overview" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Обзор работы")' 'dashboard did not render'
assert_browser 'document.querySelector(".session-box small")?.textContent?.trim() === "Администратор"' 'server session role is not admin'
assert_browser '!document.cookie.includes("mana_admin_session")' 'HttpOnly session cookie is browser-readable'
assert_browser 'document.querySelector(".skip-link")?.getAttribute("href") === "#main-content"' 'skip link is missing'
assert_browser 'document.querySelectorAll(".task-card").length === 3' 'task-based navigation is missing'
assert_browser 'document.querySelector(".skip-link").getBoundingClientRect().bottom <= 0 || document.activeElement.matches(".skip-link")' 'unfocused skip link is visible'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser set viewport 1440 1000 >/dev/null
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/overview-desktop.png" >/dev/null
fi

browser eval '(() => { const link = document.querySelector("a[href=\"/growth\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("growth route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Аналитика рекламы")' 'Growth advertising capability did not render'
browser eval '(() => { const link = document.querySelector("a[href=\"/overview\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("overview route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null
browser eval '(() => { const row = [...document.querySelectorAll("tr")].find(item => item.textContent.includes("Рост и конверсия")); row.querySelector("button").click(); return "started"; })()' >/dev/null
assert_browser 'document.querySelector("dialog[open]")?.contains(document.activeElement) && document.activeElement.textContent.trim() === "Отмена"' 'confirmation did not focus the safe choice'
browser press Shift+Tab >/dev/null
assert_browser 'document.querySelector("dialog[open]")?.contains(document.activeElement)' 'modal focus escaped on reverse tab'
browser press Escape >/dev/null
assert_browser '!document.querySelector("dialog[open]") && document.activeElement.textContent.trim() === "Запустить анализ"' 'cancel did not restore trigger focus'
browser eval 'document.activeElement.click(); "opened"' >/dev/null
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/confirmation-desktop.png" >/dev/null
fi
browser find role button click --name "Подтвердить сбор данных" >/dev/null
browser wait --load networkidle >/dev/null
browser eval '(() => { const link = document.querySelector("a[href=\"/growth\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("growth route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Best-performing creative")' 'finding was not rendered'
assert_browser 'document.body.innerText.includes("scale_audience")' 'scale proposal was not rendered'
assert_accessible

browser click '.session-box button' >/dev/null
browser wait --fn 'document.body.innerText.includes("Вход в MANA")' >/dev/null
assert_browser 'document.body.innerText.includes("Вход в MANA")' 'logout did not restore login boundary'
login_browser 51456737
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/growth-agent" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.querySelectorAll(".topic-link").length === 0' 'another administrator saw private topics'
browser find label "Сообщение агенту" fill 'Покажи предложения' >/dev/null
browser find role button click --name "Отправить сообщение" >/dev/null
browser wait --fn 'document.querySelector(".chat-proposal-card") !== null' >/dev/null
assert_accessible
assert_browser '[...document.querySelectorAll(".chat-decision-buttons > button")].every(button => button.disabled)' 'empty reason allows a chat approval'
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-approvals.png" >/dev/null
fi
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/approvals" >/dev/null
browser wait --load networkidle >/dev/null
browser eval '(() => { const link = document.querySelector("a[href=\"/approvals\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("approvals route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null

browser eval '(() => { const card = [...document.querySelectorAll(".approval-card")].find((item) => item.textContent?.includes("Расширить аудиторию")); if (!card) throw new Error("scale approval card missing"); const input = card.querySelector("textarea"); const button = [...card.querySelectorAll("button")].find((item) => item.textContent?.trim() === "Одобрить"); if (!(input instanceof HTMLTextAreaElement) || !(button instanceof HTMLButtonElement)) throw new Error("scale controls missing"); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set; setter?.call(input, "Browser E2E reviewed evidence and policy limits"); input.dispatchEvent(new Event("input", { bubbles: true })); button.click(); return "submitted"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Одобрено. Выполнено")' 'approved write did not succeed'

browser eval '(() => { const card = document.querySelector(".approval-card"); if (!card) throw new Error("remaining approval card missing"); const input = card.querySelector("textarea"); const button = [...card.querySelectorAll("button")].find((item) => item.textContent?.trim() === "Отклонить"); if (!(input instanceof HTMLTextAreaElement) || !(button instanceof HTMLButtonElement)) throw new Error("rejection controls missing"); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set; setter?.call(input, "Browser E2E rejects the remaining financial increase"); input.dispatchEvent(new Event("input", { bubbles: true })); button.click(); return "submitted"; })()' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Всё рассмотрено")' 'approval queue did not clear'
assert_accessible

browser eval '(() => { const link = document.querySelector("a[href=\"/growth\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("growth route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null
browser wait --fn 'document.body.textContent.includes("Выполнено")' >/dev/null
assert_browser 'document.body.textContent.includes("Выполнено")' 'execution status was not rendered'
assert_browser 'document.querySelector(".report-copy")?.textContent?.includes("Marketing report")' 'report was not rendered'

browser eval '(() => { const link = document.querySelector("a[href=\"/runs\"]"); if (!(link instanceof HTMLAnchorElement)) throw new Error("runs route link missing"); link.click(); return "clicked"; })()' >/dev/null
browser wait --load networkidle >/dev/null
browser eval 'document.querySelector(".link-button")?.click(); "opened"' >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("action_verified")' 'verification audit event was not rendered'
assert_browser 'document.body.innerText.includes("report_created")' 'report audit event was not rendered'
assert_browser 'document.body.textContent.includes("Завершён")' 'run did not complete'
assert_browser '!document.querySelector("script .provider-payload")' 'untrusted provider markup rendered as HTML'
assert_browser '!document.querySelector("nextjs-portal")?.shadowRoot?.querySelector("[data-nextjs-dialog-overlay]")' 'Next.js error overlay appeared'

browser open "http://127.0.0.1:${AUDIT_UI_PORT}/runs" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'location.pathname === "/runs"' 'direct nested navigation changed the route'
assert_browser 'document.body.innerText.includes("Запуски и журнал")' 'server session did not survive direct refresh'
assert_accessible

browser set viewport 390 844 >/dev/null
assert_browser 'getComputedStyle(document.querySelector(".mobile-bar")).display !== "none"' 'responsive navigation did not render'
assert_browser 'getComputedStyle(document.querySelector(".sidebar")).display === "none"' 'closed mobile navigation remains keyboard-accessible'
browser eval 'document.querySelector("[aria-label=\"Открыть меню\"]")?.click(); "opened"' >/dev/null
assert_browser 'document.querySelector("[aria-label=\"Открыть меню\"]")?.getAttribute("aria-expanded") === "true"' 'mobile menu did not open'
assert_browser 'document.querySelector("nav").contains(document.activeElement)' 'mobile menu did not receive focus'
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/navigation-mobile.png" --full >/dev/null
fi
browser press Escape >/dev/null
assert_browser 'document.querySelector("[aria-label=\"Открыть меню\"]")?.getAttribute("aria-expanded") === "false"' 'Escape did not close the mobile menu'
assert_browser 'document.activeElement.getAttribute("aria-controls") === "primary-menu"' 'Escape did not return focus to the menu trigger'
browser set viewport 320 740 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'run list overflows at 320 CSS pixels'
assert_browser '[...document.querySelectorAll(".table-wrap")].every(item => item.tabIndex === 0)' 'scrollable tables cannot be reached with the keyboard'

browser eval '(async () => { const csrf = document.cookie.split("; ").find(item => item.startsWith("mana_csrf="))?.split("=")[1]; const response = await fetch("/api/v1/admin/operation/agents/retention-agent/run", {method:"POST", headers:{"Content-Type":"application/json", "X-CSRF-Token":decodeURIComponent(csrf)}, body:JSON.stringify({job_type:"analysis",idempotency_key:"browser-retention"})}); if (response.status !== 202) throw new Error("Retention fake run failed"); return "accepted"; })()' >/dev/null
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/retention" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Демонстрационные данные")' 'retention source mode is missing'
assert_browser 'document.body.innerText.includes("Источники и полнота данных")' 'retention evidence is missing'
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'retention mobile layout overflows'
assert_browser 'document.body.innerText.includes("Разделение MANA и 360REC")' 'unverified product scope is not disclosed'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/retention-mobile.png" --full >/dev/null
  browser set viewport 1440 1000 >/dev/null
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/retention-desktop.png" --full >/dev/null
fi

for route in agents users; do
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/${route}" >/dev/null
  browser wait --load networkidle >/dev/null
  assert_accessible
done

browser eval '(() => { const button = document.querySelector(".session-box button"); if (!(button instanceof HTMLButtonElement)) throw new Error("logout button missing"); button.click(); return "clicked"; })()' >/dev/null
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/runs" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Вход в MANA")' 'protected route did not return to login after logout'

echo "Browser E2E passed: fake Telegram OTP -> HttpOnly session -> run -> separate-admin approval -> refresh -> logout"
