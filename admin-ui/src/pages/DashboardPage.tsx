import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { apiPost, apiPut, type Dashboard } from "../api/client";
import { hasRole, useSession } from "../auth/SessionContext";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, formatDuration } from "../ui/format";

export function DashboardPage(): React.JSX.Element {
  const { session } = useSession();
  const canRun = hasRole(session, "operator");
  const canAdminister = hasRole(session, "admin");
  const { data, error, isLoading } = useSWR<Dashboard, Error>(
    "/api/v1/admin/operation/dashboard",
  );
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function toggleKillSwitch(): Promise<void> {
    if (!data || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await apiPut("/api/v1/admin/operation/kill-switch/global", {
        enabled: !data.global_kill_switch,
      });
      await mutate("/api/v1/admin/operation/dashboard");
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Safety control update failed");
    } finally {
      setBusy(false);
    }
  }

  async function runAgent(agentId: string): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await apiPost(`/api/v1/admin/operation/agents/${agentId}/run`, {
        job_type: "analysis",
      });
      await mutate("/api/v1/admin/operation/dashboard");
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Agent run request failed");
    } finally {
      setBusy(false);
    }
  }

  const agents = data?.agents ?? [];
  const pending = agents.reduce((total, item) => total + item.pending_approvals, 0);
  const incidents = agents.reduce((total, item) => total + item.recent_incidents, 0);
  return (
    <>
      <PageHeader
        eyebrow="Control room"
        title="Operation overview"
        description="Live agent health, approvals, schedules, and operational safeguards."
        actions={
          <button
            className={data?.global_kill_switch ? "button danger" : "button secondary"}
            aria-description={canAdminister ? undefined : "Admin role required"}
            disabled={!data || busy || !canAdminister}
            onClick={() => void toggleKillSwitch()}
            type="button"
          >
            {data?.global_kill_switch ? "Disable kill switch" : "Emergency stop"}
          </button>
        }
      />
      {error ? <p className="error-banner">Unable to load dashboard: {String(error)}</p> : null}
      {actionError ? <p className="error-banner" role="alert">{actionError}</p> : null}
      <section className="metric-grid" aria-label="Operational metrics">
        <MetricCard label="Registered agents" value={isLoading ? "…" : agents.length} />
        <MetricCard label="Pending approvals" value={pending} accent="amber" />
        <MetricCard label="Recent incidents" value={incidents} accent="rose" />
        <MetricCard
          label="Global safety"
          value={data?.global_kill_switch ? "Stopped" : "Armed"}
          detail="Real Meta writes remain opt-in"
          accent="blue"
        />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Agent registry</p>
            <h2>Operational agents</h2>
          </div>
          <span className="muted">Updated {formatDate(data?.generated_at)}</span>
        </div>
        <DataTable
          columns={[
            {
              key: "agent",
              label: "Agent",
              render: (item) => (
                <div className="primary-cell">
                  <strong>{item.display_name}</strong>
                  <span>{item.agent_id}</span>
                </div>
              ),
            },
            { key: "status", label: "Status", render: (item) => <StatusBadge status={item.status} /> },
            { key: "health", label: "Health", render: (item) => <StatusBadge status={item.health} /> },
            { key: "last", label: "Last run", render: (item) => formatDate(item.last_run) },
            { key: "next", label: "Next run", render: (item) => formatDate(item.next_run) },
            {
              key: "duration",
              label: "Duration",
              render: (item) => formatDuration(item.last_duration_ms),
            },
            { key: "success", label: "Success", render: (item) => item.success_rate },
            {
              key: "actions",
              label: "",
              render: (item) => (
                <button
                  className="button compact"
                  aria-description={canRun ? undefined : "Operator role required"}
                  disabled={busy || item.status !== "enabled" || !canRun}
                  onClick={() => void runAgent(item.agent_id)}
                  type="button"
                >
                  Run now
                </button>
              ),
            },
          ]}
          items={agents}
          getKey={(item) => item.agent_id}
          empty={<EmptyState title="No agents" detail="Register an agent to start operations." />}
        />
      </section>
    </>
  );
}
