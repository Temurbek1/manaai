"use client";

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
        eyebrow="Агенты администрации"
        title="Удержание и лояльность"
        description="Что известно об активности пользователей, чего не хватает для выводов и что требует внимания."
        actions={
          <button
            className="button secondary"
            disabled={isValidating}
            onClick={() => void mutate().catch(() => undefined)}
            type="button"
          >
            {isValidating ? "Обновляем экран…" : "Обновить экран"}
          </button>
        }
      />
      {data ? (
        <p
          className={data.mode === "live" ? "notice" : "notice notice-warning"}
        >
          <strong>{MODE_LABELS[data.mode]}.</strong> Просмотр и обновление этой
          страницы не обращаются к Firebase и другим внешним источникам.
        </p>
      ) : null}
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={mutate}
        subject="отчёт"
      />
      {data?.latest_run?.status === "failed" ? (
        <p className="error-banner" role="alert">
          Последний анализ завершился ошибкой. Ниже показаны данные предыдущего
          успешного запуска, если они доступны. Подробности — в журнале.
        </p>
      ) : null}
      {!snapshot ? (
        data && !error ? (
          <EmptyState
            title={
              isLoading ? "Загружаем данные" : "Пока нет завершённого анализа"
            }
            detail="После успешного запланированного анализа здесь появятся сохранённые показатели и выводы. Никакие данные не подставляются вместо отсутствующих."
          />
        ) : null
      ) : (
        <>
          <section className="panel">
            <h2>Как читать этот отчёт</h2>
            <p>
              Период: {formatDate(snapshot.period_start)} —{" "}
              {formatDate(snapshot.period_end)}.
            </p>
            <p>
              Данные получены: {formatDate(snapshot.collected_at)}. Технический
              показатель полноты:{" "}
              <strong>{percent(snapshot.completeness)}</strong>.
            </p>
            {data &&
            data.snapshot_age_seconds !== null &&
            data.snapshot_age_seconds !== undefined &&
            data.snapshot_age_seconds > 21600 ? (
              <p className="notice notice-warning">
                Данным больше шести часов. Это сохранённый результат, не текущая
                проверка приложения.
              </p>
            ) : null}
            <p>
              Это агрегаты активности и состояния устройств. Они не показывают
              процент удержания платящих клиентов, выручку или вероятность ухода
              конкретного человека.
            </p>
            <p className="notice notice-warning">
              Разделение MANA и 360REC в этом снимке не подтверждено. Не
              используйте эти агрегаты как показатели отдельного приложения.
            </p>
            {!mobileAvailable ? (
              <p className="notice notice-warning">
                <strong>Мобильная аналитика в снимке недоступна.</strong> Сеансы
                и поведение в приложении нельзя оценивать по состоянию
                устройств. Обновление экрана не подключает GA4.
              </p>
            ) : null}
          </section>
          <section className="metric-grid" aria-label="Показатели приложения">
            <MetricCard
              label="Детские аккаунты"
              value={snapshot.total_children}
              detail="Количество по данным backend, не число платящих родителей"
            />
            <MetricCard
              label="Аккаунты с активностью"
              value={snapshot.backend_active_children}
              detail="По собранным данным приложения; учитывайте полноту выборки"
              accent="blue"
            />
            <MetricCard
              label="Новые родительские аккаунты"
              value={snapshot.parent_accounts_joined}
              detail="Регистрации за период отчёта"
            />
            <MetricCard
              label="Сеансы мобильного приложения"
              value={mobileAvailable ? snapshot.mobile_sessions : "Нет данных"}
              detail={
                mobileAvailable
                  ? "По доступной мобильной аналитике"
                  : "Не заменяем отсутствующую аналитику нулём"
              }
              accent="amber"
            />
          </section>
          <section className="panel">
            <p className="eyebrow">Выводы и следующие шаги</p>
            <h2>На что обратить внимание</h2>
            {(data?.findings ?? []).map((finding) => {
              const copy = FINDING_LABELS[finding.finding_type];
              return (
                <article className="retention-finding" key={finding.finding_id}>
                  <h3>{copy?.title ?? "Наблюдение агента"}</h3>
                  <StatusBadge status={finding.severity} />
                  <p>
                    {copy?.explanation ??
                      "Смотрите исходное наблюдение и подтверждающие данные ниже."}
                  </p>
                  <details>
                    <summary>Основание вывода</summary>
                    <p>{finding.description}</p>
                    <p>{finding.deterministic_calculation}</p>
                  </details>
                </article>
              );
            })}
            {!data?.findings?.length ? (
              <p>
                В этом запуске предупреждений не сформировано. Это не
                подтверждение отсутствия риска ухода клиентов.
              </p>
            ) : null}
          </section>
          <section className="panel">
            <p className="eyebrow">Достоверность отчёта</p>
            <h2>Источники и полнота данных</h2>
            <DataTable
              caption="Источники сохранённого отчёта"
              items={snapshot.evidence_refs}
              getKey={(item) => item.source}
              columns={[
                {
                  key: "source",
                  label: "Источник",
                  render: (item) => labelFor(item.source),
                },
                {
                  key: "coverage",
                  label: "Техническая полнота",
                  render: (item) => percent(item.completeness),
                },
                {
                  key: "date",
                  label: "Получены",
                  render: (item) => formatDate(item.collected_at),
                },
              ]}
              empty={<p>Источники не указаны.</p>}
            />
            <p>
              Это показатель адаптера, а не процент охваченных пользователей и
              не точность прогноза. Даже 100% не означает, что прочитана вся
              база. Ограниченная выборка не является статистикой всех
              пользователей.
            </p>
            {snapshot.limitations?.length ? (
              <details>
                <summary>
                  Ограничения источников — {snapshot.limitations.length}
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
              <h2>Состояние устройств в выборке Firebase</h2>
              <p>
                Прочитано документов в этом анализе:{" "}
                <strong>{telemetry.documents_scanned}</strong>. Это не общий
                счётчик Firebase и не сумма расходов.
              </p>
              <div className="metric-grid">
                <MetricCard
                  label="Записи о батарее"
                  value={telemetry.battery_devices}
                  detail="Только выбранные документы"
                />
                <MetricCard
                  label="Устройства с данными местоположения"
                  value={telemetry.located_devices}
                  detail="Координаты здесь не показываются"
                />
                <MetricCard
                  label="Записи о подключении"
                  value={telemetry.internet_records}
                />
                <MetricCard
                  label="Мониторинг включён"
                  value={telemetry.monitoring_enabled}
                  detail="В пределах прочитанной выборки"
                />
              </div>
            </section>
          ) : null}
        </>
      )}
      <section className="panel">
        <h2>История анализов</h2>
        <DataTable
          caption="История анализов удержания"
          items={data?.recent_runs ?? []}
          getKey={(item) => item.run_id}
          columns={[
            {
              key: "date",
              label: "Начало",
              render: (item) => formatDate(item.started_at),
            },
            {
              key: "status",
              label: "Результат",
              render: (item) => <StatusBadge status={item.status} />,
            },
            {
              key: "finished",
              label: "Завершение",
              render: (item) => formatDate(item.completed_at),
            },
          ]}
          empty={data && !error ? <p>Запусков пока нет.</p> : null}
        />
        <p>
          <Link href="/runs">Открыть журнал запусков</Link> ·{" "}
          <Link href="/agents">Настройки и расписание агента</Link>
        </p>
      </section>
      <section className="panel">
        <h2>Действия по удержанию</h2>
        <p>
          Персональные зоны риска, отправка предложений, скидки и реферальные
          награды ещё не подключены. Для них нужны сведения о подписках и
          разрешённые способы выполнения действий. Этот экран не отправляет
          сообщения и не меняет подписки.
        </p>
      </section>
    </div>
  );
}
