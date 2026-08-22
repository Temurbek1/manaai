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
        error instanceof Error ? error.message : "Agent status update failed",
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
        throw new Error("Configuration must be a JSON object");
      const saved = await apiPost<Configuration>(
        `/api/v1/admin/operation/agents/${selectedId}/configurations?capability_key=${encodeURIComponent(effectiveCapability)}`,
        { values: parsed },
      );
      setMessage(`Configuration version ${String(saved.version)} activated.`);
      await mutate(`/api/v1/admin/operation/agents/${selectedId}`);
      setConfigurationText(null);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Configuration is invalid",
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
          : "Agent kill switch update failed",
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
          : "Capability kill switch update failed",
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
    setMessage(`${schedule.job_type} schedule updated.`);
  }

  const properties = isRecord(schema?.properties)
    ? Object.keys(schema.properties).length
    : 0;
  return (
    <>
      <PageHeader
        eyebrow="Registry"
        title="Agent management"
        description="Generic controls, typed configuration, capabilities, schedules, health, and history."
      />
      {agentsError || detailError ? (
        <p className="error-banner" role="alert">
          Unable to refresh agent management data. Existing mutation controls
          remain guarded by the API.
        </p>
      ) : null}
      {agentsLoading ? (
        <p className="notice" role="status">
          Loading the agent registry…
        </p>
      ) : null}
      <div className="management-layout">
        <aside className="agent-list panel" aria-label="Registered agents">
          {(agents?.items ?? []).map((agent) => (
            <button
              className={
                selectedId === agent.agent_id
                  ? "agent-button active"
                  : "agent-button"
              }
              key={agent.agent_id}
              onClick={() => {
                setSelectedId(agent.agent_id);
                setSelectedCapability(agent.default_capability_key);
                setConfigurationText(null);
              }}
              type="button"
            >
              <span>
                <strong>{agent.display_name}</strong>
                <small>{agent.version}</small>
              </span>
              <StatusBadge status={agent.status} />
            </button>
          ))}
          {(agents?.items.length ?? 0) === 0 ? (
            <EmptyState title="No agents" detail="The registry is empty." />
          ) : null}
        </aside>
        <section className="panel configuration-panel">
          {detail ? (
            <>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">{detail.agent.agent_id}</p>
                  <h2>{detail.agent.display_name}</h2>
                </div>
                <StatusBadge status={detail.agent.status} />
              </div>
              <p>{detail.agent.description}</p>
              <div className="health-list">
                {detail.integration_health.map((health) => (
                  <div key={health.integration_id}>
                    <span>
                      <strong>{health.integration_id}</strong>
                      <small>{health.message ?? "No diagnostic message"}</small>
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
                      {action}
                    </button>
                  ),
                )}
                <ConfirmAction
                  className={
                    detail.kill_switch_enabled ? "button" : "button danger"
                  }
                  confirmLabel={
                    detail.kill_switch_enabled
                      ? "Confirm re-arm"
                      : "Confirm emergency stop"
                  }
                  disabled={!canAdminister}
                  label={
                    detail.kill_switch_enabled
                      ? "Re-arm agent actions"
                      : "Emergency stop agent"
                  }
                  onConfirm={() => void toggleKillSwitch()}
                />
              </div>
              <h3>Capabilities</h3>
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
                      <strong>{capability.key}</strong>
                      <small>{capability.description}</small>
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
                        ? "Confirm capability re-arm"
                        : "Confirm capability stop"
                    }
                    disabled={!canAdminister}
                    label={
                      detail.capability_kill_switches[effectiveCapability]
                        ? "Re-arm capability"
                        : "Emergency stop capability"
                    }
                    onConfirm={() => void toggleCapabilityKillSwitch()}
                  />
                </div>
              ) : null}
              <div className="section-heading">
                <h3>Typed configuration</h3>
                <span>{properties} schema fields</span>
              </div>
              <label className="field">
                <span>Active JSON values</span>
                <textarea
                  className="code-editor"
                  disabled={!canAdminister}
                  onChange={(event) => setConfigurationText(event.target.value)}
                  value={configurationText ?? activeConfigurationText}
                />
              </label>
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
                Validate & activate version
              </button>
              <h3>Schedules</h3>
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
                <h3>Recent runs</h3>
                <span>{runs?.total ?? 0} total</span>
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
                  <span className="muted">No runs yet.</span>
                ) : null}
              </div>
              <div className="section-heading">
                <h3>Recent reports</h3>
                <span>{reports?.total ?? 0} total</span>
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
                  <span className="muted">No reports yet.</span>
                ) : null}
              </div>
            </>
          ) : (
            <EmptyState
              title="Select an agent"
              detail="Choose an agent to manage its contract and schedules."
            />
          )}
        </section>
      </div>
    </>
  );
}
