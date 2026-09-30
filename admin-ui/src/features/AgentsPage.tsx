"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import {
  apiPost,
  apiPut,
  type AgentDetail,
  type AgentPage,
  type Configuration,
  type ReportPage,
  type RunPage,
  type Schedule,
} from "../api/client";
import { hasRole, useSession } from "../auth/SessionContext";
import { EmptyState } from "../components/EmptyState";
import { ConfirmAction } from "../components/ConfirmAction";
import { PageHeader } from "../components/PageHeader";
import {
  ScheduleEditor,
  type ScheduleValues,
} from "../components/ScheduleEditor";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, isRecord } from "../ui/format";
import { descriptionFor, labelFor } from "../ui/labels";

export function AgentsPage(): React.JSX.Element {
  const { session } = useSession();
  const canAdminister = hasRole(session, "admin");
  const {
    data: agents,
    error: agentsError,
    isLoading: agentsLoading,
  } = useSWR<AgentPage, Error>("/api/v1/admin/operation/agents", {
    refreshInterval: 30_000,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedCapability, setSelectedCapability] = useState<string | null>(
    null,
  );
  const { data: detail, error: detailError } = useSWR<AgentDetail, Error>(
    selectedId ? `/api/v1/admin/operation/agents/${selectedId}` : null,
    { refreshInterval: 15_000 },
  );
  const { data: schema } = useSWR<Record<string, unknown>>(
    selectedId
      ? `/api/v1/admin/operation/agents/${selectedId}/configuration-schema${selectedCapability ? `?capability_key=${encodeURIComponent(selectedCapability)}` : ""}`
      : null,
  );
  const { data: runs } = useSWR<RunPage>(
    selectedId
      ? `/api/v1/admin/operation/runs?agent_id=${selectedId}${selectedCapability ? `&capability_key=${encodeURIComponent(selectedCapability)}` : ""}&limit=5`
      : null,
  );
  const { data: reports } = useSWR<ReportPage>(
    selectedId
      ? `/api/v1/admin/operation/reports?agent_id=${selectedId}${selectedCapability ? `&capability_key=${encodeURIComponent(selectedCapability)}` : ""}&limit=5`
      : null,
  );
  const { mutate } = useSWRConfig();
  const [configurationText, setConfigurationText] = useState<string | null>(
    null,
  );
  const [message, setMessage] = useState<string | null>(null);
  const effectiveCapability =
    selectedCapability ?? detail?.agent.default_capability_key ?? null;
  const activeConfiguration = (detail?.configurations ?? []).find(
    (item) => item.capability_key === effectiveCapability && item.active,
  );
  const activeConfigurationText = activeConfiguration
    ? JSON.stringify(activeConfiguration.values, null, 2)
    : "";

  async function changeStatus(
    action: "enable" | "disable" | "pause" | "resume",
  ): Promise<void> {
    if (!selectedId || !effectiveCapability) return;
    try {
      await apiPost(
        `/api/v1/admin/operation/agents/${selectedId}/${action}`,
        {},
      );
      await Promise.all([
        mutate("/api/v1/admin/operation/agents"),
        mutate(`/api/v1/admin/operation/agents/${selectedId}`),
      ]);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Не удалось изменить состояние агента",
      );
    }
  }

  async function saveConfiguration(): Promise<void> {
    if (!selectedId || !effectiveCapability) return;
    try {
      const parsed: unknown = JSON.parse(
        configurationText ?? activeConfigurationText,
      );
      if (!isRecord(parsed))
        throw new Error("Настройки должны быть объектом JSON");
      const saved = await apiPost<Configuration>(
        `/api/v1/admin/operation/agents/${selectedId}/configurations?capability_key=${encodeURIComponent(effectiveCapability)}`,
        { values: parsed },
      );
      setMessage(`Сохранена версия настроек ${String(saved.version)}.`);
      await mutate(`/api/v1/admin/operation/agents/${selectedId}`);
      setConfigurationText(null);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Некорректные настройки",
      );
    }
  }

  async function toggleKillSwitch(): Promise<void> {
    if (!selectedId || !detail) return;
    try {
      await apiPut(`/api/v1/admin/operation/kill-switch/agents/${selectedId}`, {
        enabled: !detail.kill_switch_enabled,
      });
      await mutate(`/api/v1/admin/operation/agents/${selectedId}`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Не удалось изменить остановку агента",
      );
    }
  }

  async function toggleCapabilityKillSwitch(): Promise<void> {
    if (!selectedId || !detail || !effectiveCapability) return;
    const enabled =
      detail.capability_kill_switches[effectiveCapability] ?? false;
    try {
      await apiPut(
        `/api/v1/admin/operation/kill-switch/agents/${selectedId}/capabilities/${encodeURIComponent(effectiveCapability)}`,
        { enabled: !enabled },
      );
      await mutate(`/api/v1/admin/operation/agents/${selectedId}`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Не удалось остановить возможность агента",
      );
    }
  }

  async function saveSchedule(
    schedule: Schedule,
    values: ScheduleValues,
  ): Promise<void> {
    await apiPut(
      `/api/v1/admin/operation/schedules/${schedule.schedule_id}`,
      values,
    );
    await Promise.all([
      mutate(`/api/v1/admin/operation/agents/${schedule.agent_id}`),
      mutate("/api/v1/admin/operation/dashboard"),
    ]);
    setMessage(`Расписание «${labelFor(schedule.job_type)}» обновлено.`);
  }

  const properties = isRecord(schema?.properties)
    ? Object.keys(schema.properties).length
    : 0;
  return (
    <>
      <PageHeader
        eyebrow="Каталог"
        title="Управление агентами"
        description="Возможности агентов, состояние источников, настройки, расписание и история работы."
      />
      {agentsError || detailError ? (
        <p className="error-banner" role="alert">
          Не удалось обновить данные агентов. Ограничения действий продолжают
          действовать на сервере.
        </p>
      ) : null}
      {agentsLoading ? (
        <p className="notice" role="status">
          Загружаем список агентов…
        </p>
      ) : null}
      <div className="management-layout">
        <aside className="agent-list panel" aria-label="Подключено агентов">
          {(agents?.items ?? []).map((agent) => (
            <button
              className={
                selectedId === agent.agent_id
                  ? "agent-button active"
                  : "agent-button"
              }
              key={agent.agent_id}
              aria-pressed={selectedId === agent.agent_id}
              onClick={() => {
                setSelectedId(agent.agent_id);
                setSelectedCapability(agent.default_capability_key);
                setConfigurationText(null);
              }}
              type="button"
            >
              <span>
                <strong>{labelFor(agent.agent_id)}</strong>
                <small>{agent.version}</small>
              </span>
              <StatusBadge status={agent.status} />
            </button>
          ))}
          {agents && !agentsError && agents.items.length === 0 ? (
            <EmptyState
              title="Агентов пока нет"
              detail="Подключённых агентов пока нет."
            />
          ) : null}
        </aside>
        <section className="panel configuration-panel">
          {detail ? (
            <>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Настройки агента</p>
                  <h2>{labelFor(detail.agent.agent_id)}</h2>
                </div>
                <StatusBadge status={detail.agent.status} />
              </div>
              <p>{descriptionFor(detail.agent.agent_id)}</p>
              <div className="health-list">
                {detail.integration_health.map((health) => (
                  <div key={health.integration_id}>
                    <span>
                      <strong>{labelFor(health.integration_id)}</strong>
                      <small>
                        {health.diagnostics?.observation === "missing"
                          ? "Сохранённой проверки нет"
                          : `Последняя проверка: ${formatDate(health.checked_at)}`}
                      </small>
                    </span>
                    <StatusBadge status={health.status} />
                  </div>
                ))}
              </div>
              <div className="button-row">
                {(["enable", "pause", "resume", "disable"] as const).map(
                  (action) => (
                    <button
                      className="button secondary compact"
                      disabled={!canAdminister}
                      key={action}
                      onClick={() => void changeStatus(action)}
                      type="button"
                    >
                      {labelFor(action)}
                    </button>
                  ),
                )}
                <ConfirmAction
                  className={
                    detail.kill_switch_enabled ? "button" : "button danger"
                  }
                  confirmLabel={
                    detail.kill_switch_enabled
                      ? "Подтвердить возобновление"
                      : "Подтвердить остановку"
                  }
                  disabled={!canAdminister}
                  label={
                    detail.kill_switch_enabled
                      ? "Возобновить действия агента"
                      : "Остановить агента"
                  }
                  onConfirm={() => void toggleKillSwitch()}
                />
              </div>
              <h3>Возможности</h3>
              <div className="capability-list">
                {detail.agent.capabilities.map((capability) => (
                  <button
                    className={
                      effectiveCapability === capability.key
                        ? "agent-button active"
                        : "agent-button"
                    }
                    key={capability.key}
                    onClick={() => {
                      setSelectedCapability(capability.key);
                      setConfigurationText(null);
                    }}
                    type="button"
                  >
                    <span>
                      <strong>{labelFor(capability.key)}</strong>
                      <small>{descriptionFor(capability.key)}</small>
                    </span>
                    <StatusBadge status={capability.risk} />
                  </button>
                ))}
              </div>
              {effectiveCapability ? (
                <div className="button-row">
                  <StatusBadge
                    status={
                      detail.capability_kill_switches[effectiveCapability]
                        ? "stopped"
                        : "armed"
                    }
                  />
                  <ConfirmAction
                    className={
                      detail.capability_kill_switches[effectiveCapability]
                        ? "button"
                        : "button danger"
                    }
                    confirmLabel={
                      detail.capability_kill_switches[effectiveCapability]
                        ? "Подтвердить возобновление"
                        : "Подтвердить остановку"
                    }
                    disabled={!canAdminister}
                    label={
                      detail.capability_kill_switches[effectiveCapability]
                        ? "Возобновить возможность"
                        : "Остановить возможность"
                    }
                    onConfirm={() => void toggleCapabilityKillSwitch()}
                  />
                </div>
              ) : null}
              <div className="section-heading">
                <h3>Настройки агента</h3>
                <span>Параметров: {properties}</span>
              </div>
              <details>
                <summary>Расширенные настройки (JSON)</summary>
                <label className="field">
                  <span>Настройки в формате JSON</span>
                  <textarea
                    className="code-editor"
                    disabled={!canAdminister}
                    onChange={(event) =>
                      setConfigurationText(event.target.value)
                    }
                    value={configurationText ?? activeConfigurationText}
                  />
                </label>
              </details>
              {message ? (
                <p className="notice" role="status">
                  {message}
                </p>
              ) : null}
              <button
                className="button"
                disabled={!canAdminister}
                onClick={() => void saveConfiguration()}
                type="button"
              >
                Проверить и сохранить настройки
              </button>
              <h3>Расписание</h3>
              <div className="schedule-editors">
                {detail.schedules
                  .filter(
                    (schedule) =>
                      schedule.capability_key === effectiveCapability,
                  )
                  .map((schedule) => (
                    <ScheduleEditor
                      disabled={!canAdminister}
                      key={`${schedule.schedule_id}:${schedule.cron_expression}:${schedule.timezone}:${String(schedule.enabled)}`}
                      onSave={saveSchedule}
                      schedule={schedule}
                    />
                  ))}
              </div>
              <div className="section-heading">
                <h3>Последние запуски</h3>
                <span>Всего: {runs?.total ?? 0}</span>
              </div>
              <div className="compact-history">
                {(runs?.items ?? []).map((run) => (
                  <div key={run.run_id}>
                    <code>{run.run_id}</code>
                    <StatusBadge status={run.status} />
                    <time>{formatDate(run.started_at)}</time>
                  </div>
                ))}
                {(runs?.items.length ?? 0) === 0 ? (
                  <span className="muted">Запусков пока нет.</span>
                ) : null}
              </div>
              <div className="section-heading">
                <h3>Последние отчёты</h3>
                <span>Всего: {reports?.total ?? 0}</span>
              </div>
              <div className="compact-history">
                {(reports?.items ?? []).map((report) => (
                  <div key={report.report_id}>
                    <code>{report.report_id}</code>
                    <StatusBadge status={report.report_type} />
                    <time>{formatDate(report.created_at)}</time>
                  </div>
                ))}
                {(reports?.items.length ?? 0) === 0 ? (
                  <span className="muted">Отчётов пока нет.</span>
                ) : null}
              </div>
            </>
          ) : (
            <EmptyState
              title="Выберите агента"
              detail="Выберите агента, чтобы посмотреть его возможности, настройки и расписание."
            />
          )}
        </section>
      </div>
    </>
  );
}
