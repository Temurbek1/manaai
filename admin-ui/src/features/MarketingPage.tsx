"use client";

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
import { useSession } from "../auth/SessionContext";
import { compactId, displayValue, formatDate, isRecord } from "../ui/format";

export function MarketingPage(): React.JSX.Element {
  const { session } = useSession();
  const [entityQuery, setEntityQuery] = useState("");
  const [deliveryStatus, setDeliveryStatus] = useState("all");
  const [selectedStart, setSelectedStart] = useState("");
  const [selectedEnd, setSelectedEnd] = useState("");
  const {
    data: overview,
    error: overviewError,
    isLoading: overviewLoading,
  } = useSWR<MarketingOverview, Error>(
    "/api/v1/admin/operation/marketing/overview",
    { refreshInterval: 30_000 },
  );
  const { data: runs, error: runsError } = useSWR<RunPage, Error>(
    "/api/v1/admin/operation/runs?agent_id=growth-agent&capability_key=growth.advertising&limit=20",
    { refreshInterval: 15_000 },
  );
  const latestRun = runs?.items[0];
  const runFilter = latestRun ? `?run_id=${latestRun.run_id}&limit=100` : null;
  const { data: findings, error: findingsError } = useSWR<FindingPage, Error>(
    runFilter ? `/api/v1/admin/operation/findings${runFilter}` : null,
  );
  const { data: recommendations, error: recommendationsError } = useSWR<
    RecommendationPage,
    Error
  >(runFilter ? `/api/v1/admin/operation/recommendations${runFilter}` : null);
  const { data: proposals, error: proposalsError } = useSWR<
    ProposalPage,
    Error
  >(
    "/api/v1/admin/operation/action-proposals?status=awaiting_approval&limit=100",
    { refreshInterval: 10_000 },
  );
  const { data: executions, error: executionsError } = useSWR<
    ExecutionPage,
    Error
  >(
    "/api/v1/admin/operation/executions?agent_id=growth-agent&capability_key=growth.advertising&limit=100",
    {
      refreshInterval: 15_000,
    },
  );
  const { data: reports, error: reportsError } = useSWR<ReportPage, Error>(
    "/api/v1/admin/operation/reports?agent_id=growth-agent&capability_key=growth.advertising&limit=20",
    { refreshInterval: 30_000 },
  );
  const latestReport = reports?.items[0];
  const structured =
    latestReport && isRecord(latestReport.structured)
      ? latestReport.structured
      : {};
  const kpis = isRecord(structured.kpis) ? structured.kpis : {};
  const snapshot = overview?.snapshot;
  const liveReadOnly =
    session.live_meta_read_only || snapshot?.provider_mode === "live_read_only";
  const account = snapshot ? snapshot.accounts[0] : undefined;
  const healthDiagnostics = isRecord(overview?.integration_health.diagnostics)
    ? overview.integration_health.diagnostics
    : {};
  const credentialHealth = isRecord(healthDiagnostics.token)
    ? healthDiagnostics.token
    : {};
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
        (deliveryStatus === "all" ||
          entity.effective_status === deliveryStatus) &&
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
      [
        ...(snapshot?.campaigns ?? []),
        ...(snapshot?.ad_sets ?? []),
        ...(snapshot?.ads ?? []),
      ]
        .map((entity) => entity.effective_status)
        .filter(Boolean),
    ),
  ).sort();
  const findingItems = findings?.items ?? [];
  const recommendationItems = recommendations?.items ?? [];
  const rankingByObject = new Map(
    findingItems
      .filter((finding) => finding.provider_object_id !== null)
      .map((finding) => [
        finding.provider_object_id ?? "",
        finding.finding_type,
      ]),
  );

  return (
    <>
      <PageHeader
        eyebrow="Рост и конверсия · Реклама"
        title="Аналитика рекламы"
        description="Сохранённые показатели рекламы Meta, выводы и предложения. Реальные изменения в рекламном кабинете отключены."
        actions={
          overview ? (
            <StatusBadge status={overview.integration_health.status} />
          ) : null
        }
      />
      {overviewError ||
      runsError ||
      findingsError ||
      recommendationsError ||
      proposalsError ||
      executionsError ||
      reportsError ? (
        <p className="error-banner" role="alert">
          Часть рекламных данных не удалось обновить. Отсутствующие значения не
          подставляются.
        </p>
      ) : null}
      {overviewLoading ? (
        <p className="notice" role="status">
          Загружаем последний сохранённый результат…
        </p>
      ) : null}
      <section className="metric-grid">
        <MetricCard label="Расходы" value={displayValue(kpis.spend)} />
        <MetricCard
          label="Заявки"
          value={displayValue(kpis.leads)}
          accent="blue"
        />
        <MetricCard
          label="CTR"
          value={displayValue(kpis.ctr)}
          detail="Проценты"
        />
        <MetricCard label="CPL" value={displayValue(kpis.cpl)} accent="amber" />
        <MetricCard
          label="ROAS"
          value={displayValue(kpis.roas)}
          accent="blue"
        />
        <MetricCard
          label="Рекламный кабинет"
          value={account?.currency ?? "unavailable"}
          detail={`${account?.timezone ?? "unavailable"} · ${snapshot?.attribution_window ?? "unavailable"}`}
        />
        <MetricCard
          label="Последний сбор данных"
          value={formatDate(overview?.last_synchronized_at)}
          detail={
            overview?.integration_health.message ??
            "Нет сохранённой проверки подключения"
          }
          accent="rose"
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Состояние подключения</p>
            <h2>Подключение Meta</h2>
          </div>
          <StatusBadge
            status={
              liveReadOnly
                ? "live read only"
                : (snapshot?.provider_mode ?? "pending")
            }
          />
        </div>
        <dl className="detail-grid health-detail-grid">
          <div>
            <dt>Только чтение</dt>
            <dd>{liveReadOnly ? "Принудительно включено" : "Нет"}</dd>
          </div>
          <div>
            <dt>Graph API</dt>
            <dd>
              {snapshot?.api_version ??
                displayValue(healthDiagnostics.api_version)}
            </dd>
          </div>
          <div>
            <dt>Состояние доступа</dt>
            <dd>
              {credentialHealth.is_valid === true ? "Действует" : "Недоступно"}
            </dd>
          </div>
          <div>
            <dt>Разрешения</dt>
            <dd>
              {Array.isArray(credentialHealth.scopes)
                ? credentialHealth.scopes.join(", ")
                : "unavailable"}
            </dd>
          </div>
          <div>
            <dt>Выбранный кабинет</dt>
            <dd>{displayValue(healthDiagnostics.selected_account_alias)}</dd>
          </div>
          <div>
            <dt>Валюта / часовой пояс</dt>
            <dd>
              {account?.currency ?? "unavailable"} /{" "}
              {account?.timezone ?? "unavailable"}
            </dd>
          </div>
          <div>
            <dt>Последний успешный запрос</dt>
            <dd>{formatDate(overview?.integration_health.last_success_at)}</dd>
          </div>
          <div>
            <dt>Последний сбор данных</dt>
            <dd>{formatDate(overview?.last_synchronized_at)}</dd>
          </div>
          <div>
            <dt>Использование лимитов API</dt>
            <dd>{displayValue(healthDiagnostics.rate_limit_usage_percent)}%</dd>
          </div>
          <div>
            <dt>Лимит запросов</dt>
            <dd>
              {displayValue(requestBudget?.requests_used)} /{" "}
              {displayValue(requestBudget?.max_requests)} requests
            </dd>
          </div>
          <div>
            <dt>Страницы / повторы</dt>
            <dd>
              {displayValue(requestBudget?.pages_fetched)} /{" "}
              {displayValue(requestBudget?.retries_used)}
            </dd>
          </div>
          <div>
            <dt>Свежесть данных</dt>
            <dd>{observability?.data_freshness_days ?? "unavailable"} days</dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Сохранённые данные</p>
            <h2>Фильтры и период анализа</h2>
          </div>
          <span className="counter">{insightRows.length}</span>
        </div>
        <div className="live-browser-filters">
          <label>
            <span>Поиск</span>
            <input
              value={entityQuery}
              onChange={(event) => setEntityQuery(event.target.value)}
              placeholder="Название или идентификатор"
            />
          </label>
          <label>
            <span>Статус показов</span>
            <select
              value={deliveryStatus}
              onChange={(event) => setDeliveryStatus(event.target.value)}
            >
              <option value="all">Все статусы</option>
              {deliveryStatuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Начало периода</span>
            <input
              type="date"
              min={defaultStart}
              max={periodEnd || defaultEnd}
              value={periodStart}
              onChange={(event) => setSelectedStart(event.target.value)}
            />
          </label>
          <label>
            <span>Конец периода</span>
            <input
              type="date"
              min={periodStart || defaultStart}
              max={defaultEnd}
              value={periodEnd}
              onChange={(event) => setSelectedEnd(event.target.value)}
            />
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Структура рекламы</p>
            <h2>Кампании</h2>
          </div>
          <span className="counter">{snapshot?.campaigns.length ?? 0}</span>
        </div>
        <MarketingEntityTable entities={filteredCampaigns} label="Кампания" />
      </section>
      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Показы</p>
              <h2>Группы объявлений</h2>
            </div>
            <span className="counter">{snapshot?.ad_sets.length ?? 0}</span>
          </div>
          <MarketingEntityTable
            entities={filteredAdSets}
            label="Группа объявлений"
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Показы</p>
              <h2>Объявления</h2>
            </div>
            <span className="counter">{snapshot?.ads.length ?? 0}</span>
          </div>
          <MarketingEntityTable entities={filteredAds} label="Объявление" />
        </section>
      </div>

      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Сравнение креативов</p>
              <h2>Креативы</h2>
            </div>
          </div>
          <DataTable
            columns={[
              {
                key: "name",
                label: "Креатив",
                render: (item) => (
                  <div className="primary-cell">
                    <strong>{item.name}</strong>
                    <code>{compactId(item.provider_id)}</code>
                  </div>
                ),
              },
              {
                key: "format",
                label: "Формат",
                render: (item) => item.format ?? "—",
              },
              {
                key: "signal",
                label: "Последнее наблюдение",
                render: (item) => (
                  <StatusBadge
                    status={rankingByObject.get(item.provider_id) ?? "observed"}
                  />
                ),
              },
            ]}
            items={snapshot?.creatives ?? []}
            getKey={(item) => item.provider_id}
            empty={
              <EmptyState
                title="Креативов пока нет"
                detail="Данные креативов появятся после сбора."
              />
            }
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Сравнение аудиторий</p>
              <h2>Аудитории</h2>
            </div>
          </div>
          <DataTable
            columns={[
              {
                key: "name",
                label: "Аудитория",
                render: (item) => (
                  <div className="primary-cell">
                    <strong>{item.name}</strong>
                    <code>{compactId(item.provider_id)}</code>
                  </div>
                ),
              },
              {
                key: "subtype",
                label: "Подтип",
                render: (item) => item.subtype,
              },
              {
                key: "signal",
                label: "Последнее наблюдение",
                render: (item) => (
                  <StatusBadge
                    status={
                      rankingByObject.get(item.provider_id) ?? item.status
                    }
                  />
                ),
              },
            ]}
            items={snapshot?.audiences ?? []}
            getKey={(item) => item.provider_id}
            empty={
              <EmptyState
                title="Аудиторий пока нет"
                detail="Данные аудиторий и таргетинга появятся после сбора."
              />
            }
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Расчёт по данным</p>
            <h2>Регионы, площадки, время и демография</h2>
          </div>
          <span className="counter">
            {overview?.breakdown_performance.length ?? 0}
          </span>
        </div>
        <PerformanceBreakdownTable
          rows={overview?.breakdown_performance ?? []}
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Подтверждающие данные</p>
            <h2>Статистика за выбранный период</h2>
          </div>
          <span className="counter">{insightRows.length}</span>
        </div>
        <DataTable
          columns={[
            {
              key: "object",
              label: "Объект",
              render: (item) => (
                <div className="primary-cell">
                  <strong>{item.entity_name}</strong>
                  <code>{compactId(item.entity_id)}</code>
                </div>
              ),
            },
            { key: "date", label: "Дата", render: (item) => item.date_stop },
            {
              key: "spend",
              label: "Расходы",
              render: (item) => displayValue(item.metrics.spend.value),
            },
            {
              key: "impressions",
              label: "Показы",
              render: (item) => displayValue(item.metrics.impressions.value),
            },
            {
              key: "clicks",
              label: "Клики",
              render: (item) => displayValue(item.metrics.clicks.value),
            },
            {
              key: "results",
              label: "Заявки / конверсии",
              render: (item) =>
                `${displayValue(item.metrics.leads.value)} / ${displayValue(item.metrics.conversions.value)}`,
            },
            {
              key: "attribution",
              label: "Атрибуция",
              render: (item) => item.attribution_window,
            },
          ]}
          items={insightRows.slice(0, 100)}
          getKey={(item) => item.row_id}
          empty={
            <EmptyState
              title="Нет статистики"
              detail="За выбранный завершённый период нет подходящих данных."
            />
          }
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Качество данных</p>
            <h2>Доступность и полнота данных</h2>
          </div>
          <span className="counter">
            {snapshot?.compatibility_matrix?.length ?? 0}
          </span>
        </div>
        <DataTable
          columns={[
            {
              key: "operation",
              label: "Операция",
              render: (item) => item.operation,
            },
            {
              key: "level",
              label: "Уровень",
              render: (item) => item.level ?? "—",
            },
            {
              key: "breakdowns",
              label: "Разрезы данных",
              render: (item) =>
                item.breakdowns && item.breakdowns.length > 0
                  ? item.breakdowns.join(", ")
                  : "base",
            },
            {
              key: "status",
              label: "Состояние",
              render: (item) => <StatusBadge status={item.status} />,
            },
            { key: "rows", label: "Строки", render: (item) => item.row_count },
            {
              key: "reason",
              label: "Причина",
              render: (item) => item.reason_code ?? "—",
            },
          ]}
          items={snapshot?.compatibility_matrix ?? []}
          getKey={(item) =>
            `${item.operation}:${item.level ?? "none"}:${item.breakdowns?.join("+") ?? "base"}`
          }
          empty={
            <EmptyState
              title="Нет результатов проверки доступности"
              detail="Дождитесь запланированного сбора данных для проверки доступных разрезов."
            />
          }
        />
        {(snapshot?.data_quality_notes?.length ?? 0) > 0 ? (
          <ul className="quality-notes">
            {snapshot?.data_quality_notes?.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Сравнения и отклонения</p>
              <h2>Выводы</h2>
            </div>
            <span className="counter">{findingItems.length}</span>
          </div>
          <div className="signal-list">
            {findingItems.slice(0, 12).map((finding) => (
              <article className="signal" key={finding.finding_id}>
                <div>
                  <StatusBadge status={finding.severity} />
                  <span>{finding.finding_type}</span>
                </div>
                <h3>{finding.title}</h3>
                <p>{finding.description}</p>
                <dl className="detail-grid compact-detail-grid">
                  <div>
                    <dt>Уверенность</dt>
                    <dd>{finding.confidence}</dd>
                  </div>
                  <div>
                    <dt>Полнота данных</dt>
                    <dd>{finding.completeness ?? "unavailable"}</dd>
                  </div>
                  <div>
                    <dt>Период</dt>
                    <dd>
                      {finding.period_start?.slice(0, 10) ?? "unavailable"} –{" "}
                      {finding.period_end?.slice(0, 10) ?? "unavailable"}
                    </dd>
                  </div>
                  <div>
                    <dt>Атрибуция / валюта</dt>
                    <dd>
                      {finding.attribution_identity ?? "unavailable"} /{" "}
                      {finding.currency ?? "unavailable"}
                    </dd>
                  </div>
                  <div>
                    <dt>Объект источника</dt>
                    <dd>
                      {finding.provider_object_id
                        ? compactId(finding.provider_object_id)
                        : "account"}
                    </dd>
                  </div>
                  <div>
                    <dt>Режим</dt>
                    <dd>{snapshot?.provider_mode ?? "unavailable"}</dd>
                  </div>
                </dl>
                <div className="evidence-block">
                  <h3>Основания</h3>
                  {finding.evidence.map((evidence) => (
                    <div key={evidence.name}>
                      <span>{evidence.name}</span>
                      <code>{evidence.current.value ?? "unavailable"}</code>
                      <small>
                        baseline {evidence.baseline?.value ?? "unavailable"}
                      </small>
                    </div>
                  ))}
                </div>
                {(finding.limitations?.length ?? 0) > 0 ? (
                  <small>Ограничения: {finding.limitations?.join(" · ")}</small>
                ) : null}
              </article>
            ))}
            {findingItems.length === 0 ? (
              <EmptyState
                title="Выводов пока нет"
                detail="После анализа рекламы здесь появятся выводы."
              />
            ) : null}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Предлагаемые действия</p>
              <h2>Предложения</h2>
            </div>
            <span className="counter">{recommendationItems.length}</span>
          </div>
          <div className="signal-list">
            {recommendationItems.slice(0, 12).map((recommendation) => (
              <article
                className="signal"
                key={recommendation.recommendation_id}
              >
                <div>
                  <StatusBadge status={recommendation.action_type} />
                  <StatusBadge
                    status={
                      liveReadOnly ? "read only advisory" : "fake executable"
                    }
                  />
                  <code>{compactId(recommendation.provider_object_id)}</code>
                </div>
                <h3>{recommendation.expected_effect}</h3>
                <p>{recommendation.reasoning}</p>
                <small>
                  Действует до {formatDate(recommendation.expires_at)}
                </small>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Нужно ваше решение</p>
            <h2>Ожидают согласования</h2>
          </div>
          <span className="counter">{proposals?.items.length ?? 0}</span>
        </div>
        <DataTable
          columns={[
            {
              key: "action",
              label: "Действие",
              render: (item) => item.action_type,
            },
            {
              key: "mode",
              label: "Режим",
              render: (item) => <StatusBadge status={item.provider_mode} />,
            },
            {
              key: "execution",
              label: "Выполнение",
              render: (item) =>
                item.execution_forbidden ? "Запрещено" : "После согласования",
            },
            {
              key: "object",
              label: "Объект",
              render: (item) => (
                <code>{compactId(item.provider_object_id)}</code>
              ),
            },
            {
              key: "confidence",
              label: "Уверенность",
              render: (item) => item.confidence,
            },
            {
              key: "expires",
              label: "Действует до",
              render: (item) => formatDate(item.expires_at),
            },
          ]}
          items={proposals?.items ?? []}
          getKey={(item) => item.proposal_id}
          empty={
            <EmptyState
              title="Нет ожидающих согласования"
              detail="Нет предложений, ожидающих решения."
            />
          }
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Изменения</p>
            <h2>История выполнения</h2>
          </div>
        </div>
        <DataTable
          columns={[
            {
              key: "id",
              label: "Выполнение",
              render: (item) => <code>{compactId(item.execution_id)}</code>,
            },
            {
              key: "status",
              label: "Состояние",
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "attempted",
              label: "Время попытки",
              render: (item) => formatDate(item.attempted_at),
            },
            {
              key: "request",
              label: "Запрос к источнику",
              render: (item) => item.provider_request_id ?? "—",
            },
          ]}
          items={executions?.items ?? []}
          getKey={(item) => item.execution_id}
          empty={
            <EmptyState
              title="Выполненных действий пока нет"
              detail={
                liveReadOnly
                  ? "Изменения в Meta запрещены. Доступны только рекомендации."
                  : "Здесь появятся согласованные изменения в тестовой среде."
              }
            />
          }
        />
      </section>

      <div className="split-grid">
        <section className="panel report-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Анализ и отчёты</p>
              <h2>Последний отчёт</h2>
            </div>
            <StatusBadge status={latestReport?.report_type ?? "pending"} />
          </div>
          <p className="report-copy">
            {latestReport?.human_readable ??
              "Подтверждённый отчёт ещё не сформирован."}
          </p>
        </section>
        <section className="panel configuration-summary">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Ограничения и расписание</p>
              <h2>Настройки и расписание</h2>
            </div>
            <span>v{overview?.configuration?.version ?? "—"}</span>
          </div>
          <pre>
            {JSON.stringify(overview?.configuration?.values ?? {}, null, 2)}
          </pre>
          <div className="schedule-list">
            {(overview?.schedules ?? []).map((schedule) => (
              <div key={schedule.schedule_id}>
                <span>
                  <strong>{schedule.job_type}</strong>
                  <code>{schedule.cron_expression}</code>
                </span>
                <span>{formatDate(schedule.next_run_at)}</span>
                <StatusBadge
                  status={schedule.enabled ? "enabled" : "disabled"}
                />
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
