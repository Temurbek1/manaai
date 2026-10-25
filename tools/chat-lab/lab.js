"use strict";
const $ = (id) => document.getElementById(id);
const prefix = "/api/v1/mana-ai";
const csrf = document.querySelector('meta[name="lab-csrf"]').content;
let bootstrap,
  state,
  pending = null,
  pendingText = null,
  busy = false,
  rendered = "";
const errors = {
  daily_token_budget_exceeded: "Дневной лимит чата исчерпан.",
  safety_server_token_budget_exceeded: "Дневной лимит Child-Safety исчерпан.",
  previous_request_unresolved:
    "Предыдущий запрос ещё не завершён. Новую генерацию не запускаем.",
  lab_session_required: "Сессия сервера изменилась. Обновите страницу.",
  lab_csrf_failed: "Сессия сервера изменилась. Обновите страницу.",
};
class LabApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-Lab-CSRF": csrf,
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const code = body.detail?.code || body.detail || `HTTP ${response.status}`;
    throw new LabApiError(errors[code] || String(code), response.status);
  }
  return body;
}
function showError(error) {
  $("error").textContent =
    error.message || "Связь потеряна. Запрос автоматически не повторяется.";
  $("error").hidden = false;
}
function controls(disabled) {
  busy = disabled;
  $("send").disabled = disabled;
  document
    .querySelectorAll(".scenarios button")
    .forEach((button) => (button.disabled = disabled));
}
function paragraph(parent, text) {
  const p = document.createElement("p");
  p.textContent = text;
  parent.append(p);
}
function draw() {
  const history = state.history;
  const fingerprint = JSON.stringify(history.messages);
  if (fingerprint !== rendered && history.messages.length) {
    const atBottom =
      $("messages").scrollHeight -
        $("messages").scrollTop -
        $("messages").clientHeight <
      100;
    $("messages").replaceChildren();
    history.messages.forEach((message) => {
      const row = document.createElement("article");
      row.className = `message ${message.role}`;
      if (message.role === "assistant") {
        const mark = document.createElement("span");
        mark.className = "mini-avatar";
        mark.textContent = "M";
        mark.setAttribute("aria-hidden", "true");
        row.append(mark);
      }
      const body = document.createElement("div");
      body.className = "body";
      body.textContent = message.content;
      const time = document.createElement("time");
      time.className = "stamp";
      time.dateTime = message.created_at;
      time.textContent = new Date(message.created_at).toLocaleTimeString(
        "ru-RU",
        { hour: "2-digit", minute: "2-digit" },
      );
      body.append(time);
      row.append(body);
      $("messages").append(row);
    });
    if (atBottom || pending || rendered === "")
      $("messages").scrollTop = $("messages").scrollHeight;
  }
  rendered = fingerprint;
  $("reply-label").textContent = history.active_question
    ? "Ответ будет привязан к вопросу агента"
    : history.active_confirmation
      ? "Подтверждение напоминания"
      : "";
  const quota = history.quota;
  $("usage").textContent =
    `${state.mode === "simulation" ? "Симуляция токенов" : "Токены чата"}: ${quota.used_tokens} / ${quota.daily_limit} · Child-Safety: ${state.safety_budget.server_used_tokens} / ${state.safety_budget.server_daily_limit}`;
  $("budget").textContent =
    `Чат: ${quota.used_tokens} использовано, ${quota.reserved_tokens} удержано. Child-Safety: ${state.safety_budget.server_used_tokens} использовано, ${state.safety_budget.server_reserved_tokens} удержано.`;
  $("jobs").replaceChildren();
  state.assessments.assessments
    .slice(-6)
    .forEach((job) =>
      paragraph(
        $("jobs"),
        `Child-Safety · ${job.kind} · ${job.status}${job.error_code ? " · " + job.error_code : ""}`,
      ),
    );
  $("offers").replaceChildren();
  $("source-jobs").replaceChildren();
  (state.source_dispatches || [])
    .slice(-6)
    .forEach((item) =>
      paragraph(
        $("source-jobs"),
        `Источник → Child-Safety · ${item.phase}${item.reason ? " · " + item.reason : ""}`,
      ),
    );
  state.conversions.proposals
    .slice(-4)
    .forEach((offer) =>
      paragraph(
        $("offers"),
        `Конверсия · ${offer.status}${offer.closed_reason ? " · " + offer.closed_reason : ""}`,
      ),
    );
  $("raw-state").textContent = JSON.stringify(state, null, 2);
}
async function refresh() {
  state = await api("/lab/state");
  draw();
}
async function observePending() {
  if (!pending) return;
  const result = await api(
    `${prefix}/parent-touch/messages/${pending}?parent_id=${bootstrap.parent_id}`,
  );
  if (["completed", "failed", "unknown"].includes(result.phase)) {
    if (result.phase === "completed") $("error").hidden = true;
    if (
      result.phase === "completed" &&
      $("message").value.trim() === pendingText
    )
      $("message").value = "";
    pending = null;
    pendingText = null;
    sessionStorage.removeItem("mana-lab-pending");
    controls(false);
    $("status").textContent = "";
    if (result.phase !== "completed")
      showError(
        new Error(
          errors[result.error_code] ||
            result.error_code ||
            "Ответ не подтверждён. Автоматического повтора нет.",
        ),
      );
  } else {
    $("status").textContent =
      result.phase === "awaiting_review"
        ? "Child-Safety изучает сообщение…"
        : "Parent-Touch готовит ответ…";
  }
}
function clearPending() {
  pending = null;
  pendingText = null;
  sessionStorage.removeItem("mana-lab-pending");
  controls(false);
}
async function tick() {
  try {
    if (document.visibilityState === "visible") {
      await refresh();
      await observePending();
    }
  } catch (error) {
    showError(error);
  } finally {
    setTimeout(tick, 1500);
  }
}
$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (busy || !text || !bootstrap) return;
  const id = crypto.randomUUID();
  const body = {
    parent_id: bootstrap.parent_id,
    request_id: id,
    message: text,
  };
  if (state?.history.active_question)
    body.reply_to_question_id = state.history.active_question.question_id;
  else if (state?.history.active_confirmation)
    body.reply_to_confirmation_id =
      state.history.active_confirmation.confirmation_id;
  controls(true);
  $("error").hidden = true;
  $("status").textContent = "Отправляем…";
  pending = id;
  pendingText = text;
  sessionStorage.setItem("mana-lab-pending", id);
  try {
    await api(prefix + "/parent-touch/messages", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if ($("message").value.trim() === pendingText) $("message").value = "";
    await refresh();
    await observePending();
  } catch (error) {
    showError(error);
    $("status").textContent =
      "Проверяем статус отправленного UUID; POST автоматически не повторяется.";
    // Keep the exact admitted identity after transport loss. Observation alone
    // never reissues this message or creates a replacement nonce.
    try {
      await observePending();
    } catch (observationError) {
      if (
        error instanceof LabApiError &&
        [400, 401, 403, 409, 422, 429].includes(error.status) &&
        observationError instanceof LabApiError &&
        observationError.status === 404
      ) {
        // A definitive refused admission plus absent SQL state is not a lost
        // submitted model call. Clear only this local pending UI, never replay.
        clearPending();
        $("status").textContent = "Запрос отклонён; повторно не отправлялся.";
        return;
      }
      $("status").textContent =
        "Статус не подтверждён. Обновите историю; повторной отправки не было.";
    }
  }
});
$("message").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});
$("sleep-example").addEventListener("click", () => {
  $("message").value = "Ребёнок поздно засыпает. Помоги разобраться";
  $("message").focus();
});
$("refresh").addEventListener("click", () =>
  refresh().then(observePending).catch(showError),
);
async function start() {
  bootstrap = await api("/lab/bootstrap");
  $("mode").textContent =
    bootstrap.mode === "simulation"
      ? "● Бесплатная симуляция"
      : "● Реальная модель";
  $("mode-notice").textContent = bootstrap.scheduled_collection
    ? "Фиктивные данные и модель · 25.10.2026 · окна 09:00 и 15:00 по Ташкенту"
    : bootstrap.mode === "simulation"
      ? "Ответы симулируются · реальные API агентов и локальное хранилище"
      : "Модель платная · все данные и офферы тестовые · лимиты 2000 + 2000 токенов в день";
  $("mode-notice").classList.toggle("paid", bootstrap.mode !== "simulation");
  bootstrap.scenarios.forEach((scenario) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = scenario.title;
    button.addEventListener("click", async () => {
      if (busy) return;
      controls(true);
      $("error").hidden = true;
      try {
        // Refresh only fictional fixture parameters on explicit human action.
        // No data provider, model or write is called by this GET.
        bootstrap = await api("/lab/bootstrap");
        const fresh = bootstrap.scenarios.find(
          (item) => item.key === scenario.key,
        );
        const receipt = await api(
          fresh.local ? fresh.path : prefix + fresh.path,
          {
            method: "POST",
            body: JSON.stringify(fresh.body),
          },
        );
        if (fresh.path === "/lab/collection") {
          $("status").textContent =
            `Сбор: ${receipt.status} · ${receipt.targets} целей. Повтор кнопки читает только сохранённый результат.`;
          await refresh();
          return;
        }
        if (fresh.path === "/lab/retention-scenario") {
          $("status").textContent =
            "Вымышленная история подготовлена. Retention обратится через Parent-Touch.";
          await refresh();
          return;
        }
        if (fresh.local && receipt.status !== "completed") {
          throw new Error(
            receipt.error_code || "Чтение источника не подтверждено.",
          );
        }
        $("status").textContent = fresh.local
          ? receipt.cache_hit
            ? "Использован сохранённый снимок."
            : "Данные получены."
          : fresh.key === "paid"
            ? "Платный статус записан как тестовый факт; платежа не создавали."
            : receipt.decision
              ? `Конверсия: ${receipt.decision}. Соблюдаются тихие часы и приоритет безопасности.`
              : "Событие принято. Агент обработает его в этом же чате.";
        await refresh();
      } catch (error) {
        showError(error);
      } finally {
        controls(false);
      }
    });
    $("scenarios").append(button);
  });
  pending = sessionStorage.getItem("mana-lab-pending");
  if (pending) controls(true);
  await refresh();
  try {
    await observePending();
  } catch (error) {
    showError(error);
  }
  tick();
}
start().catch(showError);
