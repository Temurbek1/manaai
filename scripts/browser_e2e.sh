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
    "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" --auto-connect false --restore-save never screenshot "$AUDIT_SCREENSHOT_DIRECTORY/failure.png" --full >/dev/null 2>&1
    "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" --auto-connect false --restore-save never errors 2>/dev/null
  fi
  "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" --auto-connect false --restore-save never close >/dev/null 2>&1
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

if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  mkdir -p -- "$AUDIT_SCREENSHOT_DIRECTORY"
fi

# Reuse a working installed browser; installation is only a missing-runtime fallback.
# Probe a private blank session, never the user's logged-in Chrome session.
if ! "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" --auto-connect false \
  --restore-save never open about:blank >/dev/null 2>&1; then
  "$BROWSER_BIN" install >/dev/null
fi

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
OPERATION_PARENT_ANALYTICS_ENABLED=false \
OPERATION_CHILD_TELEMETRY_ENABLED=false \
MANAKIDS_PARENT_SOURCE_ENABLED=false \
MANAKIDS_PARENT_MIN_INTERVAL_SECONDS="${AUDIT_PARENT_MIN_INTERVAL_SECONDS:-21600}" \
AUDIO_MODERATION_ENABLED=false \
OPERATION_DRY_RUN=false \
OPERATION_ALLOW_SELF_APPROVAL=false \
OPERATION_SCHEDULER_ENABLED=false \
OPERATION_GOALS_WORKER_ENABLED=false \
OPERATION_GOALS_MAX_STEPS=12 \
OPERATION_GOAL_LIMIT_EXTENSIONS_ENABLED="${AUDIT_LIMIT_EXTENSIONS:-false}" \
OPERATION_GOALS_EXTENSION_MAX_STEPS=24 \
OPERATION_GOALS_EXTENSION_BUDGET_MICROUSD=500000 \
OPERATION_MODEL_SELECTION_ENABLED=true \
OPERATION_AGENT_WORKSPACE_ENABLED="${AUDIT_AGENT_WORKSPACE:-false}" \
OPERATION_WORKSPACE_RETENTION_CONTACTS_ENABLED="${AUDIT_RETENTION_CONTACTS:-false}" \
OPERATION_WORKSPACE_RETENTION_PEER_REVIEWS_ENABLED="${AUDIT_RETENTION_PEER_REVIEWS:-false}" \
OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED="${AUDIT_CONTACT_TOOL_PROPOSALS:-false}" \
OPERATION_WORKSPACE_CONTACT_TOOL_CONTINUATIONS_ENABLED="${AUDIT_CONTACT_TOOL_CONTINUATIONS:-false}" \
OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED="${AUDIT_MODEL_CONTINUATION:-false}" \
OPERATION_WORKSPACE_REPORT_DISCOVERY_ENABLED="${AUDIT_REPORT_DISCOVERY:-false}" \
OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED="${AUDIT_SNAPSHOT_REPLACEMENT:-false}" \
OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED="${AUDIT_PAGE_PROJECTION:-false}" \
OPERATION_WORKSPACE_REVIEW_VERDICTS_ENABLED="${AUDIT_REVIEW_VERDICTS:-false}" \
OPERATION_WORKSPACE_CHAT_STREAMING_ENABLED="${AUDIT_CHAT_STREAMING:-false}" \
OPERATION_WORKSPACE_EVENTS_ENABLED=true \
OPERATION_WORKSPACE_STREAM_SECONDS=15 \
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
  # Client availability resolves after page navigation; network-idle alone does
  # not prove that the agent-mode composer has replaced its loading placeholder.
  if [[ "${1:-}" == find && "${2:-}" == label && "${3:-}" == "Сообщение агенту" ]]; then
    browser wait --fn 'document.querySelector("label[for=\"chat-message\"]")?.textContent === "Сообщение агенту" && !document.getElementById("chat-message")?.disabled && !document.querySelector(".chat-page")?.textContent.includes("Проверяем доступность AI…")' >/dev/null
  fi
  "$BROWSER_BIN" --session "$AUDIT_BROWSER_SESSION" --auto-connect false \
    --restore-save never "$@"
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
  local otp_sink_rows=0
  if [[ -f "$AUDIT_TMP_DIR/otp-sink.jsonl" ]]; then
    otp_sink_rows=$(wc -l < "$AUDIT_TMP_DIR/otp-sink.jsonl")
  fi
  browser find label "Telegram ID" fill "$telegram_id" >/dev/null
  browser find role button click --name "Получить код" >/dev/null
  for _ in $(seq 1 40); do
    if otp_code=$("$PROJECT_ROOT/.venv/bin/python" -c \
      'import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); target=int(sys.argv[2]); rows=[json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []; matches=[row for row in rows[int(sys.argv[3]):] if row.get("telegram_id") == target]; print(matches[-1]["code"] if matches else ""); raise SystemExit(0 if matches else 1)' \
      "$AUDIT_TMP_DIR/otp-sink.jsonl" "$telegram_id" "$otp_sink_rows" 2>/dev/null); then
      break
    fi
    sleep 0.1
  done
  if [[ ! "$otp_code" =~ ^[0-9]{6}$ ]]; then
    echo "Fake Telegram harness did not capture a six-digit OTP" >&2
    return 1
  fi
  browser wait --fn 'Boolean(document.querySelector("input[autocomplete=\"one-time-code\"]"))' >/dev/null
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

# Locale selection changes presentation only, never authentication or source settings.
browser select '.language-select' uz >/dev/null
browser wait --fn 'document.documentElement.lang === "uz" && document.body.innerText.includes("MANA’ga kirish")' >/dev/null
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/login-uzbek.png" --full >/dev/null
fi
browser reload >/dev/null
browser wait --fn 'document.querySelector(".language-select")?.value === "uz"' >/dev/null
browser select '.language-select' ru >/dev/null

