"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import type { ReportPage } from "@/api/client";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { useI18n } from "@/i18n/LanguageProvider";
import { formatDate, isRecord, recordArray } from "@/ui/format";
import {
  evidenceState,
  evidenceStateLabel,
} from "@/features/chat/evidenceDisplay";
import {
  ANALYTICS_SOURCES,
  BREAKDOWN_LABELS,
  activityWindows,
  breakdowns,
  count,
  eventCounts,
  measure,
  retentionCohorts,
  savedAnalytics,
  telemetrySamples,
  type AnalyticsSource,
  type SavedAnalytics,
} from "./savedAnalytics";

const EVENT_LABELS: Record<string, string> = {
  screen_view: "Просмотр экрана",
  button_click: "Нажатие кнопки",
  session_start: "Начало сеанса",
  user_engagement: "Взаимодействие с приложением",
  first_open: "Первый запуск",
  app_remove: "Сигнал удаления",
  notification_receive: "Получение уведомления",
  notification_open: "Открытие уведомления",
  sign_up: "Регистрация",
  login: "Вход",
  form_submit: "Отправка формы",
};

function useSavedReports(source: AnalyticsSource) {
  return useSWR<ReportPage, Error>(
    `/api/v1/admin/operation/reports?agent_id=retention-agent&capability_key=${ANALYTICS_SOURCES[source].capability}&limit=5&offset=0`,
    {
      refreshInterval: 0,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
    },
  );
}

