"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import { useId, useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { QueryState } from "@/components/QueryState";
import { labelFor } from "@/ui/labels";

type Action = components["schemas"]["WorkspaceActionView"];
type Page = components["schemas"]["WorkspaceActionPage"];

export function WorkspaceActions({
  topicId,
  turnId,
}: {
  topicId: string;
  turnId: string;
}): React.JSX.Element {
  const { t } = useI18n();

  const url = `/api/v1/admin/operation/workspace/topics/${encodeURIComponent(topicId)}/messages/${encodeURIComponent(turnId)}/actions`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<Page, Error>(
    url,
    {
      refreshInterval: (page) =>
        page?.items?.some(
          (item) =>
            item.receipt &&
            ["dispatching", "unknown"].includes(item.receipt.state) &&
            item.status === "executing",
        )
          ? 15000
          : 0,
    },
  );
  return (
    <section className="chat-approvals" aria-label={t("Действия в этой теме")}>
      <h3>{t("Тестовые эксперименты MANA")}</h3>
      <p>{t("Sandbox. Реальные пользователи и платежи не меняются.")}</p>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={() => mutate()}
        subject={t("действия")}
      />
      {data && !error && (data.items ?? []).length === 0 && (
        <p>{t("Подходящих предложений пока нет.")}</p>
      )}
      {data &&
        !error &&
        (data.items ?? []).map((item) => (
          <ActionCard
            key={item.proposal_id}
            action={item}
            url={url}
            refresh={async () => {
              await mutate();
            }}
          />
        ))}
      {data?.more_omitted && (
        <p>{t("Показаны только три предложения из ограниченной выборки.")}</p>
      )}
    </section>
  );
}

function ActionCard({
  action,
  url,
  refresh,
}: {
  action: Action;
  url: string;
  refresh: () => Promise<void>;
}): React.JSX.Element {
  const { t } = useI18n();

  const { session } = useSession();
  const id = useId();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const sent = useRef(false);
  const [openedAt] = useState(() => Date.now());
  const disabled =
    busy ||
    Boolean(action.receipt) ||
    !hasRole(session, "approver") ||
    action.self_approval_forbidden ||
    action.status !== "awaiting_approval" ||
    new Date(action.expires_at).getTime() <= openedAt;
  const [attempted, setAttempted] = useState(false);

  async function decide(approve: boolean): Promise<void> {
    if (disabled || !reason.trim() || sent.current) return;
    sent.current = true;
    setAttempted(true);
    setBusy(true);
    setNotice(null);
    try {
      await apiPost<Action>(
        `${url}/${encodeURIComponent(action.proposal_id)}/decision`,
        {
          request_id: crypto.randomUUID(),
          confirmed: true,
          approve,
          reason: reason.trim(),
          fingerprint: action.fingerprint,
        },
      );
    } catch {
      setNotice(
        t("Ответ не подтверждён. Повтор не отправлен. Обновите статус."),
      );
    } finally {
      await refresh().catch(() => {
        setNotice(t("Статус недоступен. Повтор не отправлен."));
      });
      setBusy(false);
    }
  }

  return (
    <article className="chat-proposal-card">
      <header>
        <strong>{t("Создать тестовый черновик эксперимента")}</strong>
        <span>{t(labelFor(action.status))}</span>
      </header>
      <details open={!action.receipt}>
        <summary>{t("Параметры и результат")}</summary>
        <p>
          {t("Гипотеза:")} {action.parameters.hypothesis}
        </p>
        <p>{action.reasoning}</p>
        <dl>
          <dt>{t("Метрика")}</dt>
          <dd>{t(labelFor(action.parameters.primary_metric))}</dd>
          <dt>{t("Аудитория")}</dt>
          <dd>{t(labelFor(action.parameters.audience_segment))}</dd>
          <dt>{t("Доля и срок")}</dt>
          <dd>
            {action.parameters.allocation_percent}% ·{" "}
            {action.parameters.duration_days} {t("дней")}{" "}
          </dd>
          <dt>{t("Объект")}</dt>
          <dd>{action.parameters.experiment_key}</dd>
        </dl>
        {action.risks.length > 0 && (
          <p>
            {t("Риски:")} {action.risks.join("; ")}
          </p>
        )}
        <p>
          {t("Ожидаемый эффект — гипотеза:")} {action.expected_effect}
        </p>
      </details>
      {action.receipt ? (
        <div role="status">
          <p>{action.receipt.message}</p>
          <p>
            {t("Исполнение:")}{" "}
            {t(labelFor(action.execution_status ?? "not_started"))}
            {t(". Проверка:")}{" "}
            {t(labelFor(action.verification_status ?? "not_started"))}.
          </p>
          <p>{t("Влияние на конверсию не измерено.")}</p>
        </div>
      ) : (
        <>
          {action.self_approval_forbidden && (
            <p>{t("Решение должен принять другой сотрудник.")}</p>
          )}
          <label htmlFor={id}>{t("Причина решения")}</label>
          <textarea
            id={id}
            value={reason}
            disabled={disabled || attempted}
            maxLength={1000}
            rows={2}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="chat-decision-buttons">
            <ConfirmAction
              className="button secondary compact"
              label={t("Создать в sandbox")}
              confirmLabel={t("Подтвердить создание")}
              disabled={disabled || attempted || !reason.trim()}
              description={t(
                "Создать только тестовый черновик {0}: {1}% аудитории, {2} дней. Реальные пользователи не затрагиваются.",
                {
                  "0": action.parameters.experiment_key,
                  "1": action.parameters.allocation_percent,
                  "2": action.parameters.duration_days,
                },
              )}
              onConfirm={() => void decide(true)}
            />
            <ConfirmAction
              className="button secondary compact"
              label={t("Отклонить")}
              confirmLabel={t("Подтвердить отклонение")}
              disabled={disabled || attempted || !reason.trim()}
              onConfirm={() => void decide(false)}
            />
          </div>
        </>
      )}
      {notice && <p role="status">{t(notice)}</p>}
      <button
        type="button"
        className="button secondary compact"
        disabled={busy}
        onClick={() =>
          void refresh().catch(() => setNotice(t("Статус недоступен.")))
        }
      >
        {t("Обновить статус")}{" "}
      </button>
    </article>
  );
}
