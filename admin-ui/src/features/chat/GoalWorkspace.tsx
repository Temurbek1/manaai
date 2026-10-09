"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { GoalReport } from "./GoalReport";

export const GOALS_BASE = "/api/v1/admin/operation/goals";
export type Goal = components["schemas"]["OperationGoal"];
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

export function GoalWorkspace({
  topicId,
  inlineSteering = true,
}: {
  topicId: string;
  inlineSteering?: boolean;
}): React.JSX.Element | null {
  const { session } = useSession();
  const canControl = hasRole(session, "operator");
  const { data, error, mutate } = useSWR<Goal[], Error>(
    `${GOALS_BASE}/topics/${topicId}`,
    {
      refreshInterval: (goals) =>
        Array.isArray(goals) &&
        goals.some(
          (g) => ["queued", "running"].includes(g.status) || g.lease_until,
        )
          ? 2000
          : 0,
    },
  );
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
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
  const terminal = ["completed", "cancelled"].includes(goal.status);
  const inFlight =
    goal.lease_until && new Date(goal.lease_until).getTime() > now;

  async function control(command: Command): Promise<void> {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setActionError(null);
    const payload = {
      request_id: crypto.randomUUID(),
      command,
      message: command === "steer" ? message.trim() : "",
      expected_revision: goal.revision,
    };
    const prior = pending.current?.payload as
      | { command?: Command; message?: string; expected_revision?: number }
      | undefined;
    if (
      pending.current?.goalId !== goal.goal_id ||
      prior?.command !== command ||
      prior?.message !== payload.message ||
      prior?.expected_revision !== goal.revision
    )
      pending.current = { goalId: goal.goal_id, payload };
    try {
      await apiPost(
        `${GOALS_BASE}/${pending.current.goalId}/commands`,
        pending.current.payload,
      );
      pending.current = null;
      if (command === "steer") setMessage("");
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
      {goal.status === "running" && (
        <p className="goal-update">
          {events.filter((e) => e.kind === "progress").at(-1)?.message ??
            "Составляю план и проверяю контекст…"}
        </p>
      )}
      {goal.waiting_reason && (
        <p className="goal-waiting" role="status">
          {goal.waiting_reason}
        </p>
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
          ) : (
            <button
              type="button"
              disabled={busy || Boolean(inFlight)}
              onClick={() => void control("resume")}
            >
              Продолжить
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
            placeholder={
              inFlight
                ? "Сначала поставьте цель на паузу"
                : "Уточните цель или добавьте контекст…"
            }
            value={message}
            maxLength={6000}
            disabled={busy || Boolean(inFlight)}
            onChange={(event) => {
              setMessage(event.target.value);
              pending.current = null;
            }}
          />
          <button
            type="submit"
            disabled={busy || Boolean(inFlight) || !message.trim()}
          >
            Отправить
          </button>
        </form>
      )}
      <details className="goal-details">
        <summary>История и источники</summary>
        <p>
          {goal.steps_used} / {goal.request.max_steps} шагов · Учтено с
          резервом: ${(goal.accounted_microusd / 1_000_000).toFixed(3)} / $
          {(goal.request.budget_microusd / 1_000_000).toFixed(2)}
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