login_browser 976835256
assert_browser 'document.body.innerText.includes("Над чем поработаем?")' 'chat-first home did not render'
assert_browser 'document.querySelectorAll(".agent-nav-group").length === 4' 'four agent chats are missing'
assert_browser '!document.querySelector(".task-grid") && !document.querySelector("a[href=\"/users\"]")' 'professional controls leaked into chat mode'
assert_browser '!document.querySelector(".topic-options, .chat-starters, .chat-tools-links")' 'manual setup controls leaked into the simple chat'
browser find label "Сообщение агенту" fill 'Не изменять исходную задачу 🧒' >/dev/null
browser select '.language-select' uz >/dev/null
browser wait --fn 'document.documentElement.lang === "uz" && document.body.innerText.includes("Nima ustida ishlaymiz?")' >/dev/null
assert_browser 'document.querySelector(".chat-page textarea")?.value === "Не изменять исходную задачу 🧒"' 'language switch changed the user draft'
assert_browser 'document.querySelectorAll(".agent-nav-group").length === 4 && document.body.innerText.includes("O‘sish va konversiya")' 'Uzbek agent navigation is missing'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-uzbek-desktop.png" --full >/dev/null
fi
browser reload >/dev/null
browser wait --fn 'document.querySelector(".language-select")?.value === "uz" && document.querySelector(".chat-page textarea")?.value === "Не изменять исходную задачу 🧒"' >/dev/null
browser set viewport 320 812 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'Uzbek chat overflows on mobile'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/chat-uzbek-mobile.png" --full >/dev/null
fi
# Use the mobile menu to reach the same locale selector, not a hidden element.
browser find role button click --name "Menyuni ochish" >/dev/null
browser select '.language-select' ru >/dev/null
browser find role button click --name "Открыть меню" >/dev/null
browser set viewport 1440 1000 >/dev/null
browser find label "Сообщение агенту" fill '' >/dev/null
if [[ "${AUDIT_PROFESSIONAL_UI:-false}" == true ]]; then
  # UI fixtures only: no GA4/Firestore transport, source activation or database seed.
  analytics_fixture="$PROJECT_ROOT/admin-ui/src/test/fixtures/analytics-reports.json"
  for analytics_source in ga4 firestore parents; do
    analytics_capability=$(node -p 'const d=require(process.argv[1]); d[process.argv[2]].items[0].capability_key' "$analytics_fixture" "$analytics_source")
    analytics_body=$(node -p 'JSON.stringify(require(process.argv[1])[process.argv[2]])' "$analytics_fixture" "$analytics_source")
    browser network route "**/api/v1/admin/operation/reports?*${analytics_capability}*" --body "$analytics_body" >/dev/null
  done
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/analytics" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Активные профили GA4") && document.body.innerText.includes("2 140")' >/dev/null
  assert_browser 'Boolean(document.querySelector(".professional-shell")) && !document.querySelector(".chat-page")' 'professional analytics did not render separately from chat'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/analytics-ga4-desktop.png" --full >/dev/null
  fi
  browser find role button click --name '7 дней' --exact >/dev/null
  browser wait --fn 'document.querySelector(".metric-grid")?.innerText.includes("860")' >/dev/null
  browser find role button click --name 'Firebase' >/dev/null
  browser wait --fn 'document.body.innerText.includes("Две ограниченные выборки")' >/dev/null
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/analytics-firebase-desktop.png" --full >/dev/null
  fi
  browser find role button click --name 'Parent API' >/dev/null
  browser wait --fn 'document.body.innerText.includes("Не подтверждает оплату")' >/dev/null
  browser select '.language-select' uz >/dev/null
  browser wait --fn 'document.documentElement.lang === "uz" && document.body.innerText.includes("To‘lovni tasdiqlamaydi")' >/dev/null
  browser set viewport 320 812 >/dev/null
  assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'professional analytics overflows on mobile'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/analytics-parents-uz-mobile.png" --full >/dev/null
  fi
  browser find role button click --name 'Menyuni ochish' >/dev/null
  browser select '.language-select' ru >/dev/null
  browser find role button click --name 'Открыть меню' >/dev/null
  browser set viewport 1440 1000 >/dev/null
  for analytics_source in ga4 firestore parents; do
    analytics_capability=$(node -p 'const d=require(process.argv[1]); d[process.argv[2]].items[0].capability_key' "$analytics_fixture" "$analytics_source")
    browser network unroute "**/api/v1/admin/operation/reports?*${analytics_capability}*" >/dev/null
  done
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/overview" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Обзор работы")' >/dev/null
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/professional-overview.png" --full >/dev/null
  fi
  if [[ "${AUDIT_PROFESSIONAL_UI_ONLY:-false}" == true ]]; then
    echo "Professional UI browser passed: GA4 windows, Firebase samples, Parent API, RU/UZ, desktop/mobile and accessibility; synthetic reports only."
    exit 0
  fi
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/" >/dev/null
  browser wait --fn 'Boolean(document.querySelector(".chat-page"))' >/dev/null
