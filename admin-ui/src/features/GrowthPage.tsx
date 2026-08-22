"use client";

import { useState } from "react";
import useSWR from "swr";

import type {
  AgentDetail,
  FindingPage,
  OutcomeEvaluationPage,
  ProposalPage,
  RecommendationPage,
  RunPage,
} from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { compactId, displayValue, formatDate } from "../ui/format";
import { MarketingPage } from "./MarketingPage";

const ADVERTISING = "growth.advertising";
const FUNNEL = "growth.funnel.analyze";

export function GrowthPage(): React.JSX.Element {
  const [selectedCapability, setSelectedCapability] = useState(ADVERTISING);
  const { data: detail, error: detailError } = useSWR<AgentDetail, Error>(
    "/api/v1/admin/operation/agents/growth-agent",
    { refreshInterval: 30_000 },
  );
  const { data: funnelRuns, error: runsError } = useSWR<RunPage, Error>(
    `/api/v1/admin/operation/runs?agent_id=growth-agent&capability_key=${FUNNEL}&limit=20`,
    { refreshInterval: 15_000 },
  );
  const latestFunnelRun = funnelRuns?.items[0];
  const runId = latestFunnelRun?.run_id;
  const { data: findings } = useSWR<FindingPage>(
    runId ? `/api/v1/admin/operation/findings?run_id=${runId}&limit=100` : null,
  );
  const { data: recommendations } = useSWR<RecommendationPage>(
    runId
      ? `/api/v1/admin/operation/recommendations?run_id=${runId}&limit=100`
      : null,
  );
  const { data: proposals } = useSWR<ProposalPage>(
    runId
      ? `/api/v1/admin/operation/action-proposals?run_id=${runId}&limit=100`
      : null,
  );
  const { data: outcomes } = useSWR<OutcomeEvaluationPage>(
    runId
      ? `/api/v1/admin/operation/outcome-evaluations?run_id=${runId}&limit=100`
      : null,
  );

  const latestConfigurations = new Map<
    string,
    AgentDetail["configurations"][number]
  >();
  for (const configuration of detail?.configurations ?? []) {
    const previous = latestConfigurations.get(configuration.capability_key);
    if (!previous || configuration.version > previous.version) {
      latestConfigurations.set(configuration.capability_key, configuration);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="MANA Operation AI"
        title="Growth & Conversion"
        description="One governed agent for advertising, funnel analysis, conversion hypotheses, offers, and controlled experiments."
        actions={detail ? <StatusBadge status={detail.agent.status} /> : null}
      />
      {detailError || runsError ? (
        <p className="error-banner" role="alert">
          Growth control-plane data could not be refreshed.
        </p>
      ) : null}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Capability control plane</p>
            <h2>Independent capabilities</h2>
          </div>
          <span className="counter">
            {detail?.agent.capabilities.length ?? 0}
          </span>
        </div>
        <div className="capability-list">
          {(detail?.agent.capabilities ?? []).map((capability) => {
            const configuration = latestConfigurations.get(capability.key);
            const schedules = (detail?.schedules ?? []).filter(
              (schedule) => schedule.capability_key === capability.key,
            );
            return (
              <button
                className={
                  selectedCapability === capability.key
                    ? "agent-button active"
                    : "agent-button"
                }
                key={capability.key}
                onClick={() => setSelectedCapability(capability.key)}
                type="button"
              >
                <span>
                  <strong>{capability.key}</strong>
                  <small>{capability.description}</small>
                  <small>
                    Configuration v{configuration?.version ?? "—"} ·{" "}
                    {schedules.length} schedule(s)
                  </small>
                </span>
                <StatusBadge status={capability.risk} />
              </button>
            );
          })}
        </div>
      </section>

      {selectedCapability === ADVERTISING ? (
        <MarketingPage />
      ) : selectedCapability === FUNNEL ? (
        <>
          <section
            className="metric-grid"
            aria-label="Funnel capability status"
          >
            <MetricCard
              label="Latest run"
              value={
                latestFunnelRun ? compactId(latestFunnelRun.run_id) : "No data"
              }
              detail={formatDate(latestFunnelRun?.started_at)}
            />
            <MetricCard
              label="Findings"
              value={findings?.total ?? 0}
              accent="amber"
            />
            <MetricCard
              label="Action proposals"
              value={proposals?.total ?? 0}
              accent="blue"
            />
            <MetricCard
              label="Outcome evaluations"
              value={outcomes?.total ?? 0}
              accent="rose"
            />
          </section>
          <p className="notice" role="status">
            Funnel sources are deterministic fake adapters in this milestone.
            Experiment writes target only the in-memory sandbox and always
            require approval.
          </p>
          <div className="split-grid">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Deterministic analysis</p>
                  <h2>Latest findings</h2>
                </div>
              </div>
              {(findings?.items ?? []).map((finding) => (
                <div className="compact-history" key={finding.finding_id}>
                  <div>
                    <span>
                      <strong>{finding.title}</strong>
                      <small>
                        {finding.deterministic_calculation ??
                          "Deterministic metric"}
                      </small>
                    </span>
                    <StatusBadge status={finding.severity} />
                  </div>
                </div>
              ))}
              {(findings?.items.length ?? 0) === 0 ? (
                <EmptyState
                  title="No funnel findings"
                  detail="Run growth.funnel.analyze to calculate the normalized funnel."
                />
              ) : null}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Governed actions</p>
                  <h2>Experiments and outcomes</h2>
                </div>
              </div>
              {(proposals?.items ?? []).map((proposal) => (
                <div className="compact-history" key={proposal.proposal_id}>
                  <div>
                    <code>{compactId(proposal.proposal_id)}</code>
                    <span>{proposal.action_type}</span>
                    <StatusBadge status={proposal.status} />
                  </div>
                </div>
              ))}
              {(outcomes?.items ?? []).map((outcome) => (
                <div className="compact-history" key={outcome.evaluation_id}>
                  <div>
                    <span>
                      <strong>{outcome.metric_name}</strong>
                      <small>
                        Baseline {displayValue(outcome.baseline_value)}
                      </small>
                    </span>
                    <StatusBadge status={outcome.status} />
                  </div>
                </div>
              ))}
              {(proposals?.items.length ?? 0) === 0 &&
              (outcomes?.items.length ?? 0) === 0 ? (
                <EmptyState
                  title="No experiment lifecycle"
                  detail="Shadow mode stores recommendations without creating action proposals."
                />
              ) : null}
            </section>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Recommendations</p>
                <h2>Conversion hypotheses</h2>
              </div>
            </div>
            {(recommendations?.items ?? []).map((recommendation) => (
              <div
                className="compact-history"
                key={recommendation.recommendation_id}
              >
                <div>
                  <span>
                    <strong>{recommendation.action_type}</strong>
                    <small>{recommendation.reasoning}</small>
                  </span>
                  <StatusBadge status={String(recommendation.confidence)} />
                </div>
              </div>
            ))}
          </section>
        </>
      ) : (
        <EmptyState
          title="Capability is not available"
          detail="This Growth capability has no loaded handler in the current runtime."
        />
      )}
    </>
  );
}
