import { useState } from "react";
import useSWR from "swr";

import type {
  AdEntity,
  ExecutionPage,
  FindingPage,
  MarketingOverview,
  ProposalPage,
  RecommendationPage,
  ReportPage,
  RunPage,
} from "../api/client";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { MarketingEntityTable } from "../components/MarketingEntityTable";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { PerformanceBreakdownTable } from "../components/PerformanceBreakdownTable";
import { StatusBadge } from "../components/StatusBadge";
import { compactId, displayValue, formatDate, isRecord } from "../ui/format";

export function MarketingPage(): React.JSX.Element {
  const [entityQuery, setEntityQuery] = useState("");
  const [deliveryStatus, setDeliveryStatus] = useState("all");
  const [selectedStart, setSelectedStart] = useState("");
  const [selectedEnd, setSelectedEnd] = useState("");
  const { data: overview } = useSWR<MarketingOverview>(
    "/api/v1/admin/operation/marketing/overview",
  );
  const { data: runs } = useSWR<RunPage>(
    "/api/v1/admin/operation/runs?agent_id=marketing-agent&limit=20",
  );
  const latestRun = runs?.items[0];
  const runFilter = latestRun ? `?run_id=${latestRun.run_id}&limit=100` : null;
  const { data: findings } = useSWR<FindingPage>(
    runFilter ? `/api/v1/admin/operation/findings${runFilter}` : null,
  );
  const { data: recommendations } = useSWR<RecommendationPage>(
    runFilter ? `/api/v1/admin/operation/recommendations${runFilter}` : null,
  );
  const { data: proposals } = useSWR<ProposalPage>(
    "/api/v1/admin/operation/action-proposals?status=awaiting_approval&limit=100",
  );
  const { data: executions } = useSWR<ExecutionPage>(
    "/api/v1/admin/operation/executions?agent_id=marketing-agent&limit=100",
  );
  const { data: reports } = useSWR<ReportPage>(
    "/api/v1/admin/operation/reports?agent_id=marketing-agent&limit=20",
  );
  const latestReport = reports?.items[0];
  const structured = latestReport && isRecord(latestReport.structured) ? latestReport.structured : {};
  const kpis = isRecord(structured.kpis) ? structured.kpis : {};
  const snapshot = overview?.snapshot;
  const liveReadOnly = snapshot?.provider_mode === "live_read_only";
  const account = snapshot ? snapshot.accounts[0] : undefined;
  const healthDiagnostics = isRecord(overview?.integration_health.diagnostics)
    ? overview.integration_health.diagnostics
    : {};
  const credentialHealth = isRecord(healthDiagnostics.token) ? healthDiagnostics.token : {};
  const requestBudget = snapshot?.request_budget;
  const observability = snapshot?.observability;
  const defaultStart = snapshot ? snapshot.period_start.slice(0, 10) : "";
  const defaultEnd = snapshot ? snapshot.period_end.slice(0, 10) : "";
  const periodStart = selectedStart || defaultStart;
  const periodEnd = selectedEnd || defaultEnd;
  const normalizedQuery = entityQuery.trim().toLowerCase();
  const filterEntities = (entities: readonly AdEntity[]): AdEntity[] =>
    entities.filter(
      (entity) =>
        (deliveryStatus === "all" || entity.effective_status === deliveryStatus) &&
        (!normalizedQuery ||
          entity.name.toLowerCase().includes(normalizedQuery) ||
          entity.provider_id.toLowerCase().includes(normalizedQuery)),
    );
  const filteredCampaigns = filterEntities(snapshot?.campaigns ?? []);
  const filteredAdSets = filterEntities(snapshot?.ad_sets ?? []);
  const filteredAds = filterEntities(snapshot?.ads ?? []);
  const insightRows = (snapshot?.insights ?? []).filter(
    (row) =>
      (!periodStart || row.date_stop >= periodStart) &&
      (!periodEnd || row.date_start <= periodEnd),
  );
  const deliveryStatuses = Array.from(
    new Set(
      [...(snapshot?.campaigns ?? []), ...(snapshot?.ad_sets ?? []), ...(snapshot?.ads ?? [])]
        .map((entity) => entity.effective_status)
        .filter(Boolean),
    ),
  ).sort();
  const findingItems = findings?.items ?? [];
  const recommendationItems = recommendations?.items ?? [];
  const rankingByObject = new Map(
    findingItems
      .filter((finding) => finding.provider_object_id !== null)
      .map((finding) => [finding.provider_object_id ?? "", finding.finding_type]),
  );

  return (
    <>
      <PageHeader
        eyebrow="Marketing Agent"
        title="Meta Ads intelligence"
        description="Verified performance signals, complete provider snapshots, recommendations, and controlled execution history."
        actions={overview ? <StatusBadge status={overview.integration_health.status} /> : null}
      />
      <section className="metric-grid">
        <MetricCard label="Spend" value={displayValue(kpis.spend)} />
        <MetricCard label="Leads" value={displayValue(kpis.leads)} accent="blue" />
        <MetricCard label="CTR" value={displayValue(kpis.ctr)} detail="Percent" />
        <MetricCard label="CPL" value={displayValue(kpis.cpl)} accent="amber" />
        <MetricCard label="ROAS" value={displayValue(kpis.roas)} accent="blue" />
        <MetricCard
          label="Account context"
          value={account?.currency ?? "unavailable"}
          detail={`${account?.timezone ?? "unavailable"} · ${snapshot?.attribution_window ?? "unavailable"}`}
        />
        <MetricCard
          label="Last synchronization"
          value={formatDate(overview?.last_synchronized_at)}
          detail={overview?.integration_health.message ?? "Integration health pending"}
          accent="rose"
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Integration health</p><h2>Meta connection</h2></div>
          <StatusBadge status={liveReadOnly ? "live read only" : snapshot?.provider_mode ?? "pending"} />
        </div>
        <dl className="detail-grid health-detail-grid">
          <div><dt>Read-only mode</dt><dd>{liveReadOnly ? "Enforced" : "No"}</dd></div>
          <div><dt>Graph API</dt><dd>{snapshot?.api_version ?? displayValue(healthDiagnostics.api_version)}</dd></div>
          <div><dt>Credential health</dt><dd>{credentialHealth.is_valid === true ? "Valid" : "Unavailable"}</dd></div>
          <div><dt>Permissions</dt><dd>{Array.isArray(credentialHealth.scopes) ? credentialHealth.scopes.join(", ") : "unavailable"}</dd></div>
          <div><dt>Selected account</dt><dd>{displayValue(healthDiagnostics.selected_account_alias)}</dd></div>
          <div><dt>Currency / timezone</dt><dd>{account?.currency ?? "unavailable"} / {account?.timezone ?? "unavailable"}</dd></div>
          <div><dt>Last successful request</dt><dd>{formatDate(overview?.integration_health.last_success_at)}</dd></div>
          <div><dt>Last synchronization</dt><dd>{formatDate(overview?.last_synchronized_at)}</dd></div>
          <div><dt>Rate-limit usage</dt><dd>{displayValue(healthDiagnostics.rate_limit_usage_percent)}%</dd></div>
          <div><dt>Request budget</dt><dd>{displayValue(requestBudget?.requests_used)} / {displayValue(requestBudget?.max_requests)} requests</dd></div>
          <div><dt>Pages / retries</dt><dd>{displayValue(requestBudget?.pages_fetched)} / {displayValue(requestBudget?.retries_used)}</dd></div>
          <div><dt>Data freshness</dt><dd>{observability?.data_freshness_days ?? "unavailable"} days</dd></div>
        </dl>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Live data browser</p><h2>Filters and analysis period</h2></div><span className="counter">{insightRows.length}</span></div>
        <div className="live-browser-filters">
          <label><span>Search entities</span><input value={entityQuery} onChange={(event) => setEntityQuery(event.target.value)} placeholder="Name or object ID" /></label>
          <label><span>Delivery status</span><select value={deliveryStatus} onChange={(event) => setDeliveryStatus(event.target.value)}><option value="all">All statuses</option>{deliveryStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
          <label><span>Period start</span><input type="date" min={defaultStart} max={periodEnd || defaultEnd} value={periodStart} onChange={(event) => setSelectedStart(event.target.value)} /></label>
          <label><span>Period end</span><input type="date" min={periodStart || defaultStart} max={defaultEnd} value={periodEnd} onChange={(event) => setSelectedEnd(event.target.value)} /></label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Provider structure</p><h2>Campaigns</h2></div><span className="counter">{snapshot?.campaigns.length ?? 0}</span></div>
        <MarketingEntityTable entities={filteredCampaigns} label="Campaign" />
      </section>
      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Delivery</p><h2>Ad sets</h2></div><span className="counter">{snapshot?.ad_sets.length ?? 0}</span></div>
          <MarketingEntityTable entities={filteredAdSets} label="Ad set" />
        </section>
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Delivery</p><h2>Ads</h2></div><span className="counter">{snapshot?.ads.length ?? 0}</span></div>
          <MarketingEntityTable entities={filteredAds} label="Ad" />
        </section>
      </div>

      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Creative ranking</p><h2>Creatives</h2></div></div>
          <DataTable
            columns={[
              { key: "name", label: "Creative", render: (item) => <div className="primary-cell"><strong>{item.name}</strong><code>{compactId(item.provider_id)}</code></div> },
              { key: "format", label: "Format", render: (item) => item.format ?? "—" },
              { key: "signal", label: "Latest signal", render: (item) => <StatusBadge status={rankingByObject.get(item.provider_id) ?? "observed"} /> },
            ]}
            items={snapshot?.creatives ?? []}
            getKey={(item) => item.provider_id}
            empty={<EmptyState title="No creatives" detail="Creative metadata appears after synchronization." />}
          />
        </section>
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Audience ranking</p><h2>Audiences</h2></div></div>
          <DataTable
            columns={[
              { key: "name", label: "Audience", render: (item) => <div className="primary-cell"><strong>{item.name}</strong><code>{compactId(item.provider_id)}</code></div> },
              { key: "subtype", label: "Subtype", render: (item) => item.subtype },
              { key: "signal", label: "Latest signal", render: (item) => <StatusBadge status={rankingByObject.get(item.provider_id) ?? item.status} /> },
            ]}
            items={snapshot?.audiences ?? []}
            getKey={(item) => item.provider_id}
            empty={<EmptyState title="No audiences" detail="Available audience and targeting attributes appear after synchronization." />}
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Verified aggregation</p><h2>Region, placement, hourly, daily & demographics</h2></div><span className="counter">{overview?.breakdown_performance.length ?? 0}</span></div>
        <PerformanceBreakdownTable rows={overview?.breakdown_performance ?? []} />
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Normalized evidence</p><h2>Insight rows for selected period</h2></div><span className="counter">{insightRows.length}</span></div>
        <DataTable
          columns={[
            { key: "object", label: "Object", render: (item) => <div className="primary-cell"><strong>{item.entity_name}</strong><code>{compactId(item.entity_id)}</code></div> },
            { key: "date", label: "Date", render: (item) => item.date_stop },
            { key: "spend", label: "Spend", render: (item) => displayValue(item.metrics.spend.value) },
            { key: "impressions", label: "Impressions", render: (item) => displayValue(item.metrics.impressions.value) },
            { key: "clicks", label: "Clicks", render: (item) => displayValue(item.metrics.clicks.value) },
            { key: "results", label: "Leads / conversions", render: (item) => `${displayValue(item.metrics.leads.value)} / ${displayValue(item.metrics.conversions.value)}` },
            { key: "attribution", label: "Attribution", render: (item) => item.attribution_window },
          ]}
          items={insightRows.slice(0, 100)}
          getKey={(item) => item.row_id}
          empty={<EmptyState title="No insight rows" detail="No live rows match the selected completed period." />}
        />
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Data quality</p><h2>Compatibility and completeness</h2></div><span className="counter">{snapshot?.compatibility_matrix?.length ?? 0}</span></div>
        <DataTable
          columns={[
            { key: "operation", label: "Operation", render: (item) => item.operation },
            { key: "level", label: "Level", render: (item) => item.level ?? "—" },
            { key: "breakdowns", label: "Breakdowns", render: (item) => item.breakdowns && item.breakdowns.length > 0 ? item.breakdowns.join(", ") : "base" },
            { key: "status", label: "Status", render: (item) => <StatusBadge status={item.status} /> },
            { key: "rows", label: "Rows", render: (item) => item.row_count },
            { key: "reason", label: "Reason", render: (item) => item.reason_code ?? "—" },
          ]}
          items={snapshot?.compatibility_matrix ?? []}
          getKey={(item) => `${item.operation}:${item.level ?? "none"}:${item.breakdowns?.join("+") ?? "base"}`}
          empty={<EmptyState title="No compatibility evidence" detail="Run a live read-only synchronization to probe supported levels and breakdowns." />}
        />
        {(snapshot?.data_quality_notes?.length ?? 0) > 0 ? (
          <ul className="quality-notes">{snapshot?.data_quality_notes?.map((note) => <li key={note}>{note}</li>)}</ul>
        ) : null}
      </section>

      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Rankings & anomalies</p><h2>Findings</h2></div><span className="counter">{findingItems.length}</span></div>
          <div className="signal-list">
            {findingItems.slice(0, 12).map((finding) => (
              <article className="signal" key={finding.finding_id}>
                <div><StatusBadge status={finding.severity} /><span>{finding.finding_type}</span></div>
                <h3>{finding.title}</h3><p>{finding.description}</p>
                <dl className="detail-grid compact-detail-grid">
                  <div><dt>Confidence</dt><dd>{finding.confidence}</dd></div>
                  <div><dt>Completeness</dt><dd>{finding.completeness ?? "unavailable"}</dd></div>
                  <div><dt>Period</dt><dd>{finding.period_start?.slice(0, 10) ?? "unavailable"} – {finding.period_end?.slice(0, 10) ?? "unavailable"}</dd></div>
                  <div><dt>Attribution / currency</dt><dd>{finding.attribution_identity ?? "unavailable"} / {finding.currency ?? "unavailable"}</dd></div>
                  <div><dt>Source object</dt><dd>{finding.provider_object_id ? compactId(finding.provider_object_id) : "account"}</dd></div>
                  <div><dt>Mode</dt><dd>{snapshot?.provider_mode ?? "unavailable"}</dd></div>
                </dl>
                <div className="evidence-block">
                  <h3>Evidence</h3>
                  {finding.evidence.map((evidence) => <div key={evidence.name}><span>{evidence.name}</span><code>{evidence.current.value ?? "unavailable"}</code><small>baseline {evidence.baseline?.value ?? "unavailable"}</small></div>)}
                </div>
                {(finding.limitations?.length ?? 0) > 0 ? <small>Limitations: {finding.limitations?.join(" · ")}</small> : null}
              </article>
            ))}
            {findingItems.length === 0 ? <EmptyState title="No findings yet" detail="Run the Marketing Agent to calculate signals." /> : null}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Action plan</p><h2>Recommendations</h2></div><span className="counter">{recommendationItems.length}</span></div>
          <div className="signal-list">
            {recommendationItems.slice(0, 12).map((recommendation) => (
              <article className="signal" key={recommendation.recommendation_id}>
                <div><StatusBadge status={recommendation.action_type} /><StatusBadge status={liveReadOnly ? "read only advisory" : "fake executable"} /><code>{compactId(recommendation.provider_object_id)}</code></div>
                <h3>{recommendation.expected_effect}</h3><p>{recommendation.reasoning}</p><small>Expires {formatDate(recommendation.expires_at)}</small>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Decision gate</p><h2>Pending approvals</h2></div><span className="counter">{proposals?.items.length ?? 0}</span></div>
        <DataTable
          columns={[
            { key: "action", label: "Action", render: (item) => item.action_type },
            { key: "mode", label: "Mode", render: (item) => <StatusBadge status={item.provider_mode} /> },
            { key: "execution", label: "Execution", render: (item) => item.execution_forbidden ? "Forbidden" : "Available after approval" },
            { key: "object", label: "Object", render: (item) => <code>{compactId(item.provider_object_id)}</code> },
            { key: "confidence", label: "Confidence", render: (item) => item.confidence },
            { key: "expires", label: "Expires", render: (item) => formatDate(item.expires_at) },
          ]}
          items={proposals?.items ?? []}
          getKey={(item) => item.proposal_id}
          empty={<EmptyState title="No pending approvals" detail="The current decision queue is clear." />}
        />
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Changes</p><h2>Execution history</h2></div></div>
        <DataTable
          columns={[
            { key: "id", label: "Execution", render: (item) => <code>{compactId(item.execution_id)}</code> },
            { key: "status", label: "Status", render: (item) => <StatusBadge status={item.status} /> },
            { key: "attempted", label: "Attempted", render: (item) => formatDate(item.attempted_at) },
            { key: "request", label: "Provider request", render: (item) => item.provider_request_id ?? "—" },
          ]}
          items={executions?.items ?? []}
          getKey={(item) => item.execution_id}
          empty={<EmptyState title="No executions" detail={liveReadOnly ? "Live Meta execution is forbidden. Recommendations remain advisory." : "Approved sandbox changes will appear here."} />}
        />
      </section>

      <div className="split-grid">
        <section className="panel report-panel">
          <div className="panel-heading"><div><p className="eyebrow">Nightly & analysis</p><h2>Latest report</h2></div><StatusBadge status={latestReport?.report_type ?? "pending"} /></div>
          <p className="report-copy">{latestReport?.human_readable ?? "No verified report has been generated yet."}</p>
        </section>
        <section className="panel configuration-summary">
          <div className="panel-heading"><div><p className="eyebrow">Active controls</p><h2>Configuration & schedules</h2></div><span>v{overview?.configuration?.version ?? "—"}</span></div>
          <pre>{JSON.stringify(overview?.configuration?.values ?? {}, null, 2)}</pre>
          <div className="schedule-list">
            {(overview?.schedules ?? []).map((schedule) => (
              <div key={schedule.schedule_id}><span><strong>{schedule.job_type}</strong><code>{schedule.cron_expression}</code></span><span>{formatDate(schedule.next_run_at)}</span><StatusBadge status={schedule.enabled ? "enabled" : "disabled"} /></div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