fi
audit_contact_lane() {
if [[ "${AUDIT_RETENTION_CONTACTS:-false}" == "true" ]]; then
  if [[ "${AUDIT_MANUAL_ACTION_CONTROLS:-false}" == "true" ]]; then
    browser open "http://127.0.0.1:${AUDIT_UI_PORT}/agents" >/dev/null
    browser wait --fn 'Array.from(document.querySelectorAll(".agent-list button")).some(item => item.textContent.includes("Удержание и лояльность"))' >/dev/null
    browser eval 'Array.from(document.querySelectorAll(".agent-list button")).find(item => item.textContent.includes("Удержание и лояльность")).click(); "selected"' >/dev/null
    browser wait --fn 'document.body.innerText.includes("Ручные действия Retention") && Array.from(document.querySelectorAll("button")).some(item => item.textContent.trim() === "Остановить sandbox" && !item.disabled)' >/dev/null
    assert_browser '!document.querySelector(".capability-list")?.textContent.includes("retention.contact.sandbox")' 'manual contact control became a scheduled analysis capability'
    assert_accessible
    browser find role button click --name 'Остановить sandbox' --exact >/dev/null
    browser click 'dialog[open] .dialog-actions button:last-child' >/dev/null
    browser wait --fn 'document.body.innerText.includes("Остановка включена") && Array.from(document.querySelectorAll("button")).some(item => item.textContent.trim() === "Снять остановку sandbox" && !item.disabled)' >/dev/null
    assert_accessible
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/manual-contact-control-stopped.png" --full >/dev/null
    fi
    browser select '.language-select' uz >/dev/null
    browser wait --fn 'document.body.innerText.includes("To‘xtatish yoqilgan")' >/dev/null
    browser set viewport 320 812 >/dev/null
    assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'manual control overflows on mobile'
    assert_accessible
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/manual-contact-control-uz-mobile.png" --full >/dev/null
    fi
    browser find role button click --name 'Menyuni ochish' >/dev/null
    browser select '.language-select' ru >/dev/null
    browser find role button click --name 'Открыть меню' >/dev/null
    browser set viewport 1440 1000 >/dev/null
    browser find role button click --name 'Снять остановку sandbox' --exact >/dev/null
    browser click 'dialog[open] .dialog-actions button:last-child' >/dev/null
    browser wait --fn 'document.body.innerText.includes("Остановка снята") && Array.from(document.querySelectorAll("button")).some(item => item.textContent.trim() === "Остановить sandbox" && !item.disabled)' >/dev/null
  fi
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/retention-agent" >/dev/null
  browser wait --load networkidle >/dev/null
  browser find label "Сообщение агенту" fill 'Проверь вымышленный контактный sandbox' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Контактный sandbox Retention")' >/dev/null
  if [[ "${AUDIT_CONTACT_TOOL_PROPOSALS:-false}" == "true" ]]; then
    browser wait --fn 'document.body.innerText.includes("Агент выбрал тестовое действие")' >/dev/null
    assert_browser '!document.querySelector("select[aria-label=\"Вымышленный получатель\"]")' 'native action was replaced by a manual selector'
  else
    browser select 'select[aria-label="Вымышленный получатель"]' sample_uz >/dev/null
  fi
  if [[ "${AUDIT_CONTACT_ADMISSION:-false}" == "true" ]]; then
    # The stale card was admitted before this explicit fake-admin stop. The real
    # backend must refuse its next preparation before reading the fictional target.
    browser eval '(async () => { const csrf=document.cookie.split("; ").find(x=>x.startsWith("mana_csrf="))?.slice(10); const r=await fetch("/api/v1/admin/operation/workspace/manual-action-controls/retention-agent/retention.contact.sandbox",{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":decodeURIComponent(csrf || "")},body:JSON.stringify({confirmed:true,enabled:true})}); if(!r.ok) throw Error("Fake stop failed"); return r.status; })()' >/dev/null
    browser find role button click --name "Подготовить тестовое сообщение" >/dev/null
    browser find role button click --name "Подтвердить подготовку" >/dev/null
    browser wait --fn 'document.body.innerText.includes("Подготовка контактных действий Retention остановлена.")' >/dev/null
    assert_browser 'Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()==="Подготовить тестовое сообщение")?.disabled' 'known refusal became immediate permission to redispatch'
    browser eval 'window.auditPreparationRequest=JSON.parse(sessionStorage.getItem(Object.keys(sessionStorage).find(k=>k.startsWith("mana:contact-preparation:v1:")))).request; true' >/dev/null
    browser eval '(async () => { const csrf=document.cookie.split("; ").find(x=>x.startsWith("mana_csrf="))?.slice(10); const r=await fetch("/api/v1/admin/operation/workspace/manual-action-controls/retention-agent/retention.contact.sandbox",{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":decodeURIComponent(csrf || "")},body:JSON.stringify({confirmed:true,enabled:false})}); if(!r.ok) throw Error("Fake rearm failed"); return r.status; })()' >/dev/null
    browser find role button click --name "Проверить подготовку" >/dev/null
    browser wait --fn 'Array.from(document.querySelectorAll("button")).some(b=>b.textContent.trim()==="Подготовить тестовое сообщение" && !b.disabled)' >/dev/null
    # Lose only the successful UI acknowledgement, after the real local fake
    # backend has recorded it. This never contacts a production host/provider.
    browser eval 'window.auditFetch=window.fetch.bind(window); window.fetch=async (...args)=>{ const response=await window.auditFetch(...args); if(String(args[0]).endsWith("/retention-contacts/prepare") && args[1]?.method==="POST" && response.ok){ if(JSON.stringify(JSON.parse(args[1].body))!==JSON.stringify(window.auditPreparationRequest)) throw Error("Preparation request changed"); throw Error("Synthetic lost preparation acknowledgement"); } return response; }; true' >/dev/null
  fi
  browser find role button click --name "Подготовить тестовое сообщение" >/dev/null
  browser find role button click --name "Подтвердить подготовку" >/dev/null
  browser wait --fn 'document.querySelector("blockquote[lang=uz]")?.textContent.includes("MANA: sozlashda")' >/dev/null
  if [[ "${AUDIT_CONTACT_ADMISSION:-false}" == "true" ]]; then
    browser wait --fn 'document.body.innerText.includes("Результат подготовки неизвестен. Новый запрос не отправляется.")' >/dev/null
    browser reload >/dev/null
    browser wait --fn 'document.body.innerText.includes("Результат подготовки неизвестен. Новый запрос не отправляется.") && Boolean(document.querySelector("blockquote[lang=uz]"))' >/dev/null
    assert_accessible
    browser find role button click --name "Проверить подготовку" >/dev/null
    browser wait --fn '!document.body.innerText.includes("Результат подготовки неизвестен. Новый запрос не отправляется.") && Boolean(document.querySelector("blockquote[lang=uz]"))' >/dev/null
    "$PROJECT_ROOT/.venv/bin/python" -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute("SELECT count(*) FROM operation_contact_preparations").fetchone()[0]==1; assert c.execute("SELECT count(*) FROM operation_contact_preparations WHERE status=?",("recorded",)).fetchone()[0]==1; print("Contact admission browser: one SQL preparation after known refusal/reconfirmation, lost acknowledgement and reload/status observation")' "$AUDIT_TMP_DIR/operation.db"
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/contact-preparation-recovered.png" --full >/dev/null
    fi
  fi
  assert_browser '!document.body.innerText.includes("Принято тестовым получателем")' 'preparation sent without approval'
  browser find label "Причина решения" fill 'Reviewed exact fictional Uzbek template' >/dev/null
  if [[ "${AUDIT_RETENTION_PEER_REVIEWS:-false}" == "true" ]]; then
    assert_browser 'Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "Отправить в sandbox")?.disabled' 'author can approve their own contact'
    contact_peer_user_id=$(browser eval 'document.querySelector(".chat-proposal-card section select")?.options[1]?.value' | tr -d '"')
    browser select '.chat-proposal-card section select' "$contact_peer_user_id" >/dev/null
    browser find role button click --name "Передать на согласование" >/dev/null
    browser find role button click --name "Подтвердить передачу" >/dev/null
    browser wait --fn 'Boolean(document.querySelector(".chat-proposal-card a[href^=\"/reviews?review=\"]"))' >/dev/null
    contact_review_path=$(browser eval 'document.querySelector(".chat-proposal-card a[href^=\"/reviews?review=\"]").getAttribute("href")' | tr -d '"')
    contact_owner_url=$(browser get url)
    assert_browser '!document.body.innerText.includes("Принято тестовым получателем")' 'sharing dispatched without a peer decision'
    browser find role button click --name "Выйти" >/dev/null
    browser open "http://127.0.0.1:${AUDIT_UI_PORT}${contact_review_path}" >/dev/null
    browser wait --fn 'Boolean(document.querySelector("input"))' >/dev/null
    login_browser 51456737
    browser wait --fn 'document.body.innerText.includes("Согласования Retention") && document.querySelector("blockquote[lang=uz]")?.textContent.includes("MANA: sozlashda")' >/dev/null
    assert_browser '!document.body.innerText.includes("Проверь вымышленный контактный sandbox")' 'peer received the private originating transcript'
    browser find label "Причина решения" fill 'Reviewed exact fictional Uzbek template as a different employee' >/dev/null
  fi
  browser find role button click --name "Отправить в sandbox" >/dev/null
  browser find role button click --name "Подтвердить тестовую отправку" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Принято тестовым получателем")' >/dev/null
  assert_accessible
  browser reload >/dev/null
  browser wait --fn 'document.body.innerText.includes("Принято тестовым получателем")' >/dev/null
  assert_browser '!document.querySelector(".chat-proposal-card textarea") && document.querySelector("blockquote[lang=uz]")?.textContent.includes("MANA: sozlashda")' 'settled contact intent was lost or remains executable'
  browser select '.language-select' uz >/dev/null
  browser wait --fn 'document.documentElement.lang === "uz" && document.body.innerText.includes("Test oluvchisi qabul qildi")' >/dev/null
  assert_browser 'document.querySelector("blockquote[lang=uz]")?.textContent.includes("MANA: sozlashda")' 'locale changed the exact contact message'
  browser set viewport 320 812 >/dev/null
  assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'contact sandbox overflows on mobile'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/retention-contact-mobile.png" --full >/dev/null
  fi
  browser set viewport 1440 1000 >/dev/null
  browser select '.language-select' ru >/dev/null
  if [[ "${AUDIT_RETENTION_PEER_REVIEWS:-false}" == "true" ]]; then
    browser find role button click --name "Выйти" >/dev/null
    browser open "$contact_owner_url" >/dev/null
    browser wait --fn 'Boolean(document.querySelector("input"))' >/dev/null
    login_browser 976835256
    browser wait --fn 'document.body.innerText.includes("Принято тестовым получателем")' >/dev/null
  fi
  if [[ "${AUDIT_CONTACT_TOOL_CONTINUATIONS:-false}" == "true" ]]; then
    browser select '.language-select' uz >/dev/null
    browser wait --fn 'document.documentElement.lang === "uz" && Array.from(document.querySelectorAll("button")).some(b => b.textContent.trim() === "Agent bilan davom etish")' >/dev/null
    browser find role button click --name "Agent bilan davom etish" >/dev/null
    browser wait --fn 'document.body.innerText.includes("Агент продолжил по SQL-результату")' >/dev/null
    assert_browser '!Array.from(document.querySelectorAll("button")).some(b => b.textContent.trim() === "Agent bilan davom etish")' 'consumed invocation remains executable'
    browser reload >/dev/null
    browser wait --fn 'document.body.innerText.includes("Агент продолжил по SQL-результату")' >/dev/null
    assert_browser 'document.querySelectorAll(".chat-turn").length === 2' 'continuation lost its originating chat or was duplicated'
    browser set viewport 320 812 >/dev/null
    browser eval 'Array.from(document.querySelectorAll(".chat-turn")).at(-1).scrollIntoView({block:"center", behavior:"instant"}); "show continued result"' >/dev/null
    assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'tool continuation overflows on mobile'
    assert_accessible
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/contact-tool-continuation-mobile.png" --full >/dev/null
    fi
    browser set viewport 1440 1000 >/dev/null
    browser select '.language-select' ru >/dev/null
  fi
fi
}
audit_contact_lane
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/growth-agent" >/dev/null
browser wait --load networkidle >/dev/null

