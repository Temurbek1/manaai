"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import Link from "next/link";
import useSWR from "swr";

import type { RetentionOverview } from "../api/client";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { QueryState } from "../components/QueryState";
import { formatDate } from "../ui/format";
import { labelFor } from "../ui/labels";

const MODE_LABELS = {
  live: "Реальные данные",
  demo: "Демонстрационные данные",
  mixed: "Реальные и тестовые данные — не объединять",
  unavailable: "Данные пока не получены",
};

const FINDING_LABELS: Record<string, { title: string; explanation: string }> = {
  engagement_data_incomplete: {
    title: "Данных недостаточно для полного вывода",
    explanation:
      "Часть источников не подключена или ограничена выборкой. Нельзя считать отсутствующие события нулевой активностью и определять уход отдельных клиентов по этим агрегатам.",
  },
  low_backend_engagement: {
    title: "Низкая доля активности в данных приложения",
    explanation:
      "В собранных данных доля детских аккаунтов с активностью ниже настроенного порога. Это сигнал для проверки качества данных и использования функций, а не доказательство ухода платящих родителей.",
  },
  mobile_activity_missing: {
    title: "В источнике нет событий мобильного приложения",
    explanation:
      "Проверьте сбор мобильных событий и период отчёта. Отсутствие событий само по себе не доказывает, что пользователи перестали пользоваться приложением.",
  },
};

function percent(value: string | number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(Number(value));
}

