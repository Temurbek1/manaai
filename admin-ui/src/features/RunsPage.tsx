"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

import type { RunDetail, RunPage } from "../api/client";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { QueryState } from "../components/QueryState";
import { labelFor } from "../ui/labels";
import {
  compactId,
  formatDate,
  formatDuration,
  redactForDisplay,
} from "../ui/format";

const PAGE_SIZE = 20;

export function RunsPage({
  initialRunId = null,
}: {
  initialRunId?: string | null;
}): React.JSX.Element {
  const { t, locale } = useI18n();

  const [status, setStatus] = useState("");
  const [agentId, setAgentId] = useState("");
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (status) query.set("status", status);
  if (agentId) query.set("agent_id", agentId);
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    RunPage,
    Error
  >(`/api/v1/admin/operation/runs?${query.toString()}`, {
    refreshInterval: 15_000,
  });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(
    initialRunId,
  );
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const selectedButton = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (selectedRunId) detailHeading.current?.focus();
  }, [selectedRunId]);
  const {
    data: detail,
    error: detailError,
    isLoading: detailLoading,
    isValidating: detailValidating,
    mutate: refreshDetail,
  } = useSWR<RunDetail, Error>(
    selectedRunId ? `/api/v1/admin/operation/runs/${selectedRunId}` : null,
    { refreshInterval: 15_000 },
  );
  const runs = data?.items ?? [];
  const duration = detail?.run.completed_at
    ? Math.max(
        new Date(detail.run.completed_at).getTime() -
          new Date(detail.run.started_at).getTime(),
        0,
      )
    : null;
  return (
    <>
      <PageHeader
        eyebrow={t("История работы")}
        title={t("Запуски и журнал")}
        description={t(
          "История работы агентов: этапы, результаты, ошибки и подтверждающие данные.",
        )}
        actions={
          <button
            className="button secondary"
            disabled={isValidating}
            onClick={() => void mutate().catch(() => undefined)}
            type="button"
          >
            {isValidating ? t("Обновляем…") : t("Обновить экран")}
          </button>
        }
      />
      <section
        className="panel list-controls"
        aria-label={t("Фильтры запусков")}
      >
        <label>
          <span>{t("Агент")}</span>
          <select
            aria-label={t("Фильтр запусков по агенту")}
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">{t("Все агенты")}</option>
            <option value="growth-agent">{t("Рост и конверсия")}</option>
            <option value="retention-agent">
              {t("Удержание и лояльность")}
            </option>
            <option value="marketing-agent">
              {t("Маркетинг — исторические запуски")}{" "}
            </option>
          </select>
        </label>
        <label>
          <span>{t("Состояние")}</span>
          <select
            aria-label={t("Фильтр запусков по статусу")}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            value={status}
          >
            <option value="">{t("Все статусы")}</option>
            <option value="completed">{t("Завершён")}</option>
            <option value="failed">{t("Ошибка")}</option>
            <option value="waiting_approval">
              {t("Ожидает согласования")}
            </option>
            <option value="executing">{t("Выполняется")}</option>
            <option value="queued">{t("В очереди")}</option>
            <option value="collecting">{t("Сбор данных")}</option>
            <option value="analyzing">{t("Анализируется")}</option>
            <option value="cancelled">{t("Отменён")}</option>
          </select>
        </label>
        {status || agentId ? (
          <button
            type="button"
            className="button secondary compact"
            onClick={() => {
              setStatus("");
              setAgentId("");
              setOffset(0);
            }}
          >
            {t("Сбросить фильтры")}{" "}
          </button>
        ) : null}
        <span role="status">
          {data
            ? data.total === 0
              ? t("Запусков: 0")
              : t("{0}–{1} из {2}", {
                  "0": offset + 1,
                  "1": Math.min(offset + PAGE_SIZE, data.total),
                  "2": data.total,
                })
            : t("Количество неизвестно")}
        </span>
        <button
          className="button secondary compact"
          disabled={offset === 0 || isLoading}
          onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
          type="button"
        >
          {t("Назад")}{" "}
        </button>
        <button
          className="button secondary compact"
          disabled={!data || isLoading || offset + PAGE_SIZE >= data.total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          type="button"
        >
          {t("Далее")}{" "}
        </button>
      </section>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={mutate}
        subject={t("запуски")}
      />
      <section className="panel">
        <DataTable
          caption={t("История запусков агентов")}
          columns={[
            {
              key: "run",
              label: t("Запуск"),
              render: (item) => (
                <button
                  className="link-button"
                  aria-expanded={selectedRunId === item.run_id}
                  aria-controls={
                    selectedRunId === item.run_id ? "run-detail" : undefined
                  }
                  onClick={(event) => {
                    selectedButton.current = event.currentTarget;
                    setSelectedRunId(item.run_id);
                    if (selectedRunId === item.run_id)
                      detailHeading.current?.focus();
                  }}
                  type="button"
                >
                  <code>{compactId(item.run_id)}</code>
                </button>
              ),
            },
            {
              key: "agent",
              label: t("Агент"),
              render: (item) => t(labelFor(item.agent_id)),
            },
            {
              key: "status",
              label: t("Состояние"),
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "trigger",
              label: t("Инициатор"),
              render: (item) => `${item.trigger} · ${item.initiated_by}`,
            },
            {
              key: "start",
              label: t("Начало"),
              render: (item) => formatDate(item.started_at, locale),
            },
            {
              key: "correlation",
              label: t("Связь событий"),
              render: (item) => <code>{compactId(item.correlation_id)}</code>,
            },
          ]}
          items={runs}
          getKey={(item) => item.run_id}
          empty={
            data && !error ? (
              <EmptyState
                title={
                  isLoading ? t("Загружаем запуски") : t("Запусков пока нет")
                }
                detail={
                  isLoading
                    ? t("Загружаем историю работы.")
                    : t("Нет запусков с выбранным фильтром.")
                }
              />
            ) : null
          }
        />
      </section>
      {selectedRunId ? (
        <section
          className="panel run-detail"
          id="run-detail"
          aria-labelledby="run-detail-heading"
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Этапы запуска")}</p>
              <h2 ref={detailHeading} tabIndex={-1} id="run-detail-heading">
                {t("Запуск")} {compactId(selectedRunId)}
              </h2>
            </div>
            {detail ? <StatusBadge status={detail.run.status} /> : null}
            <button
              className="button secondary compact"
              type="button"
              onClick={() => {
                setSelectedRunId(null);
                selectedButton.current?.focus();
              }}
            >
              {t("Закрыть подробности")}{" "}
            </button>
          </div>
          <QueryState
            error={detailError}
            loading={detailLoading}
            hasData={Boolean(detail)}
            retrying={detailValidating}
            onRetry={refreshDetail}
            subject={t("подробности запуска")}
          />
          <ol className="timeline">
            {(detail?.timeline ?? [])
              .slice()
              .reverse()
              .map((event) => (
                <li key={event.event_id}>
                  <span aria-hidden="true" />
                  <div>
                    <strong>{event.summary}</strong>
                    <p>{event.event_type}</p>
                  </div>
                  <time>{formatDate(event.occurred_at, locale)}</time>
                </li>
              ))}
          </ol>
          <dl className="detail-grid summary-grid">
            <div>
              <dt>{t("Идентификатор связи событий")}</dt>
              <dd>
                <code>{detail?.run.correlation_id ?? "…"}</code>
              </dd>
            </div>
            <div>
              <dt>{t("Длительность")}</dt>
              <dd>{formatDuration(duration, locale)}</dd>
            </div>
            <div>
              <dt>{t("Повторы")}</dt>
              <dd>{detail?.run.retry_count ?? "…"}</dd>
            </div>
            <div>
              <dt>{t("Кто запустил")}</dt>
              <dd>
                {detail
                  ? `${detail.run.trigger} · ${detail.run.initiated_by}`
                  : "…"}
              </dd>
            </div>
            <div>
              <dt>{t("Снимки данных")}</dt>
              <dd>{detail?.snapshots.length ?? "…"}</dd>
            </div>
            <div>
              <dt>{t("Выводы")}</dt>
              <dd>{detail?.findings.length ?? "…"}</dd>
            </div>
            <div>
              <dt>{t("Предложения")}</dt>
              <dd>{detail?.recommendations.length ?? "…"}</dd>
            </div>
            <div>
              <dt>{t("Предложения действий")}</dt>
              <dd>{detail?.proposals.length ?? "…"}</dd>
            </div>
          </dl>
          {detail?.run.error_message ? (
            <div className="error-banner">
              <strong>{detail.run.error_code}</strong>:{" "}
              {detail.run.error_message}
            </div>
          ) : null}
          <details className="inspection-block">
            <summary>{t("Технические сведения об этапах")}</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label={t("Технические сведения об этапах")}
            >
              {JSON.stringify(
                redactForDisplay(
                  detail?.timeline.map((event) => ({
                    event: event.event_type,
                    details: event.details,
                  })) ?? [],
                ),
                null,
                2,
              )}
            </pre>
          </details>
          <details className="inspection-block">
            <summary>{t("Исходные данные")}</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label={t("Исходные данные запуска")}
            >
              {JSON.stringify(
                redactForDisplay(detail?.snapshots ?? []),
                null,
                2,
              )}
            </pre>
          </details>
          <details className="inspection-block">
            <summary>{t("Технические результаты")}</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label={t("Технические результаты запуска")}
            >
              {JSON.stringify(
                redactForDisplay({
                  findings: detail?.findings ?? [],
                  recommendations: detail?.recommendations ?? [],
                  proposals: detail?.proposals ?? [],
                }),
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      ) : null}
    </>
  );
}