if [[ "${AUDIT_AGENT_WORKSPACE:-false}" == "true" ]]; then
  assert_browser 'document.querySelector("select[aria-label=\"Режим работы\"]")?.value === "auto" && document.querySelectorAll(".chat-page button").length === 1' 'unified agent mode has extra controls or is not the default'
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator" >/dev/null
  browser wait --load networkidle >/dev/null
  # Observe only local stream URLs/statuses; never record cookies or provider payloads.
  browser eval '(() => { window.__workspaceStreams = []; const original = window.fetch.bind(window); window.fetch = async (...args) => { const response = await original(...args); if (String(args[0]).includes("/workspace/topics/") && String(args[0]).includes("/stream?")) window.__workspaceStreams.push({url:String(args[0]),status:response.status,type:response.headers.get("content-type")}); return response; }; return "stream observation installed"; })()' >/dev/null
  browser find label "Сообщение агенту" fill 'Проанализируй текущие данные MANA и подготовь план удержания' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.querySelector(".goal-waiting")?.textContent.includes("Уточните период анализа")' >/dev/null
  assert_browser 'location.pathname.includes("/operations-orchestrator/topic/")' 'agent redirected analysis out of the Orchestrator room'
  assert_browser 'document.querySelector(".goal-plan")?.textContent.includes("Проверить удержание") && document.querySelectorAll(".goal-details ol li").length >= 3' 'agent did not persist its plan and selected tool loop'
  assert_browser '!document.querySelector(".goal-details[open]")' 'agent exposes audit details by default'
  browser wait --fn 'window.__workspaceStreams?.some(item => item.status === 200 && item.type?.startsWith("text/event-stream")) && [...Array(sessionStorage.length).keys()].some(index => sessionStorage.key(index).startsWith("mana:workspace-cursor:v1:") && Number(sessionStorage.getItem(sessionStorage.key(index))) > 0)' >/dev/null
  browser eval '(async () => { const topic = location.pathname.split("/").at(-1); const goals = await (await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); if (goals.length !== 1 || goals[0].tools.length !== 3 || goals[0].status !== "waiting") throw new Error("Unexpected task before reconnection"); window.__progressBaseline = JSON.stringify({id:goals[0].goal_id,revision:goals[0].revision,tools:goals[0].tools.map(tool => tool.call_id),cost:goals[0].accounted_microusd,steps:goals[0].steps_used}); return "task checkpoint captured"; })()' >/dev/null
  if [[ "${AUDIT_SNAPSHOT_REPLACEMENT:-false}" == "true" ]]; then
    browser eval '(async () => { const topic = location.pathname.split("/").at(-1); const goals = await (await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); if (!goals[0].snapshot_replacement_enabled || goals[0].model_continuation !== null) throw new Error("Captured snapshot contract missing or private continuation exposed"); return "captured native snapshot contract; private payload withheld"; })()' >/dev/null
  fi
  # Leave the question unanswered until the bounded stream rotates. This must only
  # reconnect observation from the cursor, not repeat the question/tool/task.
  browser wait --fn 'window.__workspaceStreams?.some(item => Number(new URL(item.url, location.origin).searchParams.get("after")) > 0)' >/dev/null
  browser eval '(async () => { const topic = location.pathname.split("/").at(-1); const goals = await (await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); const current = JSON.stringify({id:goals[0].goal_id,revision:goals[0].revision,tools:goals[0].tools.map(tool => tool.call_id),cost:goals[0].accounted_microusd,steps:goals[0].steps_used}); if (goals.length !== 1 || goals[0].status !== "waiting" || current !== window.__progressBaseline) throw new Error("Observation restarted or mutated the task"); return "reconnected without task execution"; })()' >/dev/null
  assert_browser 'document.querySelectorAll(".goal-workspace").length === 1 && document.querySelector(".goal-waiting")?.textContent.includes("Уточните период анализа")' 'stream reconnection lost the inline question'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/agent-workspace-desktop.png" --full >/dev/null
  fi
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-waiting")?.textContent.includes("Уточните период анализа")' >/dev/null
  browser set viewport 320 812 >/dev/null
  assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'agent workspace overflows at 320 CSS pixels'
  assert_accessible
  browser eval '([...document.querySelectorAll(".goal-controls button")].find(button => button.textContent.trim() === "Последние 7 дней")).scrollIntoView({block:"center", behavior:"instant"}); "scrolled"' >/dev/null
  assert_browser '(() => { const button = [...document.querySelectorAll(".goal-controls button")].find(button => button.textContent.trim() === "Последние 7 дней").getBoundingClientRect(); const transcript = document.querySelector(".chat-transcript").getBoundingClientRect(); return button.top >= transcript.top && button.bottom <= transcript.bottom; })()' 'clarification choices are obscured by the composer'
  browser find role button click --name "Последние 7 дней" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  assert_browser 'document.querySelector(".goal-result")?.textContent.includes("Тестовый анализ")' 'reviewed agent result did not render'
  assert_browser 'document.querySelector(".goal-workspace")?.textContent.includes("browser-workspace-report")' 'result lost its saved evidence reference'
  browser eval '(async()=>{const topic=location.pathname.split("/").at(-1);const goal=(await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json())[0];const source=goal.evidence.find(item=>item.report_id==="browser-workspace-report");const item=[...document.querySelectorAll(".goal-details > ul > li")].find(item=>item.textContent.includes(source.report_id));const date=new Intl.DateTimeFormat("ru-RU",{dateStyle:"medium",timeStyle:"short"}).format(new Date(source.collected_at));if(!item?.textContent.includes(`Сбор данных: ${date}`)||item.textContent.includes("Подтверждён")||item.textContent.includes("Invalid Date")||item.closest("details").open)throw new Error("Goal source conflates collection/cache timing with confirmed observations");return "collection role matches saved API metadata in collapsed details";})()' >/dev/null
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/agent-workspace-mobile.png" --full >/dev/null
  fi
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  browser find label "Сообщение агенту" fill 'Объясни второй вывод завершённого анализа' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Продолжаю по сохранённому анализу")' >/dev/null
  assert_browser 'document.querySelectorAll(".goal-workspace").length === 1' 'follow-up started a duplicate analysis'
  browser reload >/dev/null
  browser wait --fn 'document.body.innerText.includes("Продолжаю по сохранённому анализу")' >/dev/null
  assert_accessible
  # Same-room explicit review uses the real owning Growth lifecycle on scoped fake facts.
  browser set viewport 1440 1000 >/dev/null
  browser find label "Сообщение агенту" fill 'Покажи предложения экспериментов' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.querySelector(".chat-approvals")?.textContent.includes("Тестовые эксперименты MANA") && Boolean(document.querySelector(".chat-proposal-card textarea"))' >/dev/null
  assert_browser 'document.querySelector(".chat-approvals")?.textContent.includes("Реальные пользователи и платежи не меняются")' 'sandbox action scope is not explicit'
  browser eval '(async () => { const topic = location.pathname.split("/").at(-1); const detail = await (await fetch(`/api/v1/admin/operation/chat/topics/${topic}`)).json(); const turn = detail.turns.at(-1); window.__actionPath = `/api/v1/admin/operation/workspace/topics/${topic}/messages/${turn.turn_id}/actions`; const page = await (await fetch(window.__actionPath)).json(); const item = page.items[0]; if (item.receipt || item.product !== "mana" || !item.synthetic) throw new Error("Invalid action preview"); const rejected = await fetch(`${window.__actionPath}/${item.proposal_id}/decision`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({request_id:crypto.randomUUID(), confirmed:true,approve:true,reason:"CSRF test",fingerprint:item.fingerprint})}); if (rejected.status !== 403) throw new Error("Action bypassed CSRF"); window.__actionPosts = 0; const original = window.fetch.bind(window); window.fetch = async (...args) => { const isDecision = String(args[0]).startsWith(window.__actionPath) && String(args[0]).endsWith("/decision"); if (isDecision) window.__actionPosts++; const response = await original(...args); if (isDecision && response.ok) throw new Error("Synthetic lost browser reply after domain commit"); return response; }; return "preview and CSRF verified"; })()' >/dev/null
  browser eval 'document.querySelector(".chat-proposal-card textarea").scrollIntoView({block:"center", behavior:"instant"}); "scrolled to decision"' >/dev/null
  browser find label "Причина решения" fill 'Reviewed fictional parent scenario and draft parameters' >/dev/null
  browser eval '([...document.querySelectorAll(".chat-proposal-card button")].find(button => button.textContent.trim() === "Создать в sandbox")).scrollIntoView({block:"center", behavior:"instant"}); "scrolled to confirmation"' >/dev/null
  assert_browser '(() => { const button = [...document.querySelectorAll(".chat-proposal-card button")].find(button => button.textContent.trim() === "Создать в sandbox").getBoundingClientRect(); const transcript = document.querySelector(".chat-transcript").getBoundingClientRect(); return button.top >= transcript.top && button.bottom <= transcript.bottom; })()' 'sandbox decision is hidden under the composer after scrolling'
  browser find role button click --name "Создать в sandbox" --exact >/dev/null
  assert_browser 'document.querySelector("dialog[open]")?.contains(document.activeElement)' 'action dialog lost focus'
  assert_accessible
  browser find role button click --name "Подтвердить создание" --exact >/dev/null
  browser wait --fn 'document.querySelector(".chat-proposal-card")?.textContent.includes("Влияние на конверсию не измерено")' >/dev/null
  browser eval '(async () => { const page = await (await fetch(window.__actionPath)).json(); const item = page.items[0]; if (window.__actionPosts !== 1 || item.execution_status !== "succeeded" || item.verification_status !== "verified" || item.receipt.state !== "resolved") throw new Error("Lost reply was retried or verification missing"); return "one verified execution observed"; })()' >/dev/null
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".chat-proposal-card")?.textContent.includes("Влияние на конверсию не измерено")' >/dev/null
  assert_browser '!document.querySelector(".chat-proposal-card textarea")' 'reload re-enabled a consumed action'
  browser find label "Сообщение агенту" fill 'Что получилось после согласования эксперимента?' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Sandbox-черновик создан и проверен. Конверсия не измерена.")' >/dev/null
  assert_browser 'document.querySelectorAll(".goal-workspace").length === 1' 'action follow-up launched an unintended Goal'
  browser set viewport 320 812 >/dev/null
  assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'action receipt overflows on mobile'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/workspace-action-receipt-mobile.png" --full >/dev/null
  fi
  # An explicit historical deliverable is not a silent fallback for current-data work.
  browser select 'select[aria-label="Режим работы"]' goal >/dev/null
  browser select 'select[aria-label="Область анализа"]' saved_snapshot >/dev/null
  browser find label "Сообщение агенту" fill 'Проанализируй только сохранённый исторический срез MANA, не сегодняшнее удержание' >/dev/null
  browser find role button click --name "Поставить цель" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-workspace")?.textContent.includes("Исторический срез · не текущее состояние") && document.querySelector(".goal-waiting")?.textContent.includes("Уточните период анализа")' >/dev/null
  assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'historical selector or task overflows on mobile'
  assert_accessible
  browser eval '([...document.querySelectorAll(".goal-controls button")].find(button => button.textContent.trim() === "Последние 7 дней")).scrollIntoView({block:"center", behavior:"instant"}); "scrolled"' >/dev/null
  browser find role button click --name "Последние 7 дней" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  browser eval '(async () => { const topic = location.pathname.split("/").at(-1); const goals = await (await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); if (goals.length !== 2 || goals[0].request.analysis_scope !== "saved_snapshot" || goals[0].status !== "completed" || goals[0].read_attempted || goals[0].approved_capability || goals[0].tools.some(tool => tool.call.name === "request_source_read")) throw new Error("Historical deliverable scope, completion or read safety failed"); return "explicit historical deliverable verified"; })()' >/dev/null
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-workspace")?.textContent.includes("Исторический срез · не текущее состояние") && document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  assert_browser '(() => { const transcript = document.querySelector(".chat-transcript"); const result = document.querySelector(".goal-result").getBoundingClientRect(); const bounds = transcript.getBoundingClientRect(); return transcript.scrollTop > 0 && result.top < bounds.bottom && result.bottom > bounds.top; })()' 'reloaded conversation hid the latest result above or below the viewport'
  assert_accessible
  if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
    browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/workspace-historical-mobile.png" --full >/dev/null
  fi
  browser select 'select[aria-label="Режим работы"]' goal >/dev/null
  browser select 'select[aria-label="Область анализа"]' saved_snapshot >/dev/null
  browser find label "Сообщение агенту" fill 'Прошлая рабочая цель: найди её и объясни сохранённый результат, проверив исходный отчёт' >/dev/null
  browser find role button click --name "Поставить цель" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-workspace h2")?.textContent.includes("Прошлая рабочая цель") && document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  browser eval '(async () => { const topic=location.pathname.split("/").at(-1); const goals=await (await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); const goal=goals[0]; if (goals.length!==3 || JSON.stringify(goal.tools.map(tool=>tool.call.name))!==JSON.stringify(["find_saved_tasks","read_saved_task","read_saved_report"]) || goal.read_attempted || goal.approved_capability || goal.evidence[0]?.report_id!=="browser-workspace-report") throw new Error("Private SQL recall did not revalidate source separately"); return "scoped saved-task recall verified"; })()' >/dev/null
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-workspace h2")?.textContent.includes("Прошлая рабочая цель") && document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
  assert_accessible
  # Existing topics beyond the old 100-turn boundary remain readable and usable.
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator/topic/00000000-0000-4000-8000-000000000110" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Исторический ответ 110")' >/dev/null
  assert_browser 'document.querySelectorAll(".chat-turn").length === 20' 'long topic loaded an unbounded transcript'
  browser eval '(() => { window.__historyPosts = 0; const original = window.fetch.bind(window); window.fetch = (...args) => { if (args[1]?.method === "POST") window.__historyPosts++; return original(...args); }; const transcript = document.querySelector(".chat-transcript"); transcript.scrollTop = 0; transcript.dispatchEvent(new Event("scroll")); return "read earlier"; })()' >/dev/null
  browser wait --fn 'document.querySelectorAll(".chat-turn").length === 40' >/dev/null
  assert_browser '(() => { const transcript = document.querySelector(".chat-transcript"); return transcript.scrollTop > 0 && transcript.scrollHeight - transcript.clientHeight - transcript.scrollTop > 100; })()' 'older-page prepend jumped to the newest reply'
  for _ in $(seq 1 4); do
    browser eval '(() => { const transcript = document.querySelector(".chat-transcript"); transcript.scrollTop = 0; transcript.dispatchEvent(new Event("scroll")); return "earlier page"; })()' >/dev/null
    browser wait --load networkidle >/dev/null
  done
  browser wait --fn 'document.body.innerText.includes("Исторический ответ 1")' >/dev/null
  assert_browser 'document.querySelectorAll(".chat-turn").length === 110 && window.__historyPosts === 0' 'history omitted messages or initiated model/source work'
  assert_accessible
  browser find label "Сообщение агенту" fill 'Проверь первое условие длинной темы' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.body.innerText.includes("Первое условие сохранено полностью")' >/dev/null
  assert_browser 'document.querySelectorAll(".chat-turn").length === 111' 'head refresh left a gap or duplicate across old-page boundaries'
  browser reload >/dev/null
  browser wait --fn 'document.body.innerText.includes("Первое условие сохранено полностью")' >/dev/null
  assert_browser 'document.querySelectorAll(".chat-turn").length === 20' 'reload lost the newest result or eagerly loaded the full transcript'
  assert_accessible
  if [[ "${AUDIT_CHAT_STREAMING:-false}" == "true" ]]; then
    # Native contact selection is deliberately nonstreamed; test the independent
    # ordinary-answer stream in a room where that tool cannot be admitted.
    browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/growth-agent" >/dev/null
    browser wait --load networkidle >/dev/null
    browser eval '(() => { window.__chatPosts=0; window.__chatFrames=[]; const original=window.fetch.bind(window); window.fetch=async (...args)=>{ if(args[1]?.method==="POST"&&String(args[0]).includes("/messages")) window.__chatPosts++; const response=await original(...args); if(String(args[0]).includes("/stream?")) { const clone=response.clone(); (async()=>{const reader=clone.body.getReader();const decoder=new TextDecoder();while(true){const part=await reader.read();if(part.done)break;window.__chatFrames.push(decoder.decode(part.value,{stream:true}));}})(); } return response; }; return "observe chat only"; })()' >/dev/null
    browser find label "Сообщение агенту" fill 'Проверь поток ответа без новой цели' >/dev/null
    browser find role button click --name "Отправить сообщение" >/dev/null
    browser wait --fn 'document.body.innerText.includes("Тестовый поток: начало 🧒") && Boolean(document.querySelector("button[aria-label=\"Остановить ответ\"]"))' >/dev/null
    assert_browser '!document.body.innerText.includes("Тестовый поток завершён и проверен.") && !document.querySelector(".goal-workspace")' 'preview was promoted to a result or started a task'
    browser wait --fn 'document.body.innerText.includes("Тестовый поток завершён и проверен.")' >/dev/null
    assert_browser 'window.__chatPosts===1 && window.__chatFrames.join("").includes("event: chat_text")' 'chat token display polled instead of consuming SSE or resubmitted the message'
    assert_accessible
    browser reload >/dev/null
    browser wait --fn 'document.body.innerText.includes("Тестовый поток завершён и проверен.")' >/dev/null
    assert_browser '!document.querySelector(".goal-workspace")' 'reply reload created an unintended Goal'
  fi
  # Original Goal-only constraints beyond the 100-result page reach the model
  # and durable successor, not just a recent transcript message or a prose summary.
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator/topic/00000000-0000-4000-8000-000000000105" >/dev/null
  browser wait --load networkidle >/dev/null
  browser find label "Сообщение агенту" fill 'Продолжи анализ с условиями из первой архивной задачи' >/dev/null
  browser find role button click --name "Отправить сообщение" >/dev/null
  browser wait --fn 'document.querySelector(".goal-waiting")?.textContent.includes("Уточните период анализа")' >/dev/null
  browser eval '([...document.querySelectorAll(".goal-controls button")].find(button => button.textContent.trim() === "Последние 7 дней")).scrollIntoView({block:"center", behavior:"instant"}); "scrolled"' >/dev/null
  browser find role button click --name "Последние 7 дней" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-result")?.textContent.includes("Исходные условия из первой задачи сохранены")' >/dev/null
  assert_browser 'document.querySelector(".goal-result")?.textContent.includes("бюджет $5") && document.querySelector(".goal-result")?.textContent.includes("Не контактируй")' 'old Goal conditions were lost before the model/review'
  assert_accessible
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-result")?.textContent.includes("Исходные условия из первой задачи сохранены")' >/dev/null
  browser eval '(async()=>{ const topic=location.pathname.split("/").at(-1); const goals=await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); if(goals.length!==100 || goals[0].status!=="completed" || goals[0].read_attempted || goals[0].approved_capability || goals[0].evidence.length!==1) throw new Error("Archive continuation inherited authority or expanded public history"); return "all original conditions; only scoped saved evidence"; })()' >/dev/null
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator" >/dev/null
  browser wait --load networkidle >/dev/null
  paged_prompt='Прочитай полный сохранённый отчёт вместе с концом'
  if [[ "${AUDIT_MODEL_CONTINUATION:-false}" == "true" ]]; then
    paged_prompt+=' с ошибкой страницы'
  fi
  browser find label "Сообщение агенту" fill "$paged_prompt" >/dev/null
  browser find role button click --name "Отправить сообщение" --exact >/dev/null
  browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов") && document.querySelector(".goal-result")?.textContent.includes("EXACT PAGED FOOTER")' >/dev/null
  browser eval '(async()=>{ const topic=location.pathname.split("/").at(-1); const goals=await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); const goal=goals[0]; const pages=goal.tools.filter(t=>t.call.name==="read_saved_report_page"); const replan=goal.request.objective.includes("с ошибкой страницы"); if(goals.length!==1 || goal.status!=="completed" || goal.read_attempted || goal.approved_capability || goal.evidence[0].summary.length<=5000 || !goal.evidence[0].summary.endsWith("EXACT PAGED FOOTER") || goal.evidence[0].shortened || goal.evidence[0].report_read_progress!==null || pages.filter(t=>t.status==="completed").length!==3 || pages.length!==(replan?4:3) || goal.model_recoveries!==(replan?1:0)) throw new Error("Paged source was clipped, partially accepted or exposed private receipts"); if(replan && (!goal.events.some(e=>e.message.includes("Исправляю запрос")) || pages.filter(t=>t.status==="denied").length!==1)) throw new Error("Local correction was not recorded truthfully"); sessionStorage.setItem("paged-audit-baseline",JSON.stringify({id:goal.goal_id,revision:goal.revision,steps:goal.steps_used,cost:goal.accounted_microusd})); return "full source and bounded correction reach review"; })()' >/dev/null
  assert_accessible
  browser reload >/dev/null
  browser wait --fn 'document.querySelector(".goal-result")?.textContent.includes("EXACT PAGED FOOTER")' >/dev/null
  browser eval '(async()=>{ const topic=location.pathname.split("/").at(-1); const goals=await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json(); const goal=goals[0]; if(JSON.stringify({id:goal.goal_id,revision:goal.revision,steps:goal.steps_used,cost:goal.accounted_microusd})!==sessionStorage.getItem("paged-audit-baseline")) throw new Error("Reload redispatched the paged task"); if(goal.evidence[0].shortened || !goal.evidence[0].summary.endsWith("EXACT PAGED FOOTER")) throw new Error("Reload lost complete evidence"); return "paged checkpoint restored"; })()' >/dev/null
  if [[ "${AUDIT_LIMIT_EXTENSIONS:-false}" == "true" ]]; then
    # Normal authenticated browser requests; only the isolated fake model runs.
    browser eval '(async()=>{ const csrf=decodeURIComponent(document.cookie.split("; ").find(x=>x.startsWith("mana_csrf=")).split("=").slice(1).join("=")); const headers={"Content-Type":"application/json","X-CSRF-Token":csrf}; const topicReply=await fetch("/api/v1/admin/operation/chat/topics",{method:"POST",headers,body:JSON.stringify({agent_id:"operations-orchestrator",product:"mana",title:"Продолжение длинной цели"})}); if(!topicReply.ok)throw new Error("Topic creation refused"); const topic=await topicReply.json(); const request={request_id:crypto.randomUUID(),objective:"Проверка продолжения той же цели без новых источников",constraints:"Не читай источники, не изменяй данные, сохрани исходную задачу.",max_steps:3,budget_microusd:500000,execution_mode:"agent"}; const created=await fetch(`/api/v1/admin/operation/goals/topics/${topic.topic_id}`,{method:"POST",headers,body:JSON.stringify(request)}); if(!created.ok)throw new Error("Goal creation refused"); window.__limitTopic=topic.topic_id; sessionStorage.setItem("limit-original-request",JSON.stringify(request)); return "bounded Goal created"; })()' >/dev/null
    limit_topic=$(browser eval 'window.__limitTopic' | tr -d '"')
    browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator/topic/${limit_topic}" >/dev/null
    browser wait --fn 'document.querySelector(".goal-waiting")?.textContent.includes("Лимит шагов исчерпан")' >/dev/null
    assert_browser '!document.querySelector(".goal-limit-form")' 'limit form opened without a user choice'
    browser eval '(async()=>{const topic=location.pathname.split("/").at(-1); const goal=(await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json())[0]; if(goal.limit_stop!=="steps" || goal.limit_grants.length || goal.unsettled_microusd || goal.steps_used!==3)throw new Error("No tracked safe limit stop"); const denied=await fetch(`/api/v1/admin/operation/goals/${goal.goal_id}/commands`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:crypto.randomUUID(),command:"extend_limits",expected_revision:goal.revision,max_steps:9,budget_microusd:500000})}); if(denied.status!==403)throw new Error("Extension bypassed CSRF"); window.__extensionPosts=0; const original=window.fetch.bind(window); window.fetch=async(...args)=>{const extension=args[1]?.method==="POST" && String(args[0]).endsWith("/commands") && JSON.parse(args[1].body).command==="extend_limits"; if(extension)window.__extensionPosts++; const reply=await original(...args); if(extension && reply.ok)throw new Error("Synthetic lost extension reply after commit"); return reply; }; return "tracked stop, CSRF and single-dispatch observation ready";})()' >/dev/null
    browser find role button click --name "Продолжить эту цель" --exact >/dev/null
    browser set viewport 320 812 >/dev/null
    assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'limit form overflows on mobile'
    assert_accessible
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/goal-limit-form-mobile.png" --full >/dev/null
    fi
    browser eval '([...document.querySelectorAll("button")].find(button=>button.textContent.trim()==="Подтвердить и продолжить")).scrollIntoView({block:"center",behavior:"instant"}); "scrolled"' >/dev/null
    browser find role button click --name "Подтвердить и продолжить" --exact >/dev/null
    browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
    browser eval '(async()=>{const topic=location.pathname.split("/").at(-1);const goals=await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json();const goal=goals[0];const original=JSON.parse(sessionStorage.getItem("limit-original-request"));if(goals.length!==1 || goal.status!=="completed" || goal.limit_grants.length!==1 || goal.request.request_id!==original.request_id || goal.request.objective!==original.objective || goal.request.constraints!==original.constraints || goal.request.max_steps!==3 || goal.limit_grants[0].max_steps!==9 || goal.read_attempted || goal.approved_capability || goal.unsettled_microusd || window.__extensionPosts!==1)throw new Error("Extension narrowed task, reset costs, granted a read or was redispatched");sessionStorage.setItem("limit-completed-baseline",JSON.stringify({id:goal.goal_id,revision:goal.revision,cost:goal.accounted_microusd,steps:goal.steps_used,grants:goal.limit_grants}));return "same Goal completed after one confirmed extension";})()' >/dev/null
    browser reload >/dev/null
    browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов")' >/dev/null
    browser eval '(async()=>{const topic=location.pathname.split("/").at(-1);const goal=(await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json())[0];if(JSON.stringify({id:goal.goal_id,revision:goal.revision,cost:goal.accounted_microusd,steps:goal.steps_used,grants:goal.limit_grants})!==sessionStorage.getItem("limit-completed-baseline"))throw new Error("Reload changed the continued Goal");return "grant and result restored without another call";})()' >/dev/null
    assert_accessible
    echo "Goal limit browser flow passed: exact human grant, same objective, mobile form, CSRF, lost reply without redispatch and result reload"
  fi
  if [[ "${AUDIT_REPORT_DISCOVERY:-false}" == true ]]; then
    browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator" >/dev/null
    browser find label "Сообщение агенту" fill 'Найди отчёт в длинном каталоге и прочитай весь текст' >/dev/null
    browser find role button click --name "Отправить сообщение" --exact >/dev/null
    browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Анализ готов") && document.querySelector(".goal-result")?.textContent.includes("EXACT CATALOG FOOTER")' >/dev/null
    browser eval '(async()=>{const topic=location.pathname.split("/").at(-1);const goal=(await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json())[0]; if(!goal.report_discovery_enabled || goal.evidence.length!==1 || !goal.evidence[0].summary.endsWith("EXACT CATALOG FOOTER") || goal.evidence[0].shortened || goal.tools.filter(t=>t.call.name==="find_saved_reports").length!==3 || goal.read_attempted || goal.approved_capability || goal.requested_capability || goal.unsettled_microusd) throw new Error("Discovery lost full text or inherited read authority"); sessionStorage.setItem("catalog-result",JSON.stringify({id:goal.goal_id,revision:goal.revision,steps:goal.steps_used,cost:goal.accounted_microusd})); return "three local catalog pages; complete report and review; no source read";})()' >/dev/null
    browser reload >/dev/null
    browser wait --fn 'document.querySelector(".goal-result")?.textContent.includes("EXACT CATALOG FOOTER")' >/dev/null
    browser eval '(async()=>{const topic=location.pathname.split("/").at(-1);const goal=(await(await fetch(`/api/v1/admin/operation/goals/topics/${topic}`)).json())[0]; if(JSON.stringify({id:goal.goal_id,revision:goal.revision,steps:goal.steps_used,cost:goal.accounted_microusd})!==sessionStorage.getItem("catalog-result")) throw new Error("Observation redispatched discovery"); return "result restored without another task/model/source call";})()' >/dev/null
    assert_accessible
    if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
      browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/catalog-reviewed-result.png" --full >/dev/null
    fi
    echo "Catalog browser flow passed: three bounded SQL pages, complete saved text, reviewed result and reload without redispatch"
  fi
  browser eval 'document.querySelector(".session-box button").click(); "logged out"' >/dev/null
  browser wait --fn 'document.body.innerText.includes("Вход в MANA")' >/dev/null
  login_browser 51456737
  assert_browser 'document.querySelectorAll(".topic-link").length === 0' 'another administrator sees the private agent workspace'
  echo "Agent workspace browser E2E passed: handoff, durable stream/reconnection, scoped tools, inline question, reviewed result, continuation, scoped sandbox decision, lost reply without redispatch, receipt reload, explicit historical deliverable, 110-turn transcript paging, 105-Goal full-condition handoff/review/reload, full paged report/review/reload, owner isolation, CSRF and accessibility"
  exit 0
