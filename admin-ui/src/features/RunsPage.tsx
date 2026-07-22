"use client";

import { useState } from "react";
import useSWR from "swr";

import type { RunDetail, RunPage } from "../api/client";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import {
  compactId,
  formatDate,
  formatDuration,
  redactForDisplay,
} from "../ui/format";

const PAGE_SIZE = 20;

export function RunsPage(): React.JSX.Element {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (status) query.set("status", status);
  const { data, error, isLoading } = useSWR<RunPage, Error>(
    `/api/v1/admin/operation/runs?${query.toString()}`,
    { refreshInterval: 15_000 },
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const { data: detail, error: detailError } = useSWR<RunDetail, Error>(
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
        eyebrow="Observability"
        title="Runs & audit"
        description="Inspect stages, retries, sanitized evidence, outputs, and correlation IDs."
      />
      <section className="panel list-controls" aria-label="Run filters">
        <label>
          <span>Status</span>
          <select
            aria-label="Filter runs by status"
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="waiting_approval">Waiting approval</option>
            <option value="executing">Executing</option>
          </select>
        </label>
        <span>
          {data ? `${String(data.total)} runs` : "Loading run count…"}
        </span>
        <button
          className="button secondary compact"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
          type="button"
        >
          Previous
        </button>
        <button
          className="button secondary compact"
          disabled={!data || offset + PAGE_SIZE >= data.total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          type="button"
        >
          Next
        </button>
      </section>
      {error ? (
        <p className="error-banner" role="alert">
          Unable to load runs: {String(error)}
        </p>
      ) : null}
      {detailError ? (
        <p className="error-banner" role="alert">
          Unable to refresh the selected run timeline.
        </p>
      ) : null}
      <section className="panel">
        <DataTable
          columns={[
            {
              key: "run",
              label: "Run",
              render: (item) => (
                <button
                  className="link-button"
                  onClick={() => setSelectedRunId(item.run_id)}
                  type="button"
                >
                  <code>{compactId(item.run_id)}</code>
                </button>
              ),
            },
            { key: "agent", label: "Agent", render: (item) => item.agent_id },
            {
              key: "status",
              label: "Status",
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "trigger",
              label: "Initiator",
              render: (item) => `${item.trigger} · ${item.initiated_by}`,
            },
            {
              key: "start",
              label: "Started",
              render: (item) => formatDate(item.started_at),
            },
            {
              key: "correlation",
              label: "Correlation",
              render: (item) => <code>{compactId(item.correlation_id)}</code>,
            },
          ]}
          items={runs}
          getKey={(item) => item.run_id}
          empty={
            <EmptyState
              title={isLoading ? "Loading runs" : "No runs"}
              detail={
                isLoading
                  ? "Retrieving the operational timeline."
                  : "No runs match the current filter."
              }
            />
          }
        />
      </section>
      {selectedRunId ? (
        <section className="panel run-detail">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Run timeline</p>
              <h2>{compactId(selectedRunId)}</h2>
            </div>
            {detail ? <StatusBadge status={detail.run.status} /> : null}
          </div>
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
              <dt>Correlation ID</dt>
              <dd>
                <code>{detail?.run.correlation_id ?? "…"}</code>
              </dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{formatDuration(duration)}</dd>
            </div>
            <div>
              <dt>Retries</dt>
              <dd>{detail?.run.retry_count ?? "…"}</dd>
            </div>
            <div>
              <dt>Initiated by</dt>
              <dd>
                {detail
                  ? `${detail.run.trigger} · ${detail.run.initiated_by}`
                  : "…"}
              </dd>
            </div>
            <div>
              <dt>Snapshots</dt>
              <dd>{detail?.snapshots.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Findings</dt>
              <dd>{detail?.findings.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Recommendations</dt>
              <dd>{detail?.recommendations.length ?? "…"}</dd>
            </div>
            <div>
              <dt>Action proposals</dt>
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
            <summary>Sanitized timeline details</summary>
            <pre>
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
            <summary>Input snapshots</summary>
            <pre>
              {JSON.stringify(
                redactForDisplay(detail?.snapshots ?? []),
                null,
                2,
              )}
            </pre>
          </details>
          <details className="inspection-block">
            <summary>Structured outputs</summary>
            <pre>
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
