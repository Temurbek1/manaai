"use client";

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
        eyebrow="История работы"
        title="Запуски и журнал"
        description="История работы агентов: этапы, результаты, ошибки и подтверждающие данные."
        actions={
          <button
            className="button secondary"
            disabled={isValidating}
            onClick={() => void mutate().catch(() => undefined)}
            type="button"
          >
            {isValidating ? "Обновляем…" : "Обновить экран"}
          </button>
        }
      />
      <section className="panel list-controls" aria-label="Фильтры запусков">
        <label>
          <span>Агент</span>
          <select
            aria-label="Фильтр запусков по агенту"
            value={agentId}
            onChange={(event) => {
              setAgentId(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Все агенты</option>
            <option value="growth-agent">Рост и конверсия</option>
            <option value="retention-agent">Удержание и лояльность</option>
            <option value="marketing-agent">
              Маркетинг — исторические запуски
            </option>
          </select>
        </label>
        <label>
          <span>Состояние</span>
          <select
            aria-label="Фильтр запусков по статусу"
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            value={status}
          >
            <option value="">Все статусы</option>
            <option value="completed">Завершён</option>
            <option value="failed">Ошибка</option>
            <option value="waiting_approval">Ожидает согласования</option>
            <option value="executing">Выполняется</option>
            <option value="queued">В очереди</option>
            <option value="collecting">Сбор данных</option>
            <option value="analyzing">Анализируется</option>
            <option value="cancelled">Отменён</option>
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
            Сбросить фильтры
          </button>
        ) : null}
        <span role="status">
          {data
            ? data.total === 0
              ? "Запусков: 0"
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, data.total)} из ${data.total}`
            : "Количество неизвестно"}
        </span>
        <button
          className="button secondary compact"
          disabled={offset === 0 || isLoading}
          onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
          type="button"
        >
          Назад
        </button>
        <button
          className="button secondary compact"
          disabled={!data || isLoading || offset + PAGE_SIZE >= data.total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          type="button"
        >
          Далее
        </button>
      </section>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={mutate}
        subject="запуски"
      />
      <section className="panel">
        <DataTable
          caption="История запусков агентов"
          columns={[
            {
              key: "run",
              label: "Запуск",
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
              label: "Агент",
              render: (item) => labelFor(item.agent_id),
            },
            {
              key: "status",
              label: "Состояние",
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "trigger",
              label: "Инициатор",
              render: (item) => `${item.trigger} · ${item.initiated_by}`,
            },
            {
              key: "start",
              label: "Начало",
              render: (item) => formatDate(item.started_at),
            },
            {
              key: "correlation",
              label: "Связь событий",
              render: (item) => <code>{compactId(item.correlation_id)}</code>,
            },
          ]}
          items={runs}
          getKey={(item) => item.run_id}
          empty={
            data && !error ? (
              <EmptyState
                title={isLoading ? "Загружаем запуски" : "Запусков пока нет"}
                detail={
                  isLoading
                    ? "Загружаем историю работы."
                    : "Нет запусков с выбранным фильтром."
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
              <p className="eyebrow">Этапы запуска</p>
              <h2 ref={detailHeading} tabIndex={-1} id="run-detail-heading">
                Запуск {compactId(selectedRunId)}
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
              Закрыть подробности
            </button>
          </div>
          <QueryState
            error={detailError}
            loading={detailLoading}
            hasData={Boolean(detail)}
            retrying={detailValidating}
            onRetry={refreshDetail}
            subject="подробности запуска"
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
                  <time>{formatDate(event.occurred_at)}</time>
                </li>
              ))}
          </ol>
          <dl className="detail-grid summary-grid">
            <div>
              <dt>Идентификатор связи событий</dt>
              <dd>
                <code>{detail?.run.correlation_id ?? "…"}</code>
              </dd>
            </div>
            <div>
              <dt>Длительность</dt>
              <dd>{formatDuration(duration)}</dd>
            </div>
            <div>
              <dt>Повторы</dt>
              <dd>{detail?.run.retry_count ?? "…"}</dd>
            </div>
            <div>
              <dt>Кто запустил</dt>
              <dd>
                {detail
                  ? `${detail.run.trigger} · ${detail.run.initiated_by}`
                  : "…"}
              </dd>
            </div>
            <div>
              <dt>Снимки данных</dt>
              <dd>{detail?.snapshots.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Выводы</dt>
              <dd>{detail?.findings.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Предложения</dt>
              <dd>{detail?.recommendations.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Предложения действий</dt>
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
            <summary>Технические сведения об этапах</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label="Технические сведения об этапах"
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
            <summary>Исходные данные</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label="Исходные данные запуска"
            >
              {JSON.stringify(
                redactForDisplay(detail?.snapshots ?? []),
                null,
                2,
              )}
            </pre>
          </details>
          <details className="inspection-block">
            <summary>Технические результаты</summary>
            <pre
              tabIndex={0}
              role="region"
              aria-label="Технические результаты запуска"
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