fi
assert_browser 'document.querySelectorAll(".chat-page button:not(.composer-mode button)").length === 1 && document.querySelectorAll(".composer-mode button").length === 2' 'new chat has extra action buttons outside the chat/goal mode selector'
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
assert_browser 'document.querySelectorAll(".chat-decision-buttons > button").length === 0 && document.body.innerText.includes("Согласование в этом чате недоступно")' 'unverified historical proposals allow a chat decision'
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
browser wait --fn 'document.querySelector(".link-button") !== null' >/dev/null
browser click '.link-button' >/dev/null
browser wait --fn 'document.body.innerText.includes("action_verified")' >/dev/null
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

browser set viewport 1440 1000 >/dev/null
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/retention-agent" >/dev/null
browser wait --load networkidle >/dev/null
browser find label "Сообщение агенту" fill 'Проверь родителей MANA' >/dev/null
browser find role button click --name "Отправить сообщение" >/dev/null
browser wait --fn 'document.body.innerText.includes("Это тестовый ответ")' >/dev/null
assert_browser 'document.querySelector(".chat-action-suggestion")?.textContent.includes("Firebase не вызывается")' 'parent confirmation lost source limits'
assert_browser 'document.querySelector(".chat-action-suggestion")?.textContent.includes("Подтверждение не гарантирует сбор")' 'parent confirmation implies a guaranteed read'
assert_browser 'document.querySelector(".chat-action-suggestion")?.textContent.includes("соответствие источника приложению")' 'parent confirmation omits source ownership validation'
browser eval "(async () => { const id = location.pathname.split('/').at(-1); const response = await fetch('/api/v1/admin/operation/chat/topics/' + id); const detail = await response.json(); const turn = detail.turns.at(-1); const policy = turn.read_confirmation; if (turn.analysis_requested || policy?.kind !== 'mana_parents' || policy.product !== 'mana' || policy.capability_key !== 'retention.parents.analyze' || policy.confirmation_required !== true || policy.minimum_interval_seconds !== ${AUDIT_PARENT_MIN_INTERVAL_SECONDS:-21600} || JSON.stringify(policy.admission_checks) !== JSON.stringify(['access','product_scope','cooldown','budget'])) throw new Error('Server read conditions are missing, wrong or treated as execution'); return 'Read conditions verified'; })()" >/dev/null
assert_browser 'document.querySelector(".chat-evidence-warning")?.textContent.includes("устаревшие данные")' 'historical source warning is hidden or missing'
assert_browser '!document.querySelector(".chat-evidence-warning")?.closest("details") && !document.querySelector(".chat-message-details[open]")' 'historical source warning requires expanding details'
assert_browser 'document.querySelector(".chat-sources a")?.textContent.includes("Сбор данных:") && document.querySelector(".chat-sources a")?.textContent.includes("Устаревшие") && !document.querySelector(".chat-sources a")?.textContent.includes("Данные:")' 'chat source conflates data collection with an observation date'
assert_browser '!document.querySelector("dialog[open]") && document.querySelectorAll(".chat-action-suggestion").length === 1' 'chat requires duplicate confirmation'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/parent-consent-stale-desktop.png" --full >/dev/null
fi
browser set viewport 320 812 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'evidence warning overflows on mobile'
assert_accessible
browser eval 'document.querySelector(".chat-action-suggestion button").scrollIntoView({block: "center", behavior: "instant"}); "scrolled"' >/dev/null
assert_browser '(() => { const button = document.querySelector(".chat-action-suggestion button").getBoundingClientRect(); const transcript = document.querySelector(".chat-transcript").getBoundingClientRect(); return button.top >= transcript.top && button.bottom <= transcript.bottom; })()' 'mobile confirmation is obscured or cannot be reached'
browser eval 'document.querySelector(".chat-evidence-warning").scrollIntoView({block: "center", behavior: "instant"}); "scrolled"' >/dev/null
assert_browser '(() => { const warning = document.querySelector(".chat-evidence-warning").getBoundingClientRect(); const transcript = document.querySelector(".chat-transcript").getBoundingClientRect(); return warning.top >= transcript.top && warning.bottom <= transcript.bottom && !document.querySelector(".chat-message-details[open]"); })()' 'mobile source warning is obscured or requires expanding details'
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/parent-consent-stale-mobile.png" --full >/dev/null
fi
browser set viewport 1440 1000 >/dev/null
browser find role button click --name "Подтвердить сбор данных" >/dev/null
browser wait --fn 'document.body.innerText.includes("Только в этой выборке")' >/dev/null
assert_browser '!document.querySelector(".chat-action-suggestion")' 'completed request left a stale action suggestion'
assert_accessible
browser reload >/dev/null
browser wait --fn 'document.body.innerText.includes("Только в этой выборке")' >/dev/null
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/parents-mana-chat.png" --full >/dev/null
fi
browser set viewport 320 812 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'parent chat overflows on mobile'
assert_accessible
browser set viewport 1440 1000 >/dev/null

