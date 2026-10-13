"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { GoalReport } from "./GoalReport";
import type { WorkspaceStreamState } from "./useWorkspaceStream";

export const GOALS_BASE = "/api/v1/admin/operation/goals";
type StoredGoal = components["schemas"]["OperationGoal"];
export type Goal = Omit<
  StoredGoal,
  "request" | "model_recoveries" | "limit_tracking" | "unsettled_microusd"
> & {
  limit_tracking?: StoredGoal["limit_tracking"];
  unsettled_microusd?: StoredGoal["unsettled_microusd"];
  model_recoveries?: StoredGoal["model_recoveries"];
  request: Omit<
    StoredGoal["request"],
    "execution_mode" | "analysis_scope" | "older_turns_omitted"
  > &
    Partial<
      Pick<
        StoredGoal["request"],
        "execution_mode" | "analysis_scope" | "older_turns_omitted"
      >
    >;
};
export type GoalsAvailability = components["schemas"]["GoalAvailability"];
type Command = components["schemas"]["GoalCommand"]["command"];
const LABELS: Record<Goal["status"], string> = {
  queued: "Продолжаем",
  running: "Работаю",
  paused: "На паузе",
  waiting: "Нужны данные или уточнение",
  completed: "Анализ готов",
  cancelled: "Отменена",
};
const TOOL_LABELS: Record<
  components["schemas"]["AgentToolCall"]["name"],
  string
> = {
  inspect_sources: "Проверка источников",
  read_saved_report: "Чтение сохранённого отчёта",
  read_saved_report_page: "Чтение части сохранённого отчёта",
  find_saved_tasks: "Поиск прошлых задач",
  read_saved_task: "Чтение прошлого результата",
  request_source_read: "Запрос нового чтения",
  ask_user: "Уточнение задачи",
};
const TOOL_STATUS: Record<
  components["schemas"]["AgentToolRecord"]["status"],
  string
> = {
  started: "В работе",
  completed: "Готово",
  awaiting_approval: "Нужно подтверждение",
  waiting_for_user: "Жду ответа",
  denied: "Недоступно",
  unknown: "Результат неизвестен",
};

