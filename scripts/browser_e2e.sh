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
MANAKIDS_PARENT_SOURCE_ENABLED=false \
MANAKIDS_PARENT_MIN_INTERVAL_SECONDS="${AUDIT_PARENT_MIN_INTERVAL_SECONDS:-21600}" \
AUDIO_MODERATION_ENABLED=false \
OPERATION_DRY_RUN=false \
OPERATION_ALLOW_SELF_APPROVAL=false \
OPERATION_SCHEDULER_ENABLED=false \
OPERATION_GOALS_WORKER_ENABLED=false \
OPERATION_MODEL_SELECTION_ENABLED=true \
OPERATION_AGENT_WORKSPACE_ENABLED="${AUDIT_AGENT_WORKSPACE:-false}" \
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
assert_browser '!document.querySelector(".topic-options, .chat-starters, .chat-tools-links")' 'manual setup controls leaked into the simple chat'
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
  browser eval 'document.querySelector(".session-box button").click(); "logged out"' >/dev/null
  browser wait --fn 'document.body.innerText.includes("Вход в MANA")' >/dev/null
  login_browser 51456737
  assert_browser 'document.querySelectorAll(".topic-link").length === 0' 'another administrator sees the private agent workspace'
  echo "Agent workspace browser E2E passed: handoff, durable stream/reconnection, scoped tools, inline question, reviewed result, continuation, scoped sandbox decision, lost reply without redispatch, receipt reload, explicit historical deliverable, owner isolation, CSRF and accessibility"
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

echo "Browser E2E passed: private chats, durable Goals, scope/freshness guards, mobile accessibility, approvals and logout"
