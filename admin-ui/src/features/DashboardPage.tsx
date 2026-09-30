"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";

import { apiPost, apiPut, type Dashboard } from "../api/client";
import { hasRole, useSession } from "../auth/SessionContext";
import { DataTable } from "../components/DataTable";
import { ConfirmAction } from "../components/ConfirmAction";
import { EmptyState } from "../components/EmptyState";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { QueryState } from "../components/QueryState";
import { formatDate, formatDuration } from "../ui/format";
import { labelFor } from "../ui/labels";

const DASHBOARD_KEY = "/api/v1/admin/operation/dashboard";

export function DashboardPage(): React.JSX.Element {
  const { session } = useSession();
  const canRun = hasRole(session, "operator");
  const canAdminister = hasRole(session, "admin");
  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate: refresh,
  } = useSWR<Dashboard, Error>(DASHBOARD_KEY, {
    refreshInterval: 15_000,
  });
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function toggleKillSwitch(): Promise<void> {
    if (!data || busy) return;
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const freshDashboard = await mutate<Dashboard>(DASHBOARD_KEY);
      if (!freshDashboard)
        throw new Error("Текущее состояние ограничений недоступно");
      if (freshDashboard.global_kill_switch !== data.global_kill_switch)
        throw new Error(
          "Состояние уже изменилось. Проверьте обновлённый обзор и подтвердите действие заново.",
        );
      await apiPut("/api/v1/admin/operation/kill-switch/global", {
        enabled: !freshDashboard.global_kill_switch,
      });
      await mutate(DASHBOARD_KEY);
      setMessage(
        freshDashboard.global_kill_switch
          ? "Остановка снята. Действия по-прежнему ограничены политиками доступа."
          : "Новые действия остановлены. Уже начатую работу проверяйте в журнале.",
      );
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : "Не удалось изменить ограничения",
      );
    } finally {
      setBusy(false);
    }
  }

  async function runAgent(agentId: string): Promise<void> {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      await apiPost(`/api/v1/admin/operation/agents/${agentId}/run`, {
        job_type: "analysis",
      });
      await mutate(DASHBOARD_KEY);
      setMessage(
        "Запрос на анализ принят. Состояние и результат доступны в журнале запусков.",
      );
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : "Не удалось запустить анализ",
      );
    } finally {
      setBusy(false);
    }
  }

  const agents = data?.agents ?? [];
  const pending = agents.reduce(
    (total, item) => total + item.pending_approvals,
    0,
  );
  const incidents = agents.reduce(
    (total, item) => total + item.recent_incidents,
    0,
  );
  return (
    <>
      <PageHeader
        eyebrow="Администрация"
        title="Обзор работы"
        description="Состояние агентов, ожидающие решения, расписание и ограничения. Просмотр страницы не запускает сбор данных."
        actions={
          <div className="header-actions">
            <button
              className="button secondary"
              disabled={isValidating}
              onClick={() => void refresh().catch(() => undefined)}
              type="button"
            >
              {isValidating ? "Обновляем…" : "Обновить экран"}
            </button>
            <ConfirmAction
              className={
                data?.global_kill_switch ? "button danger" : "button secondary"
              }
              confirmLabel={
                data?.global_kill_switch
                  ? "Подтвердить возобновление"
                  : "Подтвердить остановку"
              }
              disabled={!data || Boolean(error) || busy || !canAdminister}
              description="Меняет запрет на новые действия агентов. Не отменяет уже начатую работу и не снимает ограничения отдельных источников."
              label={
                data?.global_kill_switch
                  ? "Возобновить действия"
                  : "Остановить действия"
              }
              onConfirm={() => void toggleKillSwitch()}
            />
          </div>
        }
      />
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={refresh}
        subject="обзор"
      />
      {message ? (
        <p className="notice" role="status">
          {message} <Link href="/runs">Открыть журнал</Link>
        </p>
      ) : null}
      {actionError ? (
        <p className="error-banner" role="alert">
          {actionError}
        </p>
      ) : null}
      <section className="metric-grid" aria-label="Показатели работы агентов">
        <MetricCard
          label="Подключено агентов"
          value={data ? agents.length : "—"}
        />
        <MetricCard
          label="Ожидают согласования"
          value={data ? pending : "—"}
          accent="amber"
        />
        <MetricCard
          label="Запуски с ошибками"
          value={data ? incidents : "—"}
          accent="rose"
        />
        <MetricCard
          label="Выполнение действий"
          value={
            !data
              ? "Нет данных"
              : data.global_kill_switch
                ? "Остановлено"
                : "Разрешено политикой"
          }
          detail="Изменения в реальном рекламном кабинете запрещены"
          accent="blue"
        />
      </section>
      <section className="task-grid" aria-label="Быстрые переходы">
        <Link className="task-card" href="/approvals">
          <span className="eyebrow">Решения</span>
          <strong>
            Рассмотреть согласования <span aria-hidden="true">→</span>
          </strong>
          <span>
            {data
              ? `Ожидают решения: ${pending}.`
              : "Проверить очередь предложений."}{" "}
            Проверяйте основания до одобрения.
          </span>
        </Link>
        <Link className="task-card" href="/retention">
          <span className="eyebrow">Данные</span>
          <strong>
            Проверить активность <span aria-hidden="true">→</span>
          </strong>
          <span>Сохранённый отчёт, дата сбора и ограничения источников.</span>
        </Link>
        <Link className="task-card" href="/runs">
          <span className="eyebrow">Контроль</span>
          <strong>
            Разобрать запуски <span aria-hidden="true">→</span>
          </strong>
          <span>
            Результаты, ошибки и история. Без повторного запуска анализа.
          </span>
        </Link>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Агенты и настройки</p>
            <h2>Агенты</h2>
          </div>
          <span className="muted">
            Обновлено {formatDate(data?.generated_at)}
          </span>
        </div>
        <DataTable
          caption="Состояние агентов"
          columns={[
            {
              key: "agent",
              label: "Агент",
              render: (item) => (
                <div className="primary-cell">
                  <strong>{labelFor(item.agent_id)}</strong>
                </div>
              ),
            },
            {
              key: "status",
              label: "Состояние",
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "health",
              label: "Подключения",
              render: (item) => <StatusBadge status={item.health} />,
            },
            {
              key: "last",
              label: "Последний запуск",
              render: (item) => formatDate(item.last_run),
            },
            {
              key: "next",
              label: "Следующий запуск",
              render: (item) => formatDate(item.next_run),
            },
            {
              key: "duration",
              label: "Длительность",
              render: (item) => formatDuration(item.last_duration_ms),
            },
            {
              key: "success",
              label: "Успешно",
              render: (item) =>
                item.success_rate === "unavailable"
                  ? "Нет запусков"
                  : new Intl.NumberFormat("ru-RU", {
                      style: "percent",
                      maximumFractionDigits: 0,
                    }).format(Number(item.success_rate)),
            },
            {
              key: "actions",
              label: "Действия",
              render: (item) => (
                <ConfirmAction
                  className="button compact"
                  disabled={
                    busy ||
                    Boolean(error) ||
                    item.status !== "enabled" ||
                    !canRun
                  }
                  description={`Агент «${labelFor(item.agent_id)}» обратится к настроенным источникам. Это может расходовать квоты и бюджет. Для просмотра сохранённых данных запуск не нужен.`}
                  onConfirm={() => void runAgent(item.agent_id)}
                  label="Запустить анализ"
                  confirmLabel="Подтвердить сбор данных"
                />
              ),
            },
          ]}
          items={agents}
          getKey={(item) => item.agent_id}
          empty={
            data ? (
              <EmptyState
                title="Агентов пока нет"
                detail="Здесь появятся подключённые агенты."
              />
            ) : null
          }
        />
      </section>
      <p className="notice">
        Обновление экрана читает только сохранённые данные. Кнопка «Запустить
        анализ» обращается к внешним источникам в пределах настроенных лимитов.
      </p>
    </>
  );
}
