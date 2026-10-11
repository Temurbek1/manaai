"use client";

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
    <section className="chat-approvals" aria-label="Действия в этой теме">
      <h3>Тестовые эксперименты MANA</h3>
      <p>Sandbox. Реальные пользователи и платежи не меняются.</p>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={() => mutate()}
        subject="действия"
      />
      {data && !error && (data.items ?? []).length === 0 && (
        <p>Подходящих предложений пока нет.</p>
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
        <p>Показаны только три предложения из ограниченной выборки.</p>
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
      setNotice("Ответ не подтверждён. Повтор не отправлен. Обновите статус.");
    } finally {
      await refresh().catch(() => {
        setNotice("Статус недоступен. Повтор не отправлен.");
      });
      setBusy(false);
    }
  }

  return (
    <article className="chat-proposal-card">
      <header>
        <strong>Создать тестовый черновик эксперимента</strong>
        <span>{labelFor(action.status)}</span>
      </header>
      <details open={!action.receipt}>
        <summary>Параметры и результат</summary>
        <p>Гипотеза: {action.parameters.hypothesis}</p>
        <p>{action.reasoning}</p>
        <dl>
          <dt>Метрика</dt>
          <dd>{labelFor(action.parameters.primary_metric)}</dd>
          <dt>Аудитория</dt>
          <dd>{labelFor(action.parameters.audience_segment)}</dd>
          <dt>Доля и срок</dt>
          <dd>
            {action.parameters.allocation_percent}% ·{" "}
            {action.parameters.duration_days} дней
          </dd>
          <dt>Объект</dt>
          <dd>{action.parameters.experiment_key}</dd>
        </dl>
        {action.risks.length > 0 && <p>Риски: {action.risks.join("; ")}</p>}
        <p>Ожидаемый эффект — гипотеза: {action.expected_effect}</p>
      </details>
      {action.receipt ? (
        <div role="status">
          <p>{action.receipt.message}</p>
          <p>
            Исполнение: {labelFor(action.execution_status ?? "not_started")}.
            Проверка: {labelFor(action.verification_status ?? "not_started")}.
          </p>
          <p>Влияние на конверсию не измерено.</p>
        </div>
      ) : (
        <>
          {action.self_approval_forbidden && (
            <p>Решение должен принять другой сотрудник.</p>
          )}
          <label htmlFor={id}>Причина решения</label>
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
              label="Создать в sandbox"
              confirmLabel="Подтвердить создание"
              disabled={disabled || attempted || !reason.trim()}
              description={`Создать только тестовый черновик ${action.parameters.experiment_key}: ${action.parameters.allocation_percent}% аудитории, ${action.parameters.duration_days} дней. Реальные пользователи не затрагиваются.`}
              onConfirm={() => void decide(true)}
            />
            <ConfirmAction
              className="button secondary compact"
              label="Отклонить"
              confirmLabel="Подтвердить отклонение"
              disabled={disabled || attempted || !reason.trim()}
              onConfirm={() => void decide(false)}
            />
          </div>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      <button
        type="button"
        className="button secondary compact"
        disabled={busy}
        onClick={() =>
          void refresh().catch(() => setNotice("Статус недоступен."))
        }
      >
        Обновить статус
      </button>
    </article>
  );
}
