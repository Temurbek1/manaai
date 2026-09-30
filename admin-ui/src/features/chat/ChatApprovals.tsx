"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import {
  apiGet,
  apiPost,
  type ApprovalLifecycle,
  type ApprovalPage,
  type Proposal,
  type ProposalPage,
} from "@/api/client";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { QueryState } from "@/components/QueryState";
import { labelFor } from "@/ui/labels";
import { formatDate } from "@/ui/format";

const APPROVALS = "/api/v1/admin/operation/approvals?status=pending&limit=100";

export function ChatApprovals({
  runId,
}: {
  runId?: string | undefined;
}): React.JSX.Element {
  const query = new URLSearchParams({ limit: "100" });
  if (runId) query.set("run_id", runId);
  const key = `/api/v1/admin/operation/action-proposals?${query.toString()}`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    ProposalPage,
    Error
  >(key);
  const {
    data: approvals,
    error: approvalError,
    mutate: refreshApprovals,
  } = useSWR<ApprovalPage, Error>(APPROVALS);
  const proposals = (data?.items ?? [])
    .filter((item) =>
      ["growth-agent", "marketing-agent"].includes(item.agent_id),
    )
    .slice(0, 3);
  return (
    <section className="chat-approvals" aria-label="Предложения агента">
      <h3>Предложения агента</h3>
      <p>
        Привязка предложений к MANA / 360REC не подтверждена. Проверьте источник
        и объект перед решением.
      </p>
      <QueryState
        error={error || approvalError}
        loading={isLoading || !approvals}
        hasData={Boolean(data && approvals)}
        retrying={isValidating}
        onRetry={() => Promise.all([mutate(), refreshApprovals()])}
        subject="предложения"
      />
      {data &&
        approvals &&
        !error &&
        !approvalError &&
        proposals.length === 0 && <p>В сохранённой выборке предложений нет.</p>}
      {proposals.map((proposal) => (
        <ProposalCard
          key={proposal.proposal_id}
          proposal={proposal}
          pendingAuthor={
            approvals?.items.find(
              (item) => item.proposal_id === proposal.proposal_id,
            )?.requested_by
          }
          unavailable={!approvals || Boolean(error || approvalError)}
          refresh={async () => {
            await Promise.all([mutate(), refreshApprovals()]);
          }}
          sourceKey={key}
        />
      ))}
      <Link href="/approvals">Все предложения и технические подробности ↗</Link>
    </section>
  );
}

function ProposalCard({
  proposal,
  pendingAuthor,
  unavailable,
  refresh,
  sourceKey,
}: {
  proposal: Proposal;
  pendingAuthor: string | undefined;
  unavailable: boolean;
  refresh: () => Promise<void>;
  sourceKey: string;
}): React.JSX.Element {
  const { session } = useSession();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [openedAt] = useState(() => Date.now());
  const self = pendingAuthor === session.user.user_id;
  const disabled =
    unavailable ||
    busy ||
    !hasRole(session, "approver") ||
    !pendingAuthor ||
    self ||
    proposal.status !== "awaiting_approval" ||
    new Date(proposal.expires_at).getTime() <= openedAt;
  async function decide(approve: boolean): Promise<void> {
    if (disabled || !reason.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      const current = (await apiGet<ProposalPage>(sourceKey)).items.find(
        (item) => item.proposal_id === proposal.proposal_id,
      );
      if (
        !current ||
        current.status !== "awaiting_approval" ||
        new Date(current.expires_at).getTime() <= Date.now() ||
        current.current_state_hash !== proposal.current_state_hash ||
        JSON.stringify(current.parameters) !==
          JSON.stringify(proposal.parameters)
      )
        throw new Error(
          "Предложение изменилось. Проверьте обновлённые данные перед новым решением.",
        );
      const result = await apiPost<ApprovalLifecycle>(
        `/api/v1/admin/operation/approvals/${proposal.proposal_id}/decision`,
        { approve, reason: reason.trim(), correlation_id: crypto.randomUUID() },
      );
      setNotice(
        !approve
          ? "Предложение отклонено."
          : proposal.execution_forbidden
            ? "Ознакомление подтверждено. Изменения в источнике запрещены."
            : `Решение принято. ${labelFor(result.execution?.status ?? "queued")}.`,
      );
      await refresh();
    } catch (caught) {
      setNotice(
        caught instanceof Error
          ? caught.message
          : "Не удалось подтвердить результат. Обновите состояние перед повтором.",
      );
      await refresh().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="chat-proposal-card">
      <header>
        <strong>{labelFor(proposal.action_type)}</strong>
        <span>{labelFor(proposal.status)}</span>
      </header>
      <p className="chat-provider-mode">
        {proposal.execution_forbidden
          ? "Только рекомендация: изменения в Meta запрещены"
          : `Режим: ${labelFor(proposal.provider_mode)}`}
      </p>
      <p>{proposal.reasoning}</p>
      <p>
        <strong>Ожидаемый эффект:</strong> {proposal.expected_effect}
      </p>
      <dl>
        <dt>Источник и объект</dt>
        <dd>
          {proposal.provider} · {proposal.object_type} ·{" "}
          {proposal.provider_object_id}
        </dd>
        <dt>Действует до</dt>
        <dd>{formatDate(proposal.expires_at)}</dd>
      </dl>
      <details>
        <summary>Что именно изменится</summary>
        <dl>
          {Object.entries(proposal.parameters)
            .filter(([key]) => key !== "kind")
            .map(([key, value]) => (
              <div key={key}>
                <dt>{labelFor(key)}</dt>
                <dd>
                  {typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
                </dd>
              </div>
            ))}
        </dl>
      </details>
      {proposal.risks.length > 0 && (
        <ul>
          {proposal.risks.map((risk) => (
            <li key={risk}>{risk}</li>
          ))}
        </ul>
      )}
      {proposal.missing_data.length > 0 && (
        <p>Не хватает данных: {proposal.missing_data.join("; ")}</p>
      )}
      {self && (
        <p>Это ваше предложение. Решение должен принять другой сотрудник.</p>
      )}
      {proposal.status === "awaiting_approval" && (
        <>
          <label htmlFor={`chat-reason-${proposal.proposal_id}`}>
            Причина решения
          </label>
          <textarea
            id={`chat-reason-${proposal.proposal_id}`}
            value={reason}
            disabled={disabled}
            maxLength={1000}
            onChange={(event) => setReason(event.target.value)}
            rows={2}
          />
          <div className="chat-decision-buttons">
            <ConfirmAction
              className="button secondary compact"
              label={proposal.execution_forbidden ? "Ознакомиться" : "Одобрить"}
              confirmLabel={
                proposal.execution_forbidden
                  ? "Подтвердить ознакомление"
                  : "Подтвердить решение"
              }
              description={
                proposal.execution_forbidden
                  ? "Вы подтверждаете ознакомление. Изменения в Meta не выполняются."
                  : "Одобрение может сразу запустить действие в указанном режиме источника. Проверьте параметры изменения, риски и объект."
              }
              disabled={disabled || !reason.trim()}
              onConfirm={() => void decide(true)}
            />
            <ConfirmAction
              className="button secondary compact"
              label="Отклонить"
              confirmLabel="Подтвердить отклонение"
              disabled={disabled || !reason.trim()}
              onConfirm={() => void decide(false)}
            />
          </div>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </article>
  );
}