browser open "http://127.0.0.1:${AUDIT_UI_PORT}/chat/operations-orchestrator" >/dev/null
browser wait --load networkidle >/dev/null
browser find role button click --name "Цель" --exact >/dev/null
browser find label "Сообщение агенту" fill 'Проанализируй удержание пользователей MANA и подготовь проверенный план' >/dev/null
browser find role button click --name "Поставить цель" >/dev/null
browser wait --fn 'document.querySelector(".goal-workspace")?.textContent.includes("Уточните период анализа")' >/dev/null
assert_browser 'document.querySelector(".goal-plan")?.textContent.includes("Проверить удержание")' 'goal has no durable public plan'
assert_browser 'document.querySelector(".goal-result")?.textContent.includes("Тестовый анализ")' 'goal partial result was lost'
assert_browser '!document.querySelector(".goal-details[open]")' 'goal audit detail is not collapsed by default'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/goals-desktop.png" --full >/dev/null
fi
browser reload >/dev/null
browser wait --fn 'document.querySelector(".goal-workspace")?.textContent.includes("Уточните период анализа")' >/dev/null
assert_browser 'document.querySelector(".goal-workspace h2")?.textContent.includes("удержание пользователей MANA")' 'goal did not survive reload'
browser set viewport 320 812 >/dev/null
assert_browser 'document.documentElement.scrollWidth <= innerWidth' 'goal workspace overflows on mobile'
assert_accessible
if [[ -n "${AUDIT_SCREENSHOT_DIRECTORY:-}" ]]; then
  browser screenshot "$AUDIT_SCREENSHOT_DIRECTORY/goals-mobile.png" --full >/dev/null