function SourceReport({
  saved,
  source,
}: {
  saved: SavedAnalytics;
  source: AnalyticsSource;
}): React.JSX.Element {
  const { t, locale } = useI18n();
  const { facts, report } = saved;
  const [windowDays, setWindowDays] = useState(30);
  const [groupIndex, setGroupIndex] = useState(0);
  const [displayedAt] = useState(() => Date.now());
  const number = (value: unknown): string => {
    const parsed = count(value);
    return parsed === null
      ? "—"
      : new Intl.NumberFormat(locale === "uz" ? "uz-Latn-UZ" : "ru-RU").format(
          parsed,
        );
  };
  const windows = activityWindows(facts);
  const window =
    windows.find((row) => row.days === windowDays) ?? windows.at(-1);
  const events = eventCounts(facts);
  const groups = breakdowns(facts);
  const group = groups[groupIndex] ?? groups[0];
  const samples = telemetrySamples(facts);
  const quality = evidenceState(
    {
      collected_at: saved.collectedAt,
      fresh_until:
        typeof facts.fresh_until === "string" ? facts.fresh_until : null,
      refresh_status:
        typeof facts.refresh_status === "string" ? facts.refresh_status : null,
    },
    displayedAt,
  );
  const notes = Array.from(
    new Set([
      ...report.data_quality_notes,
      ...(Array.isArray(facts.limitations)
        ? facts.limitations.filter(
            (note): note is string => typeof note === "string",
          )
        : []),
    ]),
  );
  return (
    <>
      <div className="analytics-report-meta">
        <span>
          {t("Сбор данных:")} {formatDate(saved.collectedAt, locale)}
        </span>
        <span className="analytics-pill">
          {t(
            saved.demo
              ? "Демонстрационные данные"
              : evidenceStateLabel(quality),
          )}
        </span>
      </div>
      {source === "ga4" && (
        <>
          <div className="analytics-section-title">
            <div>
              <h2>{t("Активность родителей")}</h2>
              <p className="muted">
                {window
                  ? `${window.start} — ${window.end}`
                  : t("Нет подтверждённого окна активности")}
              </p>
            </div>
            <div
              className="analytics-periods"
              aria-label={t("Окно из сохранённого отчёта")}
            >
              {([1, 7, 30] as const).map((days) => (
                <button
                  type="button"
                  key={days}
                  disabled={!windows.some((row) => row.days === days)}
                  aria-pressed={window?.days === days}
                  onClick={() => setWindowDays(days)}
                >
                  {t(days === 1 ? "1 день" : days === 7 ? "7 дней" : "30 дней")}
                </button>
              ))}
            </div>
          </div>
          <section className="metric-grid" aria-label={t("Показатели GA4")}>
            <MetricCard
              label={t("Активные профили GA4")}
              value={window ? number(window.users) : "—"}
              detail={t("Родительское приложение")}
              accent="blue"
            />
            <MetricCard
              label={t("Сеансы")}
              value={window ? number(window.sessions) : "—"}
            />
            <MetricCard
              label={t("Вовлечённые сеансы")}
              value={window ? number(window.engaged) : "—"}
            />
            <MetricCard
              label={t("Время взаимодействия")}
              value={
                window
                  ? `${number(Math.round(window.seconds / 60))} ${t("мин")}`
                  : "—"
              }
            />
          </section>
          <p className="analytics-footnote">
            {t(
              "Профили аналитики не равны числу родительских аккаунтов. Показан сохранённый период, не текущая активность.",
            )}
          </p>
          <div className="analytics-columns">
            <section className="panel analytics-panel">
              <div className="panel-heading">
                <h2>{t("События приложения")}</h2>
                <span className="muted">
                  {t(
                    facts.event_inventory_complete === true &&
                      facts.event_quality === "complete" &&
                      isRecord(facts.event_counts) &&
                      Object.keys(facts.event_counts).length === events.length
                      ? "Полный перечень в отчёте"
                      : "Неполные данные",
                  )}
                </span>
              </div>
              <DataTable
                caption={t("События GA4")}
                items={events.slice(0, 20)}
                getKey={(row) => row.name}
                columns={[
                  {
                    key: "name",
                    label: t("Событие"),
                    render: (row) => (
                      <span className="primary-cell">
                        <strong>{t(EVENT_LABELS[row.name] ?? row.name)}</strong>
                        {EVENT_LABELS[row.name] && <small>{row.name}</small>}
                      </span>
                    ),
                  },
                  {
                    key: "value",
                    label: t("Количество"),
                    render: (row) => number(row.value),
                  },
                ]}
                empty={
                  <p className="analytics-empty">
                    {t("Подтверждённых событий в отчёте нет")}
                  </p>
                }
              />
              {events.length > 20 && (
                <p className="analytics-footnote">
                  {t("Показано {0} из {1}", { 0: 20, 1: events.length })}
                </p>
              )}
            </section>
            <section className="panel analytics-panel">
              <div className="panel-heading">
                <h2>{t("Возвращаемость")}</h2>
                <span className="muted">D1 / D7 / D30</span>
              </div>
              <DataTable
                caption={t("Когорты первых сеансов")}
                items={retentionCohorts(facts)}
                getKey={(row) => row.date}
                columns={[
                  {
                    key: "cohort",
                    label: t("Первый сеанс"),
                    render: (row) => row.date,
                  },
                  ...[1, 7, 30].map((day, index) => ({
                    key: `day-${day}`,
                    label: `D${day}`,
                    render: (
                      row: ReturnType<typeof retentionCohorts>[number],
                    ) => row.returns[index] ?? "—",
                  })),
                ]}
                empty={
                  <p className="analytics-empty">
                    {t("Полных когорт в отчёте нет")}
                  </p>
                }
              />
              <p className="analytics-footnote">
                {t(
                  "Вернувшиеся / размер когорты. Только полностью наблюдённые когорты; отсутствие данных не равно нулю.",
                )}
              </p>
            </section>
          </div>
          <section className="panel analytics-panel">
            <div className="panel-heading">
              <h2>{t("Детализация GA4")}</h2>
              <label className="analytics-inline-label">
                {t("Разрез")}{" "}
                <select
                  value={String(group ? groups.indexOf(group) : -1)}
                  onChange={(event) =>
                    setGroupIndex(Number(event.target.value))
                  }
                  disabled={!groups.length}
                >
                  {groups.map((item, index) => (
                    <option key={String(item.kind)} value={index}>
                      {t(
                        BREAKDOWN_LABELS[
                          item.kind as keyof typeof BREAKDOWN_LABELS
                        ],
                      )}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <DataTable
              caption={t("Детализация GA4")}
              items={group ? recordArray(group.rows) : []}
              getKey={(row) => JSON.stringify(row.labels)}
              columns={[
                {
                  key: "group",
                  label: t("Группа"),
                  render: (row) =>
                    isRecord(row.labels)
                      ? Object.values(row.labels)
                          .filter((value) => typeof value === "string")
                          .join(" · ") || t("Не определено")
                      : "—",
                },
                ...[
                  "active_users",
                  "event_count",
                  "views",
                  "new_users",
                  "sessions",
                  "engagement_seconds",
                ]
                  .filter(
                    (key) =>
                      group &&
                      recordArray(group.rows).some(
                        (row) => isRecord(row.measures) && key in row.measures,
                      ),
                  )
                  .map((key) => ({
                    key,
                    label: t(
                      (
                        {
                          active_users: "Активные профили GA4",
                          event_count: "События",
                          views: "Просмотры",
                          new_users: "Новые профили",
                          sessions: "Сеансы",
                          engagement_seconds: "Взаимодействие, сек.",
                        } as Record<string, string>
                      )[key] ?? key,
                    ),
                    render: (row: Record<string, unknown>) => {
                      const value = isRecord(row.measures)
                        ? measure(row.measures[key])
                        : null;
                      return value === null
                        ? "—"
                        : new Intl.NumberFormat(
                            locale === "uz" ? "uz-Latn-UZ" : "ru-RU",
                            { maximumFractionDigits: 1 },
                          ).format(value);
                    },
                  })),
              ]}
              empty={
                <p className="analytics-empty">
                  {t("Детализация в отчёте отсутствует")}
                </p>
              }
            />
            {group && (
              <p className="analytics-footnote">
                {t("Показано {0} из {1} групп", {
                  0: recordArray(group.rows).length,
                  1: Number(group.total_groups),
                })}{" "}
                ·{" "}
                {t(
                  group.quality === "complete"
                    ? "Полный разрез в отчёте"
                    : "Неполные данные",
                )}
                . {t("География пользователей не является географией оплат.")}
              </p>
            )}
          </section>
        </>
      )}
      {source === "firestore" && (
        <>
          <div className="analytics-section-title">
            <div>
              <h2>{t("Телеметрия детских устройств")}</h2>
              <p className="muted">
                {t("Две ограниченные выборки, не статистика всей базы")}
              </p>
            </div>
          </div>
          <div className="analytics-columns">
            {samples.map((sample) => (
              <section
                className="panel analytics-panel"
                key={String(sample.collection)}
              >
                <div className="panel-heading">
                  <h2>
                    {t(
                      sample.collection === "battery"
                        ? "Батарея"
                        : "Местоположение",
                    )}
                  </h2>
                  <span className="analytics-pill">{t("Выборка")}</span>
                </div>
                <dl className="analytics-facts">
                  {[
                    ["Прочитано документов", sample.sampled_documents],
                    ["Корректные наблюдения", sample.valid_observations],
                    ["Некорректные наблюдения", sample.invalid_observations],
                    [
                      "Недавние обновления сервера",
                      sample.recent_server_updates,
                    ],
                    [
                      sample.collection === "battery"
                        ? "Наблюдения низкого заряда"
                        : "Наблюдения точной геолокации",
                      sample.collection === "battery"
                        ? sample.low_battery_observations
                        : sample.precise_location_observations,
                    ],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt>{t(String(label))}</dt>
                      <dd>{number(value)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="analytics-footnote">
                  {t(
                    sample.more_documents === true
                      ? "За пределами выборки есть другие документы."
                      : "Признак продолжения выборки не установлен.",
                  )}
                </p>
              </section>
            ))}
          </div>
          {!samples.length && (
            <p className="notice notice-warning">
              {t("Сохранённая выборка не прошла проверку")}
            </p>
          )}
          <p className="analytics-footnote">
            {t(
              "Координаты и идентификаторы не показываются. Эти записи не определяют активность родителей.",
            )}
          </p>
        </>
      )}
      {source === "parents" && (
        <>
          <div className="analytics-section-title">
            <div>
              <h2>{t("Родительские аккаунты MANA")}</h2>
              <p className="muted">
                {t("Количество по API и отдельная ограниченная выборка")}
              </p>
            </div>
          </div>
          <section
            className="metric-grid"
            aria-label={t("Показатели Parent API")}
          >
            <MetricCard
              label={t("Всего по счётчику API")}
              value={number(facts.total_parents)}
              accent="blue"
            />
            <MetricCard
              label={t("Родителей в выборке")}
              value={number(facts.sampled_parents)}
            />
            <MetricCard
              label={t("С привязанными детьми")}
              value={number(facts.parents_with_children)}
              detail={t("Только в выборке")}
            />
            <MetricCard
              label={t("С текущим тарифом")}
              value={number(facts.parents_with_current_tariff)}
              detail={t("Не подтверждает оплату")}
            />
          </section>
          <section className="panel analytics-panel">
            <div className="panel-heading">
              <h2>{t("Состав выборки")}</h2>
            </div>
            <dl className="analytics-facts">
              {[
                [
                  "С подключёнными детьми",
                  facts.parents_with_connected_children,
                ],
                ["Без текущего тарифа", facts.parents_without_current_tariff],
                [
                  "Тариф истекает в 7 дней",
                  facts.tariffs_expiring_within_7_days,
                ],
                [
                  "Тариф истекает в 30 дней",
                  facts.tariffs_expiring_within_30_days,
                ],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <dt>{t(String(label))}</dt>
                  <dd>{number(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
          <p className="analytics-footnote">
            {t(
              "Тариф может быть бесплатным. Оплаты, выручка и удержание платящих по этим данным неизвестны.",
            )}
          </p>
        </>
      )}
      <details className="panel analytics-method">
        <summary>{t("Источник и ограничения")}</summary>
        <dl className="analytics-facts">
          <div>
            <dt>{t("Отчёт создан")}</dt>
            <dd>{formatDate(report.created_at, locale)}</dd>
          </div>
          <div>
            <dt>{t("Отчёт")}</dt>
            <dd>{report.report_id}</dd>
          </div>
        </dl>
        {notes.length > 0 && (
          <ul>
            {notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        )}
        <p>
          {t(
            "Срок кэша и время создания отчёта не подтверждают текущий охват пользователей.",
          )}
        </p>
      </details>
    </>
  );
}

export function AnalyticsPage(): React.JSX.Element {
  const { t, locale } = useI18n();
  const [source, setSource] = useState<AnalyticsSource>("ga4");
  const [selected, setSelected] = useState<string | null>(null);
  const ga4 = useSavedReports("ga4"),
    firestore = useSavedReports("firestore"),
    parents = useSavedReports("parents");
  const queries = { ga4, firestore, parents };
  const query = queries[source];
  const reports = (query.data?.items ?? [])
    .map((report) => savedAnalytics(report, source))
    .filter((report): report is SavedAnalytics => report !== null);
  const current =
    reports.find((item) => item.report.report_id === selected) ?? reports[0];
  return (
    <div className="analytics-workspace">
      <PageHeader
        eyebrow={t("Профессиональный режим")}
        title={t("Аналитика и данные")}
        description={t(
          "MANA · Сохранённые отчёты, без новых чтений источников.",
        )}
        actions={
          <button
            type="button"
            className="button secondary"
            disabled={query.isValidating}
            onClick={() => void query.mutate().catch(() => undefined)}
          >
            {t("Обновить экран")}
          </button>
        }
      />
      <div className="analytics-source-grid" aria-label={t("Источники данных")}>
        {(Object.keys(ANALYTICS_SOURCES) as AnalyticsSource[]).map((key) => {
          const latest = queries[key].data?.items
            .map((report) => savedAnalytics(report, key))
            .find((item) => item !== null);
          return (
            <button
              key={key}
              className={`analytics-source-card${source === key ? " selected" : ""}`}
              aria-pressed={source === key}
              type="button"
              onClick={() => {
                setSource(key);
                setSelected(null);
              }}
            >
              <span
                className={`analytics-source-icon ${key}`}
                aria-hidden="true"
              >
                {key === "ga4" ? "G" : key === "firestore" ? "F" : "P"}
              </span>
              <span>
                <strong>{ANALYTICS_SOURCES[key].label}</strong>
                <span>
                  {t(
                    key === "ga4"
                      ? "Активность родителей"
                      : key === "firestore"
                        ? "Телеметрия устройств"
                        : "Родительские аккаунты",
                  )}
                </span>
                <small>
                  {queries[key].error
                    ? t("Отчёты недоступны")
                    : queries[key].isLoading
                      ? t("Загрузка…")
                      : latest
                        ? formatDate(latest.collectedAt, locale)
                        : t("Нет сохранённых данных")}
                </small>
              </span>
            </button>
          );
        })}
      </div>
      <QueryState
        error={query.error}
        loading={query.isLoading}
        hasData={Boolean(current) && !query.error}
        retrying={query.isValidating}
        onRetry={query.mutate}
        subject={t("отчёт")}
      />
      {current && !query.error ? (
        <>
          <div className="analytics-report-picker">
            <span className="analytics-pill">
              MANA · {ANALYTICS_SOURCES[source].label}
            </span>
            <label>
              {t("Сохранённый срез")}{" "}
              <select
                value={current.report.report_id}
                onChange={(event) => setSelected(event.target.value)}
              >
                {reports.map((item) => (
                  <option
                    key={item.report.report_id}
                    value={item.report.report_id}
                  >
                    {formatDate(item.collectedAt, locale)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {query.data && query.data.total > query.data.items.length && (
            <p className="analytics-footnote">
              {t("Показаны последние 5 отчётов этого источника.")}
            </p>
          )}
          <SourceReport
            key={current.report.report_id}
            saved={current}
            source={source}
          />
        </>
      ) : (
        !query.isLoading &&
        !query.error && (
          <EmptyState
            title={t("Нет подтверждённого сохранённого отчёта")}
            detail={t(
              "Получить новые данные можно через агента с отдельным подтверждением. Открытие этого экрана не запускает сбор.",
            )}
          />
        )
      )}
      <div className="analytics-bottom-links">
        <Link href="/chat/retention-agent">{t("Обсудить с агентом")} →</Link>
        <Link href="/runs">{t("Открыть журнал")}</Link>
      </div>
    </div>
  );
}
