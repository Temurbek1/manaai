"use client";

import { useI18n } from "@/i18n/LanguageProvider";

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
  const { t, locale } = useI18n();

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
        throw new Error(t("Текущее состояние ограничений недоступно"));
      if (freshDashboard.global_kill_switch !== data.global_kill_switch)
        throw new Error(
          t(
            "Состояние уже изменилось. Проверьте обновлённый обзор и подтвердите действие заново.",
          ),
        );
      await apiPut("/api/v1/admin/operation/kill-switch/global", {
        enabled: !freshDashboard.global_kill_switch,
      });
      await mutate(DASHBOARD_KEY);
      setMessage(
        freshDashboard.global_kill_switch
          ? t(
              "Остановка снята. Действия по-прежнему ограничены политиками доступа.",
            )
          : t(
              "Новые действия остановлены. Уже начатую работу проверяйте в журнале.",
            ),
      );
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : t("Не удалось изменить ограничения"),
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
        t(
          "Запрос на анализ принят. Состояние и результат доступны в журнале запусков.",
        ),
      );
    } catch (caught) {
      setActionError(
        caught instanceof Error
          ? caught.message
          : t("Не удалось запустить анализ"),
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
        eyebrow={t("Администрация")}
        title={t("Обзор работы")}
        description={t(
          "Состояние агентов, ожидающие решения, расписание и ограничения. Просмотр страницы не запускает сбор данных.",
        )}
        actions={
          <div className="header-actions">
            <button
              className="button secondary"
              disabled={isValidating}
              onClick={() => void refresh().catch(() => undefined)}
              type="button"
            >
              {isValidating ? t("Обновляем…") : t("Обновить экран")}
            </button>
            <ConfirmAction
              className={
                data?.global_kill_switch ? "button danger" : "button secondary"
              }
              confirmLabel={
                data?.global_kill_switch
                  ? t("Подтвердить возобновление")
                  : t("Подтвердить остановку")
              }
              disabled={!data || Boolean(error) || busy || !canAdminister}
              description={t(
                "Меняет запрет на новые действия агентов. Не отменяет уже начатую работу и не снимает ограничения отдельных источников.",
              )}
              label={
                data?.global_kill_switch
                  ? t("Возобновить действия")
                  : t("Остановить действия")
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
        subject={t("обзор")}
      />
      {message ? (
        <p className="notice" role="status">
          {t(message)} <Link href="/runs">{t("Открыть журнал")}</Link>
        </p>
      ) : null}
      {actionError ? (
        <p className="error-banner" role="alert">
          {t(actionError)}
        </p>
      ) : null}
      <section
        className="metric-grid"
        aria-label={t("Показатели работы агентов")}
      >
        <MetricCard
          label={t("Подключено агентов")}
          value={data ? agents.length : "—"}
        />
        <MetricCard
          label={t("Ожидают согласования")}
          value={data ? pending : "—"}
          accent="amber"
        />
        <MetricCard
          label={t("Запуски с ошибками")}
          value={data ? incidents : "—"}
          accent="rose"
        />
        <MetricCard
          label={t("Выполнение действий")}
          value={
            !data
              ? t("Нет данных")
              : data.global_kill_switch
                ? t("Остановлено")
                : t("Разрешено политикой")
          }
          detail={t("Изменения в реальном рекламном кабинете запрещены")}
          accent="blue"
        />
      </section>
      <section className="task-grid" aria-label={t("Быстрые переходы")}>
        <Link className="task-card" href="/approvals">
          <span className="eyebrow">{t("Решения")}</span>
          <strong>
            {t("Рассмотреть согласования")} <span aria-hidden="true">→</span>
          </strong>
          <span>
            {data
              ? t("Ожидают решения: {0}.", { "0": pending })
              : t("Проверить очередь предложений.")}{" "}
            {t("Проверяйте основания до одобрения.")}{" "}
          </span>
        </Link>
        <Link className="task-card" href="/analytics">
          <span className="eyebrow">{t("Данные")}</span>
          <strong>
            {t("Аналитика и данные")} <span aria-hidden="true">→</span>
          </strong>
          <span>
            {t(
              "GA4, Firebase и Parent API. Сохранённые показатели и ограничения.",
            )}
          </span>
        </Link>
        <Link className="task-card" href="/runs">
          <span className="eyebrow">{t("Контроль")}</span>
          <strong>
            {t("Разобрать запуски")} <span aria-hidden="true">→</span>
          </strong>
          <span>
            {t(
              "Результаты, ошибки и история. Без повторного запуска анализа.",
            )}{" "}
          </span>
        </Link>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Агенты и настройки")}</p>
            <h2>{t("Агенты")}</h2>
          </div>
          <span className="muted">
            {t("Обновлено")} {formatDate(data?.generated_at, locale)}
          </span>
        </div>
        <DataTable
          caption={t("Состояние агентов")}
          columns={[
            {
              key: "agent",
              label: t("Агент"),
              render: (item) => (
                <div className="primary-cell">
                  <strong>{t(labelFor(item.agent_id))}</strong>
                </div>
              ),
            },
            {
              key: "status",
              label: t("Состояние"),
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "health",
              label: t("Подключения"),
              render: (item) => <StatusBadge status={item.health} />,
            },
            {
              key: "last",
              label: t("Последний запуск"),
              render: (item) => formatDate(item.last_run, locale),
            },
            {
              key: "next",
              label: t("Следующий запуск"),
              render: (item) => formatDate(item.next_run, locale),
            },
            {
              key: "duration",
              label: t("Длительность"),
              render: (item) => formatDuration(item.last_duration_ms, locale),
            },
            {
              key: "success",
              label: t("Успешно"),
              render: (item) =>
                item.success_rate === "unavailable"
                  ? t("Нет запусков")
                  : new Intl.NumberFormat("ru-RU", {
                      style: "percent",
                      maximumFractionDigits: 0,
                    }).format(Number(item.success_rate)),
            },
            {
              key: "actions",
              label: t("Действия"),
              render: (item) => (
                <ConfirmAction
                  className="button compact"
                  disabled={
                    busy ||
                    Boolean(error) ||
                    item.status !== "enabled" ||
                    !canRun
                  }
                  description={t(
                    "Агент «{0}» обратится к настроенным источникам. Это может расходовать квоты и бюджет. Для просмотра сохранённых данных запуск не нужен.",
                    { "0": labelFor(item.agent_id) },
                  )}
                  onConfirm={() => void runAgent(item.agent_id)}
                  label={t("Запустить анализ")}
                  confirmLabel={t("Подтвердить сбор данных")}
                />
              ),
            },
          ]}
          items={agents}
          getKey={(item) => item.agent_id}
          empty={
            data ? (
              <EmptyState
                title={t("Агентов пока нет")}
                detail={t("Здесь появятся подключённые агенты.")}
              />
            ) : null
          }
        />
      </section>
      <p className="notice">
        {t(
          "Обновление экрана читает только сохранённые данные. Кнопка «Запустить анализ» обращается к внешним источникам в пределах настроенных лимитов.",
        )}{" "}
      </p>
    </>
  );
}
