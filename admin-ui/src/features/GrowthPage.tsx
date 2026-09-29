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
import { descriptionFor, labelFor } from "../ui/labels";
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
        title="Рост и конверсия"
        description="Анализ рекламы и воронки, предложения по росту конверсии и согласованные эксперименты. Режим данных указан в каждом разделе."
        actions={detail ? <StatusBadge status={detail.agent.status} /> : null}
      />
      {detailError || runsError ? (
        <p className="error-banner" role="alert">
          Не удалось обновить данные агента роста.
        </p>
      ) : null}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Возможности агента</p>
            <h2>Возможности агента</h2>
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
                  <strong>{labelFor(capability.key)}</strong>
                  <small>{descriptionFor(capability.key)}</small>
                  <small>
                    Версия настроек {configuration?.version ?? "—"} ·{" "}
                    расписаний: {schedules.length}
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
            aria-label="Состояние анализа воронки"
          >
            <MetricCard
              label="Последний запуск"
              value={
                latestFunnelRun
                  ? compactId(latestFunnelRun.run_id)
                  : "Нет данных"
              }
              detail={formatDate(latestFunnelRun?.started_at)}
            />
            <MetricCard
              label="Выводы"
              value={findings?.total ?? 0}
              accent="amber"
            />
            <MetricCard
              label="Предложения действий"
              value={proposals?.total ?? 0}
              accent="blue"
            />
            <MetricCard
              label="Оценки результата"
              value={outcomes?.total ?? 0}
              accent="rose"
            />
          </section>
          <p className="notice" role="status">
            Воронка пока использует тестовые данные. Эксперименты выполняются
            только в тестовой среде и требуют согласования. Это не показатели
            реальных продаж.
          </p>
          <div className="split-grid">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Расчёт по данным</p>
                  <h2>Последние выводы</h2>
                </div>
              </div>
              {(findings?.items ?? []).map((finding) => (
                <div className="compact-history" key={finding.finding_id}>
                  <div>
                    <span>
                      <strong>{finding.title}</strong>
                      <small>
                        {finding.deterministic_calculation ??
                          "Показатель рассчитан по данным"}
                      </small>
                    </span>
                    <StatusBadge status={finding.severity} />
                  </div>
                </div>
              ))}
              {(findings?.items.length ?? 0) === 0 ? (
                <EmptyState
                  title="Нет выводов по воронке"
                  detail="После анализа воронки здесь появятся рассчитанные показатели."
                />
              ) : null}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Действия под контролем</p>
                  <h2>Эксперименты и результаты</h2>
                </div>
              </div>
              {(proposals?.items ?? []).map((proposal) => (
                <div className="compact-history" key={proposal.proposal_id}>
                  <div>
                    <code>{compactId(proposal.proposal_id)}</code>
                    <span>{labelFor(proposal.action_type)}</span>
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
                        Исходное значение {displayValue(outcome.baseline_value)}
                      </small>
                    </span>
                    <StatusBadge status={outcome.status} />
                  </div>
                </div>
              ))}
              {(proposals?.items.length ?? 0) === 0 &&
              (outcomes?.items.length ?? 0) === 0 ? (
                <EmptyState
                  title="Экспериментов пока нет"
                  detail="В режиме наблюдения сохраняются рекомендации без запросов на выполнение."
                />
              ) : null}
            </section>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Предложения</p>
                <h2>Гипотезы роста конверсии</h2>
              </div>
            </div>
            {(recommendations?.items ?? []).map((recommendation) => (
              <div
                className="compact-history"
                key={recommendation.recommendation_id}
              >
                <div>
                  <span>
                    <strong>{labelFor(recommendation.action_type)}</strong>
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
          title="Возможность пока недоступна"
          detail="Эта возможность агента роста пока не реализована."
        />
      )}
    </>
  );
}