fi
browser find label "Уточнение цели" fill 'За последние семь дней. Не объединяй родителей и детей.' >/dev/null
browser find role button click --name "Уточнить цель" --exact >/dev/null
browser wait --fn 'document.querySelector(".goal-waiting")?.textContent.includes("цель не закрыта")' >/dev/null
assert_browser '!document.querySelector(".goal-workspace")?.textContent.includes("Анализ готов")' 'goal closed on stale evidence'
browser eval 'document.querySelector(".goal-details summary").click(); "opened"' >/dev/null
browser find role button click --name "Отменить цель" >/dev/null
browser wait --fn 'document.querySelector(".goal-heading")?.textContent.includes("Отменена")' >/dev/null
assert_browser '!document.querySelector(".goal-steer")' 'cancelled goal remained writable'
browser set viewport 1440 1000 >/dev/null


for route in agents users; do
  browser open "http://127.0.0.1:${AUDIT_UI_PORT}/${route}" >/dev/null
  browser wait --load networkidle >/dev/null
  assert_accessible
done

browser eval '(() => { const button = document.querySelector(".session-box button"); if (!(button instanceof HTMLButtonElement)) throw new Error("logout button missing"); button.click(); return "clicked"; })()' >/dev/null
browser open "http://127.0.0.1:${AUDIT_UI_PORT}/runs" >/dev/null
browser wait --load networkidle >/dev/null
assert_browser 'document.body.innerText.includes("Вход в MANA")' 'protected route did not return to login after logout'

echo "Browser E2E passed: RU/UZ persistence, unchanged drafts, private chats, durable Goals, scope/freshness guards, mobile accessibility, approvals and logout"
