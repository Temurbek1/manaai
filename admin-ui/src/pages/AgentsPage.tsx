import { useEffect, useState } from "react";
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
import { PageHeader } from "../components/PageHeader";
import { ScheduleEditor, type ScheduleValues } from "../components/ScheduleEditor";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, isRecord } from "../ui/format";

export function AgentsPage(): React.JSX.Element {
  const { session } = useSession();
  const canAdminister = hasRole(session, "admin");
  const { data: agents } = useSWR<AgentPage>("/api/v1/admin/operation/agents");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: detail } = useSWR<AgentDetail>(
    selectedId ? `/api/v1/admin/operation/agents/${selectedId}` : null,
  );
  const { data: schema } = useSWR<Record<string, unknown>>(
    selectedId ? `/api/v1/admin/operation/agents/${selectedId}/configuration-schema` : null,
  );
  const { data: runs } = useSWR<RunPage>(
    selectedId ? `/api/v1/admin/operation/runs?agent_id=${selectedId}&limit=5` : null,
  );
  const { data: reports } = useSWR<ReportPage>(
    selectedId ? `/api/v1/admin/operation/reports?agent_id=${selectedId}&limit=5` : null,
  );
  const { mutate } = useSWRConfig();
  const [configurationText, setConfigurationText] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (detail?.configuration) {
      setConfigurationText(JSON.stringify(detail.configuration.values, null, 2));
    }
  }, [detail?.configuration]);

  async function changeStatus(action: "enable" | "disable" | "pause" | "resume"): Promise<void> {
    if (!selectedId) return;
    try {
      await apiPost(`/api/v1/admin/operation/agents/${selectedId}/${action}`, {});
      await Promise.all([
        mutate("/api/v1/admin/operation/agents"),
        mutate(`/api/v1/admin/operation/agents/${selectedId}`),
      ]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent status update failed");
    }
  }

  async function saveConfiguration(): Promise<void> {
    if (!selectedId) return;
    try {
      const parsed: unknown = JSON.parse(configurationText);
      if (!isRecord(parsed)) throw new Error("Configuration must be a JSON object");
      const saved = await apiPost<Configuration>(
        `/api/v1/admin/operation/agents/${selectedId}/configurations`,
        { values: parsed },
      );
      setMessage(`Configuration version ${String(saved.version)} activated.`);
      await mutate(`/api/v1/admin/operation/agents/${selectedId}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Configuration is invalid");
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
      setMessage(error instanceof Error ? error.message : "Agent kill switch update failed");
    }
  }

  async function saveSchedule(schedule: Schedule, values: ScheduleValues): Promise<void> {
    await apiPut(`/api/v1/admin/operation/schedules/${schedule.schedule_id}`, values);
    await Promise.all([
      mutate(`/api/v1/admin/operation/agents/${schedule.agent_id}`),
      mutate("/api/v1/admin/operation/dashboard"),
    ]);
    setMessage(`${schedule.job_type} schedule updated.`);
  }

  const properties = isRecord(schema?.properties) ? Object.keys(schema.properties).length : 0;
  return (
    <>
      <PageHeader
        eyebrow="Registry"
        title="Agent management"
        description="Generic controls, typed configuration, capabilities, schedules, health, and history."
      />
      <div className="management-layout">
        <aside className="agent-list panel" aria-label="Registered agents">
          {(agents?.items ?? []).map((agent) => (
            <button
              className={selectedId === agent.agent_id ? "agent-button active" : "agent-button"}
              key={agent.agent_id}
              onClick={() => setSelectedId(agent.agent_id)}
              type="button"
            >
              <span><strong>{agent.display_name}</strong><small>{agent.version}</small></span>
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
                <div><p className="eyebrow">{detail.agent.agent_id}</p><h2>{detail.agent.display_name}</h2></div>
                <StatusBadge status={detail.agent.status} />
              </div>
              <p>{detail.agent.description}</p>
              <div className="health-list">
                {detail.integration_health.map((health) => (
                  <div key={health.integration_id}>
                    <span><strong>{health.integration_id}</strong><small>{health.message ?? "No diagnostic message"}</small></span>
                    <StatusBadge status={health.status} />
                  </div>
                ))}
              </div>
              <div className="button-row">
                {(["enable", "pause", "resume", "disable"] as const).map((action) => (
                  <button className="button secondary compact" disabled={!canAdminister} key={action} onClick={() => void changeStatus(action)} type="button">
                    {action}
                  </button>
                ))}
                <button
                  className={detail.kill_switch_enabled ? "button" : "button danger"}
                  disabled={!canAdminister}
                  onClick={() => void toggleKillSwitch()}
                  type="button"
                >
                  {detail.kill_switch_enabled ? "Re-arm agent actions" : "Emergency stop agent"}
                </button>
              </div>
              <h3>Capabilities</h3>
              <div className="capability-list">
                {detail.agent.capabilities.map((capability) => (
                  <div key={capability.key}><strong>{capability.key}</strong><span>{capability.description}</span><StatusBadge status={capability.risk} /></div>
                ))}
              </div>
              <div className="section-heading"><h3>Typed configuration</h3><span>{properties} schema fields</span></div>
              <label className="field">
                <span>Active JSON values</span>
                <textarea className="code-editor" disabled={!canAdminister} onChange={(event) => setConfigurationText(event.target.value)} value={configurationText} />
              </label>
              {message ? <p className="notice" role="status">{message}</p> : null}
              <button className="button" disabled={!canAdminister} onClick={() => void saveConfiguration()} type="button">Validate & activate version</button>
              <h3>Schedules</h3>
              <div className="schedule-editors">
                {detail.schedules.map((schedule) => (
                  <ScheduleEditor
                    disabled={!canAdminister}
                    key={schedule.schedule_id}
                    onSave={saveSchedule}
                    schedule={schedule}
                  />
                ))}
              </div>
              <div className="section-heading"><h3>Recent runs</h3><span>{runs?.total ?? 0} total</span></div>
              <div className="compact-history">
                {(runs?.items ?? []).map((run) => (
                  <div key={run.run_id}>
                    <code>{run.run_id}</code><StatusBadge status={run.status} /><time>{formatDate(run.started_at)}</time>
                  </div>
                ))}
                {(runs?.items.length ?? 0) === 0 ? <span className="muted">No runs yet.</span> : null}
              </div>
              <div className="section-heading"><h3>Recent reports</h3><span>{reports?.total ?? 0} total</span></div>
              <div className="compact-history">
                {(reports?.items ?? []).map((report) => (
                  <div key={report.report_id}>
                    <code>{report.report_id}</code><StatusBadge status={report.report_type} /><time>{formatDate(report.created_at)}</time>
                  </div>
                ))}
                {(reports?.items.length ?? 0) === 0 ? <span className="muted">No reports yet.</span> : null}
              </div>
            </>
          ) : (
            <EmptyState title="Select an agent" detail="Choose an agent to manage its contract and schedules." />
          )}
        </section>
      </div>
    </>
  );
}