export function RetentionPage(): React.JSX.Element {
  const { t, locale } = useI18n();

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    RetentionOverview,
    Error
  >("/api/v1/admin/operation/retention/overview", { refreshInterval: 30_000 });
  const snapshot = data?.snapshot;
  const mobileAvailable = data?.mobile_analytics_available ?? false;
  const telemetry = snapshot?.operational_telemetry;

  return (
    <div className="retention-workspace">
      <PageHeader
        eyebrow={t("Агенты администрации")}
        title={t("Удержание и лояльность")}
        description={t(
          "Что известно об активности пользователей, чего не хватает для выводов и что требует внимания.",
        )}
        actions={
          <button
            className="button secondary"
            disabled={isValidating}
            onClick={() => void mutate().catch(() => undefined)}
            type="button"
          >
            {isValidating ? t("Обновляем экран…") : t("Обновить экран")}
          </button>
        }
      />
      {data ? (
        <p
          className={data.mode === "live" ? "notice" : "notice notice-warning"}
        >
          <strong>{t(MODE_LABELS[data.mode])}.</strong>{" "}
          {t(
            "Просмотр и обновление этой страницы не обращаются к Firebase и другим внешним источникам.",
          )}{" "}
        </p>
      ) : null}
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={mutate}
        subject={t("отчёт")}
      />
      {data?.latest_run?.status === "failed" ? (
        <p className="error-banner" role="alert">
          {t(
            "Последний анализ завершился ошибкой. Ниже показаны данные предыдущего успешного запуска, если они доступны. Подробности — в журнале.",
          )}{" "}
        </p>
      ) : null}
      {!snapshot ? (
        data && !error ? (
          <EmptyState
            title={
              isLoading
                ? t("Загружаем данные")
                : t("Пока нет завершённого анализа")
            }
            detail={t(
              "После успешного запланированного анализа здесь появятся сохранённые показатели и выводы. Никакие данные не подставляются вместо отсутствующих.",
            )}
          />
        ) : null
      ) : (
        <>
          <section className="panel">
            <h2>{t("Как читать этот отчёт")}</h2>
            <p>
              {t("Период:")} {formatDate(snapshot.period_start, locale)} —{" "}
              {formatDate(snapshot.period_end, locale)}.
            </p>
            <p>
              {t("Данные получены:")}{" "}
              {formatDate(snapshot.collected_at, locale)}
              {t(". Технический показатель полноты:")}{" "}
              <strong>{percent(snapshot.completeness)}</strong>.
            </p>
            {data &&
            data.snapshot_age_seconds !== null &&
            data.snapshot_age_seconds !== undefined &&
            data.snapshot_age_seconds > 21600 ? (
              <p className="notice notice-warning">
                {t(
                  "Данным больше шести часов. Это сохранённый результат, не текущая проверка приложения.",
                )}{" "}
              </p>
            ) : null}
            <p>
              {t(
                "Это агрегаты активности и состояния устройств. Они не показывают процент удержания платящих клиентов, выручку или вероятность ухода конкретного человека.",
              )}{" "}
            </p>
            {snapshot.product_scope === "mana" ? (
              <p>
                {t(
                  "Только MANA. Поведение в приложении — активность родителей, не детей и не заказы.",
                )}{" "}
              </p>
            ) : (
              <p className="notice notice-warning">
                {t(
                  "Разделение MANA и 360REC в этом снимке не подтверждено. Не используйте эти агрегаты как показатели отдельного приложения.",
                )}{" "}
              </p>
            )}
            {!mobileAvailable ? (
              <p className="notice notice-warning">
                <strong>{t("Мобильная аналитика в снимке недоступна.")}</strong>{" "}
                {t(
                  "Сеансы и поведение в приложении нельзя оценивать по состоянию устройств. Обновление экрана не подключает GA4.",
                )}{" "}
              </p>
            ) : null}
          </section>
          <section
            className="metric-grid"
            aria-label={t("Показатели приложения")}
          >
            <MetricCard
              label={t("Детские аккаунты")}
              value={snapshot.total_children}
              detail={t(
                "Количество по данным backend, не число платящих родителей",
              )}
            />
            <MetricCard
              label={t("Дети с активностью в backend")}
              value={snapshot.backend_active_children}
              detail={t(
                "По собранным данным приложения; учитывайте полноту выборки",
              )}
              accent="blue"
            />
            <MetricCard
              label={t("Новые родительские аккаунты")}
              value={snapshot.parent_accounts_joined}
              detail={t("Регистрации за период отчёта")}
            />
            <MetricCard
              label={t("Сеансы мобильного приложения")}
              value={
                mobileAvailable ? snapshot.mobile_sessions : t("Нет данных")
              }
              detail={
                mobileAvailable
                  ? t("По доступной мобильной аналитике")
                  : t("Не заменяем отсутствующую аналитику нулём")
              }
              accent="amber"
            />
            {mobileAvailable && snapshot.mobile_population === "parents" && (
              <MetricCard
                label={t("Активные родители")}
                value={snapshot.mobile_active_subjects}
                detail={t(
                  "За период мобильного отчёта; не доля от детских аккаунтов",
                )}
              />
            )}
          </section>
          <section className="panel">
            <p className="eyebrow">{t("Выводы и следующие шаги")}</p>
            <h2>{t("На что обратить внимание")}</h2>
            {(data?.findings ?? []).map((finding) => {
              const copy = FINDING_LABELS[finding.finding_type];
              return (
                <article className="retention-finding" key={finding.finding_id}>
                  <h3>{t(copy?.title ?? "Наблюдение агента")}</h3>
                  <StatusBadge status={finding.severity} />
                  <p>
                    {t(
                      copy?.explanation ??
                        "Смотрите исходное наблюдение и подтверждающие данные ниже.",
                    )}
                  </p>
                  <details>
                    <summary>{t("Основание вывода")}</summary>
                    <p>{finding.description}</p>
                    <p>{finding.deterministic_calculation}</p>
                  </details>
                </article>
              );
            })}
            {!data?.findings?.length ? (
              <p>
                {t(
                  "В этом запуске предупреждений не сформировано. Это не подтверждение отсутствия риска ухода клиентов.",
                )}{" "}
              </p>
            ) : null}
          </section>
          <section className="panel">
            <p className="eyebrow">{t("Достоверность отчёта")}</p>
            <h2>{t("Источники и полнота данных")}</h2>
            <DataTable
              caption={t("Источники сохранённого отчёта")}
              items={snapshot.evidence_refs}
              getKey={(item) => item.source}
              columns={[
                {
                  key: "source",
                  label: t("Источник"),
                  render: (item) => t(labelFor(item.source)),
                },
                {
                  key: "coverage",
                  label: t("Техническая полнота"),
                  render: (item) => percent(item.completeness),
                },
                {
                  key: "date",
                  label: t("Получены"),
                  render: (item) => formatDate(item.collected_at, locale),
                },
              ]}
              empty={<p>{t("Источники не указаны.")}</p>}
            />
            <p>
              {t(
                "Это показатель адаптера, а не процент охваченных пользователей и не точность прогноза. Даже 100% не означает, что прочитана вся база. Ограниченная выборка не является статистикой всех пользователей.",
              )}{" "}
            </p>
            {snapshot.limitations?.length ? (
              <details>
                <summary>
                  {t("Ограничения источников —")} {snapshot.limitations.length}
                </summary>
                <ul>
                  {snapshot.limitations.map((item, index) => (
                    <li key={`${index}-${item}`}>{item}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>
          {telemetry ? (
            <section className="panel">
              <h2>{t("Состояние устройств в выборке Firebase")}</h2>
              <p>
                {t("Прочитано документов в этом анализе:")}{" "}
                <strong>{telemetry.documents_scanned}</strong>
                {t(". Это не общий счётчик Firebase и не сумма расходов.")}{" "}
              </p>
              <div className="metric-grid">
                <MetricCard
                  label={t("Записи о батарее")}
                  value={telemetry.battery_devices}
                  detail={t("Только выбранные документы")}
                />
                <MetricCard
                  label={t("Устройства с данными местоположения")}
                  value={telemetry.located_devices}
                  detail={t("Координаты здесь не показываются")}
                />
                <MetricCard
                  label={t("Записи о подключении")}
                  value={telemetry.internet_records}
                />
                <MetricCard
                  label={t("Мониторинг включён")}
                  value={telemetry.monitoring_enabled}
                  detail={t("В пределах прочитанной выборки")}
                />
              </div>
            </section>
          ) : null}
        </>
      )}
      <section className="panel">
        <h2>{t("История анализов")}</h2>
        <DataTable
          caption={t("История анализов удержания")}
          items={data?.recent_runs ?? []}
          getKey={(item) => item.run_id}
          columns={[
            {
              key: "date",
              label: t("Начало"),
              render: (item) => formatDate(item.started_at, locale),
            },
            {
              key: "status",
              label: t("Результат"),
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "finished",
              label: t("Завершение"),
              render: (item) => formatDate(item.completed_at, locale),
            },
          ]}
          empty={data && !error ? <p>{t("Запусков пока нет.")}</p> : null}
        />
        <p>
          <Link href="/runs">{t("Открыть журнал запусков")}</Link> ·{" "}
          <Link href="/agents">{t("Настройки и расписание агента")}</Link>
        </p>
      </section>
      <section className="panel">
        <h2>{t("Действия по удержанию")}</h2>
        <p>
          {t(
            "Персональные зоны риска, отправка предложений, скидки и реферальные награды ещё не подключены. Для них нужны сведения о подписках и разрешённые способы выполнения действий. Этот экран не отправляет сообщения и не меняет подписки.",
          )}{" "}
        </p>
      </section>
    </div>
  );
}
