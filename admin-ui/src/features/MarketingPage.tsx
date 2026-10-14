"use client";

import { useI18n } from "@/i18n/LanguageProvider";

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
  const { t, locale } = useI18n();

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
        eyebrow={t("Рост и конверсия · Реклама")}
        title={t("Аналитика рекламы")}
        description={t(
          "Сохранённые показатели рекламы Meta, выводы и предложения. Реальные изменения в рекламном кабинете отключены.",
        )}
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
          {t(
            "Часть рекламных данных не удалось обновить. Отсутствующие значения не подставляются.",
          )}{" "}
        </p>
      ) : null}
      {overviewLoading ? (
        <p className="notice" role="status">
          {t("Загружаем последний сохранённый результат…")}{" "}
        </p>
      ) : null}
      <section className="metric-grid">
        <MetricCard label={t("Расходы")} value={displayValue(kpis.spend)} />
        <MetricCard
          label={t("Заявки")}
          value={displayValue(kpis.leads)}
          accent="blue"
        />
        <MetricCard
          label="CTR"
          value={displayValue(kpis.ctr)}
          detail={t("Проценты")}
        />
        <MetricCard label="CPL" value={displayValue(kpis.cpl)} accent="amber" />
        <MetricCard
          label="ROAS"
          value={displayValue(kpis.roas)}
          accent="blue"
        />
        <MetricCard
          label={t("Рекламный кабинет")}
          value={account?.currency ?? "unavailable"}
          detail={`${account?.timezone ?? "unavailable"} · ${snapshot?.attribution_window ?? "unavailable"}`}
        />
        <MetricCard
          label={t("Последний сбор данных")}
          value={formatDate(overview?.last_synchronized_at, locale)}
          detail={
            overview?.integration_health.message ??
            t("Нет сохранённой проверки подключения")
          }
          accent="rose"
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Состояние подключения")}</p>
            <h2>{t("Подключение Meta")}</h2>
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
            <dt>{t("Только чтение")}</dt>
            <dd>{liveReadOnly ? t("Принудительно включено") : t("Нет")}</dd>
          </div>
          <div>
            <dt>Graph API</dt>
            <dd>
              {snapshot?.api_version ??
                displayValue(healthDiagnostics.api_version)}
            </dd>
          </div>
          <div>
            <dt>{t("Состояние доступа")}</dt>
            <dd>
              {credentialHealth.is_valid === true
                ? t("Действует")
                : t("Недоступно")}
            </dd>
          </div>
          <div>
            <dt>{t("Разрешения")}</dt>
            <dd>
              {Array.isArray(credentialHealth.scopes)
                ? credentialHealth.scopes.join(", ")
                : "unavailable"}
            </dd>
          </div>
          <div>
            <dt>{t("Выбранный кабинет")}</dt>
            <dd>{displayValue(healthDiagnostics.selected_account_alias)}</dd>
          </div>
          <div>
            <dt>{t("Валюта / часовой пояс")}</dt>
            <dd>
              {account?.currency ?? "unavailable"} /{" "}
              {account?.timezone ?? "unavailable"}
            </dd>
          </div>
          <div>
            <dt>{t("Последний успешный запрос")}</dt>
            <dd>
              {formatDate(overview?.integration_health.last_success_at, locale)}
            </dd>
          </div>
          <div>
            <dt>{t("Последний сбор данных")}</dt>
            <dd>{formatDate(overview?.last_synchronized_at, locale)}</dd>
          </div>
          <div>
            <dt>{t("Использование лимитов API")}</dt>
            <dd>{displayValue(healthDiagnostics.rate_limit_usage_percent)}%</dd>
          </div>
          <div>
            <dt>{t("Лимит запросов")}</dt>
            <dd>
              {displayValue(requestBudget?.requests_used)} /{" "}
              {displayValue(requestBudget?.max_requests)} requests
            </dd>
          </div>
          <div>
            <dt>{t("Страницы / повторы")}</dt>
            <dd>
              {displayValue(requestBudget?.pages_fetched)} /{" "}
              {displayValue(requestBudget?.retries_used)}
            </dd>
          </div>
          <div>
            <dt>{t("Свежесть данных")}</dt>
            <dd>{observability?.data_freshness_days ?? "unavailable"} days</dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Сохранённые данные")}</p>
            <h2>{t("Фильтры и период анализа")}</h2>
          </div>
          <span className="counter">{insightRows.length}</span>
        </div>
        <div className="live-browser-filters">
          <label>
            <span>{t("Поиск")}</span>
            <input
              value={entityQuery}
              onChange={(event) => setEntityQuery(event.target.value)}
              placeholder={t("Название или идентификатор")}
            />
          </label>
          <label>
            <span>{t("Статус показов")}</span>
            <select
              value={deliveryStatus}
              onChange={(event) => setDeliveryStatus(event.target.value)}
            >
              <option value="all">{t("Все статусы")}</option>
              {deliveryStatuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("Начало периода")}</span>
            <input
              type="date"
              min={defaultStart}
              max={periodEnd || defaultEnd}
              value={periodStart}
              onChange={(event) => setSelectedStart(event.target.value)}
            />
          </label>
          <label>
            <span>{t("Конец периода")}</span>
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
            <p className="eyebrow">{t("Структура рекламы")}</p>
            <h2>{t("Кампании")}</h2>
          </div>
          <span className="counter">{snapshot?.campaigns.length ?? 0}</span>
        </div>
        <MarketingEntityTable
          entities={filteredCampaigns}
          label={t("Кампания")}
        />
      </section>
      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Показы")}</p>
              <h2>{t("Группы объявлений")}</h2>
            </div>
            <span className="counter">{snapshot?.ad_sets.length ?? 0}</span>
          </div>
          <MarketingEntityTable
            entities={filteredAdSets}
            label={t("Группа объявлений")}
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Показы")}</p>
              <h2>{t("Объявления")}</h2>
            </div>
            <span className="counter">{snapshot?.ads.length ?? 0}</span>
          </div>
          <MarketingEntityTable
            entities={filteredAds}
            label={t("Объявление")}
          />
        </section>
      </div>

      <div className="split-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Сравнение креативов")}</p>
              <h2>{t("Креативы")}</h2>
            </div>
          </div>
          <DataTable
            columns={[
              {
                key: "name",
                label: t("Креатив"),
                render: (item) => (
                  <div className="primary-cell">
                    <strong>{item.name}</strong>
                    <code>{compactId(item.provider_id)}</code>
                  </div>
                ),
              },
              {
                key: "format",
                label: t("Формат"),
                render: (item) => item.format ?? "—",
              },
              {
                key: "signal",
                label: t("Последнее наблюдение"),
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
                title={t("Креативов пока нет")}
                detail={t("Данные креативов появятся после сбора.")}
              />
            }
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Сравнение аудиторий")}</p>
              <h2>{t("Аудитории")}</h2>
            </div>
          </div>
          <DataTable
            columns={[
              {
                key: "name",
                label: t("Аудитория"),
                render: (item) => (
                  <div className="primary-cell">
                    <strong>{item.name}</strong>
                    <code>{compactId(item.provider_id)}</code>
                  </div>
                ),
              },
              {
                key: "subtype",
                label: t("Подтип"),
                render: (item) => item.subtype,
              },
              {
                key: "signal",
                label: t("Последнее наблюдение"),
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
                title={t("Аудиторий пока нет")}
                detail={t(
                  "Данные аудиторий и таргетинга появятся после сбора.",
                )}
              />
            }
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Расчёт по данным")}</p>
            <h2>{t("Регионы, площадки, время и демография")}</h2>
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
            <p className="eyebrow">{t("Подтверждающие данные")}</p>
            <h2>{t("Статистика за выбранный период")}</h2>
          </div>
          <span className="counter">{insightRows.length}</span>
        </div>
        <DataTable
          columns={[
            {
              key: "object",
              label: t("Объект"),
              render: (item) => (
                <div className="primary-cell">
                  <strong>{item.entity_name}</strong>
                  <code>{compactId(item.entity_id)}</code>
                </div>
              ),
            },
            { key: "date", label: t("Дата"), render: (item) => item.date_stop },
            {
              key: "spend",
              label: t("Расходы"),
              render: (item) => displayValue(item.metrics.spend.value),
            },
            {
              key: "impressions",
              label: t("Показы"),
              render: (item) => displayValue(item.metrics.impressions.value),
            },
            {
              key: "clicks",
              label: t("Клики"),
              render: (item) => displayValue(item.metrics.clicks.value),
            },
            {
              key: "results",
              label: t("Заявки / конверсии"),
              render: (item) =>
                `${displayValue(item.metrics.leads.value)} / ${displayValue(item.metrics.conversions.value)}`,
            },
            {
              key: "attribution",
              label: t("Атрибуция"),
              render: (item) => item.attribution_window,
            },
          ]}
          items={insightRows.slice(0, 100)}
          getKey={(item) => item.row_id}
          empty={
            <EmptyState
              title={t("Нет статистики")}
              detail={t(
                "За выбранный завершённый период нет подходящих данных.",
              )}
            />
          }
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Качество данных")}</p>
            <h2>{t("Доступность и полнота данных")}</h2>
          </div>
          <span className="counter">
            {snapshot?.compatibility_matrix?.length ?? 0}
          </span>
        </div>
        <DataTable
          columns={[
            {
              key: "operation",
              label: t("Операция"),
              render: (item) => item.operation,
            },
            {
              key: "level",
              label: t("Уровень"),
              render: (item) => item.level ?? "—",
            },
            {
              key: "breakdowns",
              label: t("Разрезы данных"),
              render: (item) =>
                item.breakdowns && item.breakdowns.length > 0
                  ? item.breakdowns.join(", ")
                  : "base",
            },
            {
              key: "status",
              label: t("Состояние"),
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "rows",
              label: t("Строки"),
              render: (item) => item.row_count,
            },
            {
              key: "reason",
              label: t("Причина"),
              render: (item) => item.reason_code ?? "—",
            },
          ]}
          items={snapshot?.compatibility_matrix ?? []}
          getKey={(item) =>
            `${item.operation}:${item.level ?? "none"}:${item.breakdowns?.join("+") ?? "base"}`
          }
          empty={
            <EmptyState
              title={t("Нет результатов проверки доступности")}
              detail={t(
                "Дождитесь запланированного сбора данных для проверки доступных разрезов.",
              )}
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
              <p className="eyebrow">{t("Сравнения и отклонения")}</p>
              <h2>{t("Выводы")}</h2>
            </div>
            <span className="counter">{findingItems.length}</span>
          </div>
          <div
            className="signal-list"
            tabIndex={0}
            role="region"
            aria-label={t("Выводы по рекламе")}
          >
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
                    <dt>{t("Уверенность")}</dt>
                    <dd>{finding.confidence}</dd>
                  </div>
                  <div>
                    <dt>{t("Полнота данных")}</dt>
                    <dd>{finding.completeness ?? "unavailable"}</dd>
                  </div>
                  <div>
                    <dt>{t("Период")}</dt>
                    <dd>
                      {finding.period_start?.slice(0, 10) ?? "unavailable"} –{" "}
                      {finding.period_end?.slice(0, 10) ?? "unavailable"}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Атрибуция / валюта")}</dt>
                    <dd>
                      {finding.attribution_identity ?? "unavailable"} /{" "}
                      {finding.currency ?? "unavailable"}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Объект источника")}</dt>
                    <dd>
                      {finding.provider_object_id
                        ? compactId(finding.provider_object_id)
                        : "account"}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Режим")}</dt>
                    <dd>{snapshot?.provider_mode ?? "unavailable"}</dd>
                  </div>
                </dl>
                <div className="evidence-block">
                  <h3>{t("Основания")}</h3>
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
                  <small>
                    {t("Ограничения:")} {finding.limitations?.join(" · ")}
                  </small>
                ) : null}
              </article>
            ))}
            {findingItems.length === 0 ? (
              <EmptyState
                title={t("Выводов пока нет")}
                detail={t("После анализа рекламы здесь появятся выводы.")}
              />
            ) : null}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Предлагаемые действия")}</p>
              <h2>{t("Предложения")}</h2>
            </div>
            <span className="counter">{recommendationItems.length}</span>
          </div>
          <div
            className="signal-list"
            tabIndex={0}
            role="region"
            aria-label={t("Предложения по рекламе")}
          >
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
                  {t("Действует до")}{" "}
                  {formatDate(recommendation.expires_at, locale)}
                </small>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Нужно ваше решение")}</p>
            <h2>{t("Ожидают согласования")}</h2>
          </div>
          <span className="counter">{proposals?.items.length ?? 0}</span>
        </div>
        <DataTable
          columns={[
            {
              key: "action",
              label: t("Действие"),
              render: (item) => item.action_type,
            },
            {
              key: "mode",
              label: t("Режим"),
              render: (item) => <StatusBadge status={item.provider_mode} />,
            },
            {
              key: "execution",
              label: t("Выполнение"),
              render: (item) =>
                item.execution_forbidden
                  ? t("Запрещено")
                  : t("После согласования"),
            },
            {
              key: "object",
              label: t("Объект"),
              render: (item) => (
                <code>{compactId(item.provider_object_id)}</code>
              ),
            },
            {
              key: "confidence",
              label: t("Уверенность"),
              render: (item) => item.confidence,
            },
            {
              key: "expires",
              label: t("Действует до"),
              render: (item) => formatDate(item.expires_at, locale),
            },
          ]}
          items={proposals?.items ?? []}
          getKey={(item) => item.proposal_id}
          empty={
            <EmptyState
              title={t("Нет ожидающих согласования")}
              detail={t("Нет предложений, ожидающих решения.")}
            />
          }
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t("Изменения")}</p>
            <h2>{t("История выполнения")}</h2>
          </div>
        </div>
        <DataTable
          columns={[
            {
              key: "id",
              label: t("Выполнение"),
              render: (item) => <code>{compactId(item.execution_id)}</code>,
            },
            {
              key: "status",
              label: t("Состояние"),
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "attempted",
              label: t("Время попытки"),
              render: (item) => formatDate(item.attempted_at, locale),
            },
            {
              key: "request",
              label: t("Запрос к источнику"),
              render: (item) => item.provider_request_id ?? "—",
            },
          ]}
          items={executions?.items ?? []}
          getKey={(item) => item.execution_id}
          empty={
            <EmptyState
              title={t("Выполненных действий пока нет")}
              detail={
                liveReadOnly
                  ? t(
                      "Изменения в Meta запрещены. Доступны только рекомендации.",
                    )
                  : t(
                      "Здесь появятся согласованные изменения в тестовой среде.",
                    )
              }
            />
          }
        />
      </section>

      <div className="split-grid">
        <section className="panel report-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Анализ и отчёты")}</p>
              <h2>{t("Последний отчёт")}</h2>
            </div>
            <StatusBadge status={latestReport?.report_type ?? "pending"} />
          </div>
          <p className="report-copy">
            {latestReport?.human_readable ??
              t("Подтверждённый отчёт ещё не сформирован.")}
          </p>
        </section>
        <section className="panel configuration-summary">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{t("Ограничения и расписание")}</p>
              <h2>{t("Настройки и расписание")}</h2>
            </div>
            <span>v{overview?.configuration?.version ?? "—"}</span>
          </div>
          <pre
            tabIndex={0}
            role="region"
            aria-label={t("Технические настройки рекламы")}
          >
            {JSON.stringify(overview?.configuration?.values ?? {}, null, 2)}
          </pre>
          <div className="schedule-list">
            {(overview?.schedules ?? []).map((schedule) => (
              <div key={schedule.schedule_id}>
                <span>
                  <strong>{schedule.job_type}</strong>
                  <code>{schedule.cron_expression}</code>
                </span>
                <span>{formatDate(schedule.next_run_at, locale)}</span>
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