export function GoalWorkspace({
  topicId,
  inlineSteering = true,
  progressStream,
  availability,
}: {
  topicId: string;
  inlineSteering?: boolean;
  progressStream?: WorkspaceStreamState;
  availability?: GoalsAvailability | undefined;
}): React.JSX.Element | null {
  const { session } = useSession();
  const canControl = hasRole(session, "operator");
  const { data, error, mutate } = useSWR<Goal[], Error>(
    `${GOALS_BASE}/topics/${topicId}`,
    {
      refreshInterval: (goals) => {
        if (
          !Array.isArray(goals) ||
          !goals.some((g) => !["completed", "cancelled"].includes(g.status))
        )
          return 0;
        const executing = goals.some(
          (g) => ["queued", "running"].includes(g.status) || g.lease_until,
        );
        return progressStream?.connected || !executing ? 15000 : 2000;
      },
    },
  );
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [limitFormGoalId, setLimitFormGoalId] = useState<string | null>(null);
  const [limitSteps, setLimitSteps] = useState("");
  const [limitBudget, setLimitBudget] = useState("");
  const guard = useRef(false);
  const pending = useRef<{ goalId: string; payload: object } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  // Older deployed servers may not have Goals. Never make that break ordinary chat.
  if (!Array.isArray(data) || !data.length) return null;
  const goal = data[0]!;
  const plan = goal.plan ?? [];
  const events = goal.events ?? [];
  const evidence = goal.evidence ?? [];
  const question = goal.tools?.at(-1);
  const terminal = ["completed", "cancelled"].includes(goal.status);
  const liveUpdate =
    progressStream?.event?.goal_id === goal.goal_id &&
    progressStream.event.revision >= goal.revision
      ? progressStream.event
      : null;
  const inFlight =
    goal.lease_until && new Date(goal.lease_until).getTime() > now;
  const limits = goal.limit_grants?.at(-1) ?? goal.request;
  const canExtend = Boolean(
    goal.limit_tracking &&
    goal.limit_stop &&
    !goal.unsettled_microusd &&
    availability?.limit_extensions_enabled &&
    (goal.limit_stop === "steps"
      ? limits.max_steps < (availability.extension_max_steps ?? 0)
      : limits.budget_microusd < (availability.extension_budget_microusd ?? 0)),
  );
  const proposedSteps = Number(limitSteps);
  const proposedBudget = Math.round(Number(limitBudget) * 1_000_000);
  const validLimits = Boolean(
    canExtend &&
    Number.isInteger(proposedSteps) &&
    proposedSteps >= limits.max_steps &&
    proposedSteps <= (availability?.extension_max_steps ?? 0) &&
    /^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(limitBudget) &&
    Number.isSafeInteger(proposedBudget) &&
    proposedBudget >= limits.budget_microusd &&
    proposedBudget <= (availability?.extension_budget_microusd ?? 0) &&
    (proposedSteps > limits.max_steps ||
      proposedBudget > limits.budget_microusd) &&
    (goal.limit_stop !== "steps" || proposedSteps > goal.steps_used) &&
    (goal.limit_stop !== "budget" || proposedBudget > limits.budget_microusd),
  );

  async function control(
    command: Command,
    clarification = message,
    extension?: { max_steps: number; budget_microusd: number },
  ): Promise<void> {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setActionError(null);
    const payload = {
      request_id: crypto.randomUUID(),
      command,
      message: command === "steer" ? clarification.trim() : "",
      expected_revision: goal.revision,
      ...(command === "extend_limits" ? extension : {}),
    };
    const prior = pending.current?.payload as
      | {
          command?: Command;
          message?: string;
          expected_revision?: number;
          max_steps?: number;
          budget_microusd?: number;
        }
      | undefined;
    if (
      pending.current?.goalId !== goal.goal_id ||
      prior?.command !== command ||
      prior?.message !== payload.message ||
      prior?.expected_revision !== goal.revision ||
      prior?.max_steps !== extension?.max_steps ||
      prior?.budget_microusd !== extension?.budget_microusd
    )
      pending.current = { goalId: goal.goal_id, payload };
    try {
      await apiPost(
        `${GOALS_BASE}/${pending.current.goalId}/commands`,
        pending.current.payload,
      );
      pending.current = null;
      if (command === "steer") setMessage("");
      if (command === "extend_limits") setLimitFormGoalId(null);
      await mutate();
    } catch (caught) {
      setActionError(
        caught instanceof Error ? caught.message : "Не удалось изменить цель.",
      );
      // Fetch state before any further choice. A lost response is not a failed command.
      await mutate().catch(() => undefined);
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="goal-workspace" aria-label="Рабочая цель">
      <div className="goal-heading">
        <span>Цель</span>
        <span role="status">{LABELS[goal.status]}</span>
      </div>
      <h2>{goal.request.objective}</h2>
      {goal.request.analysis_scope === "saved_snapshot" && (
        <p className="goal-update">Исторический срез · не текущее состояние</p>
      )}
      {error && (
        <p role="alert">
          Не удалось обновить прогресс. Сохранённое состояние показано ниже.
        </p>
      )}
      {plan.length > 0 && (
        <ol className="goal-plan" aria-label="План цели">
          {plan.map((task, index) => (
            <li key={index} data-status={task.status}>
              <span
                aria-label={
                  task.status === "done"
                    ? "Готово"
                    : task.status === "blocked"
                      ? "Заблокировано"
                      : "В плане"
                }
              >
                {task.status === "done"
                  ? "✓"
                  : task.status === "blocked"
                    ? "!"
                    : "○"}
              </span>{" "}
              {task.title}
            </li>
          ))}
        </ol>
      )}
      {["running", "queued"].includes(goal.status) && (
        <p className="goal-update">
          {liveUpdate?.message ??
            events.filter((e) => e.kind === "progress").at(-1)?.message ??
            (goal.status === "queued"
              ? "Задача в очереди."
              : "Готовлю следующий шаг…")}
        </p>
      )}
      {(goal.tools ?? []).length > 0 && (
        <details className="goal-details">
          <summary>Инструменты · {goal.tools!.length}</summary>
          <ol>
            {goal.tools!.map((tool) => (
              <li key={tool.call_id}>
                {TOOL_LABELS[tool.call.name]} · {TOOL_STATUS[tool.status]}
                {tool.call.report_id && <span> · {tool.call.report_id}</span>}
                {tool.result && (
                  <details>
                    <summary>Результат</summary>
                    <pre>{tool.result}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
      {goal.waiting_reason && (
        <p className="goal-waiting" role="status">
          {goal.waiting_reason}
        </p>
      )}
      {goal.status === "waiting" &&
        canControl &&
        question?.call.name === "ask_user" && (
          <div className="goal-controls">
            {(question.call.options ?? []).map((option) => (
              <button
                key={option}
                type="button"
                disabled={busy}
                onClick={() => void control("steer", option)}
              >
                {option}
              </button>
            ))}
          </div>
        )}
      {evidence.some(
        (item) =>
          !item.fresh_until ||
          Date.parse(item.fresh_until) <= now ||
          !["live", "cached"].includes(item.refresh_status),
      ) && (
        <p className="goal-update">
          Есть устаревшие данные или источники с неподтверждённой свежестью.
        </p>
      )}
      {goal.result && (
        <div
          className="goal-result"
          aria-label={
            goal.status === "completed"
              ? "Результат цели"
              : "Промежуточный результат"
          }
        >
          <GoalReport text={goal.result} />
        </div>
      )}
      {goal.status === "completed" && (
        <p className="goal-update">
          Анализ завершён. Изменения в приложении не выполнялись.
        </p>
      )}
      {actionError && <p role="alert">{actionError}</p>}
      {!terminal && canControl && (
        <div className="goal-controls">
          {["running", "queued"].includes(goal.status) ? (
            inlineSteering ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void control("pause")}
              >
                Пауза
              </button>
            ) : null
          ) : goal.requested_capability ||
            goal.limit_stop ||
            goal.unsettled_microusd ||
            (goal.status === "waiting" &&
              question?.call.name === "ask_user") ? null : (
            <button
              type="button"
              disabled={busy || Boolean(inFlight)}
              onClick={() => void control("resume")}
            >
              Продолжить
            </button>
          )}
          {goal.limit_stop && canExtend && limitFormGoalId !== goal.goal_id && (
            <button
              type="button"
              disabled={busy || Boolean(inFlight)}
              onClick={() => {
                setLimitSteps(
                  String(
                    Math.min(
                      limits.max_steps + 6,
                      availability!.extension_max_steps,
                    ),
                  ),
                );
                const budget =
                  goal.limit_stop === "budget"
                    ? Math.min(
                        limits.budget_microusd + 100000,
                        availability!.extension_budget_microusd,
                      )
                    : limits.budget_microusd;
                setLimitBudget((Math.ceil(budget / 10000) / 100).toFixed(2));
                setLimitFormGoalId(goal.goal_id);
              }}
            >
              Продолжить эту цель
            </button>
          )}
          {goal.requested_capability && goal.status === "waiting" && (
            <div className="goal-read">
              <p>
                Один read-only анализ{" "}
                {goal.product === "mana" ? "MANA" : "360REC"}. Проверяются
                доступ, привязка приложения, интервал 6 ч и общий бюджет. Без
                изменения данных.
              </p>
              <button
                type="button"
                disabled={busy || Boolean(inFlight)}
                onClick={() => void control("approve_read")}
              >
                Разрешить чтение данных
              </button>
            </div>
          )}
          {inFlight && goal.status === "paused" && (
            <span>Заканчивается текущий запрос…</span>
          )}
        </div>
      )}
      {!terminal &&
        canControl &&
        goal.limit_stop &&
        canExtend &&
        limitFormGoalId === goal.goal_id && (
          <form
            className="goal-limit-form"
            aria-label="Увеличить лимиты цели"
            onSubmit={(event) => {
              event.preventDefault();
              if (validLimits && !inFlight)
                void control("extend_limits", "", {
                  max_steps: proposedSteps,
                  budget_microusd: proposedBudget,
                });
            }}
          >
            <label>
              Всего шагов
              <input
                type="number"
                min={limits.max_steps}
                max={availability!.extension_max_steps}
                step="1"
                value={limitSteps}
                disabled={busy}
                onChange={(event) => setLimitSteps(event.target.value)}
              />
            </label>
            <label>
              Общий бюджет, $
              <input
                type="number"
                min={limits.budget_microusd / 1_000_000}
                max={availability!.extension_budget_microusd / 1_000_000}
                step="0.01"
                value={limitBudget}
                disabled={busy}
                onChange={(event) => setLimitBudget(event.target.value)}
              />
            </label>
            <p>
              Расходы сохраняются. Это не разрешение на новое чтение данных.
            </p>
            <button
              type="submit"
              disabled={busy || Boolean(inFlight) || !validLimits}
            >
              Подтвердить и продолжить
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setLimitFormGoalId(null)}
            >
              Назад
            </button>
          </form>
        )}
      {goal.status === "waiting" && Boolean(goal.unsettled_microusd) && (
        <p className="goal-update">
          Исход AI-запроса неизвестен. Резерв сохранён; повтор не запускается.
        </p>
      )}
      {goal.limit_stop && !canExtend && (
        <p className="goal-update">
          Продолжение с новыми лимитами сейчас недоступно. Результат сохранён.
        </p>
      )}
      {!terminal && canControl && inlineSteering && (
        <form
          className="goal-steer"
          onSubmit={(event) => {
            event.preventDefault();
            void control("steer");
          }}
        >
          <label className="sr-only" htmlFor={`goal-steer-${goal.goal_id}`}>
            Уточнение цели
          </label>
          <input
            id={`goal-steer-${goal.goal_id}`}
            placeholder="Уточните цель или добавьте контекст…"
            value={message}
            maxLength={6000}
            disabled={busy}
            onChange={(event) => {
              setMessage(event.target.value);
              pending.current = null;
            }}
          />
          <button type="submit" disabled={busy || !message.trim()}>
            Отправить
          </button>
        </form>
      )}
      <details className="goal-details">
        <summary>История и источники</summary>
        <p>
          {goal.steps_used} / {limits.max_steps} шагов · Учтено с резервом: $
          {(goal.accounted_microusd / 1_000_000).toFixed(3)} / $
          {(limits.budget_microusd / 1_000_000).toFixed(2)}
        </p>
        <p>Критерий: {goal.request.success_criteria}</p>
        <p>Ограничения: {goal.request.constraints}</p>
        <ul>
          {evidence.map((item) => (
            <li key={item.report_id}>
              {item.report_id} ·{" "}
              {item.refresh_status === "stale"
                ? "Устарел"
                : item.refresh_status === "unknown"
                  ? "Свежесть неизвестна"
                  : "Подтверждён"}{" "}
              ·{" "}
              {item.collected_at
                ? new Date(item.collected_at).toLocaleString("ru-RU")
                : "Дата сбора неизвестна"}
            </li>
          ))}
        </ul>
        <ol>
          {events.map((event, index) => (
            <li key={index}>
              <time>{new Date(event.at).toLocaleString("ru-RU")}</time>{" "}
              {event.message}
            </li>
          ))}
        </ol>
        {!terminal && canControl && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void control("cancel")}
          >
            Отменить цель
          </button>
        )}
      </details>
      {data.length > 1 && (
        <details className="goal-details">
          <summary>Предыдущие цели</summary>
          {data.slice(1).map((old) => (
            <article key={old.goal_id}>
              <h3>{old.request.objective}</h3>
              <p>{LABELS[old.status]}</p>
              <p className="goal-result">{old.result || old.waiting_reason}</p>
            </article>
          ))}
        </details>
      )}
    </section>
  );
}
