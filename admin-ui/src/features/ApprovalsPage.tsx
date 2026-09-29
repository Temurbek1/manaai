"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import {
  apiPost,
  type ApprovalLifecycle,
  type ApprovalPage,
  type Proposal,
  type ProposalPage,
} from "../api/client";
import { hasRole, useSession } from "../auth/SessionContext";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { labelFor } from "../ui/labels";
import { compactId, formatDate } from "../ui/format";
import { isRecord } from "../ui/format";

const PENDING_APPROVALS_KEY =
  "/api/v1/admin/operation/approvals?status=pending&limit=100";
const APPROVAL_HISTORY_KEY = "/api/v1/admin/operation/approvals?limit=100";
const PROPOSALS_KEY = "/api/v1/admin/operation/action-proposals?limit=100";

function parameterValue(
  parameters: unknown,
  keys: readonly string[],
  fallback: string,
): string {
  if (!isRecord(parameters)) return fallback;
  const value = keys
    .map((key) => parameters[key])
    .find((item) => item !== undefined);
  return typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
    ? String(value)
    : fallback;
}

export function ApprovalsPage(): React.JSX.Element {
  const { session } = useSession();
  const canDecide = hasRole(session, "approver");
  const { data: approvals, error: approvalsError } = useSWR<
    ApprovalPage,
    Error
  >(PENDING_APPROVALS_KEY, { refreshInterval: 10_000 });
  const { data: approvalHistory, error: historyError } = useSWR<
    ApprovalPage,
    Error
  >(APPROVAL_HISTORY_KEY, { refreshInterval: 30_000 });
  const {
    data: proposals,
    error: proposalsError,
    isLoading,
  } = useSWR<ProposalPage, Error>(PROPOSALS_KEY, { refreshInterval: 10_000 });
  const { mutate } = useSWRConfig();
  const [reasonByProposal, setReasonByProposal] = useState<
    Record<string, string>
  >({});
  const [busyProposal, setBusyProposal] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [bulkReason, setBulkReason] = useState("");
  const approvalByProposal = new Map(
    (approvals?.items ?? []).map((approval) => [
      approval.proposal_id,
      approval,
    ]),
  );

  async function decide(proposal: Proposal, approve: boolean): Promise<void> {
    const reason = reasonByProposal[proposal.proposal_id]?.trim();
    if (!reason) {
      setMessage("Укажите причину решения перед одобрением или отклонением.");
      return;
    }
    setBusyProposal(proposal.proposal_id);
    setMessage(null);
    try {
      const freshProposals = await mutate<ProposalPage>(PROPOSALS_KEY);
      const freshProposal = freshProposals?.items.find(
        (item) => item.proposal_id === proposal.proposal_id,
      );
      if (!freshProposal || freshProposal.status !== "awaiting_approval") {
        throw new Error(
          "Предложение больше не ожидает согласования. Очередь обновлена.",
        );
      }
      const result = await apiPost<ApprovalLifecycle>(
        `/api/v1/admin/operation/approvals/${proposal.proposal_id}/decision`,
        {
          approve,
          reason,
          correlation_id: crypto.randomUUID(),
        },
      );
      setMessage(
        approve
          ? proposal.execution_forbidden
            ? "Ознакомление подтверждено. Выполнение изменений по-прежнему запрещено."
            : `Одобрено. ${labelFor(result.execution?.status ?? "queued")}.`
          : "Предложение отклонено.",
      );
      await Promise.all([
        mutate(PENDING_APPROVALS_KEY),
        mutate(APPROVAL_HISTORY_KEY),
        mutate(PROPOSALS_KEY),
        mutate("/api/v1/admin/operation/dashboard"),
      ]);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Не удалось сохранить решение",
      );
    } finally {
      setBusyProposal(null);
    }
  }

  async function bulkDecide(approve: boolean): Promise<void> {
    setBusyProposal("bulk");
    setMessage(null);
    try {
      const freshProposals = await mutate<ProposalPage>(PROPOSALS_KEY);
      const selectedProposals = (freshProposals?.items ?? []).filter(
        (proposal) => selected.has(proposal.proposal_id),
      );
      if (!bulkReason.trim() || selectedProposals.length === 0) {
        throw new Error("Выберите предложения и укажите причину решения.");
      }
      const actionTypes = new Set(
        selectedProposals.map((proposal) => proposal.action_type),
      );
      if (
        actionTypes.size !== 1 ||
        (approve && !actionTypes.has("decrease_budget"))
      ) {
        throw new Error(
          "Одновременно можно одобрить только однотипные действия по снижению бюджета.",
        );
      }
      await apiPost("/api/v1/admin/operation/approvals/bulk-decision", {
        proposal_ids: selectedProposals.map((proposal) => proposal.proposal_id),
        approve,
        reason: bulkReason.trim(),
        correlation_id: crypto.randomUUID(),
      });
      setMessage(
        approve
          ? "Снижения бюджета одобрены."
          : "Выбранные действия отклонены.",
      );
      setSelected(new Set());
      setBulkReason("");
      await Promise.all([
        mutate(PENDING_APPROVALS_KEY),
        mutate(APPROVAL_HISTORY_KEY),
        mutate(PROPOSALS_KEY),
      ]);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Не удалось сохранить групповое решение",
      );
    } finally {
      setBusyProposal(null);
    }
  }

  const items = (proposals?.items ?? []).filter(
    (proposal) =>
      proposal.status === "awaiting_approval" || proposal.status === "expired",
  );
  return (
    <>
      <PageHeader
        eyebrow="Ожидают вашего решения"
        title="Согласования"
        description="Перед решением проверьте, что изменится, на чём основано предложение и какие есть риски."
      />
      {approvalsError || historyError || proposalsError ? (
        <p className="error-banner" role="alert">
          Не удалось обновить очередь. Действия по устаревшим данным не
          выполняются.
        </p>
      ) : null}
      {isLoading ? (
        <p className="notice" role="status">
          Обновляем очередь согласований…
        </p>
      ) : null}
      {message ? (
        <p className="notice" role="status">
          {message}
        </p>
      ) : null}
      {items.length > 0 ? (
        <section
          className="panel bulk-bar"
          aria-label="Решение по выбранным действиям"
        >
          <label className="field">
            <span>Причина решения по выбранным действиям</span>
            <input
              onChange={(event) => setBulkReason(event.target.value)}
              value={bulkReason}
            />
          </label>
          <span>Выбрано: {selected.size}</span>
          <button
            className="button secondary compact"
            disabled={
              !canDecide || busyProposal !== null || selected.size === 0
            }
            onClick={() => void bulkDecide(false)}
            type="button"
          >
            Отклонить выбранные
          </button>
          <button
            className="button compact"
            disabled={
              !canDecide || busyProposal !== null || selected.size === 0
            }
            onClick={() => void bulkDecide(true)}
            type="button"
          >
            Одобрить снижение бюджетов
          </button>
        </section>
      ) : null}
      <section className="approval-grid">
        {items.map((proposal) => {
          const approval = approvalByProposal.get(proposal.proposal_id);
          const isBusy = busyProposal === proposal.proposal_id;
          const isLiveAdvisory = proposal.execution_forbidden;
          const isSelfApproval =
            approval?.requested_by === session.user.user_id;
          const decisionDisabled =
            !canDecide ||
            isBusy ||
            proposal.status !== "awaiting_approval" ||
            isSelfApproval;
          return (
            <article className="approval-card" key={proposal.proposal_id}>
              <header>
                <input
                  aria-label={`Выбрать: ${labelFor(proposal.action_type)}`}
                  checked={selected.has(proposal.proposal_id)}
                  disabled={decisionDisabled || isLiveAdvisory}
                  onChange={(event) => {
                    setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(proposal.proposal_id);
                      else next.delete(proposal.proposal_id);
                      return next;
                    });
                  }}
                  type="checkbox"
                />
                <div>
                  <p className="eyebrow">{proposal.object_type}</p>
                  <h2>{labelFor(proposal.action_type)}</h2>
                </div>
                <StatusBadge status={proposal.status} />
              </header>
              {isLiveAdvisory ? (
                <p className="live-advisory-note">
                  <strong>META — РЕКОМЕНДАЦИЯ БЕЗ ИЗМЕНЕНИЙ</strong>
                  Одобрение не отправляет изменения в Meta. Это рекомендация для
                  ознакомления.
                </p>
              ) : null}
              {isSelfApproval ? (
                <p className="error-banner" role="status">
                  Нельзя согласовать собственное предложение. Решение должен
                  принять другой сотрудник.
                </p>
              ) : null}
              <dl className="detail-grid">
                <div>
                  <dt>Объект источника</dt>
                  <dd>
                    <code>{compactId(proposal.provider_object_id)}</code>
                  </dd>
                </div>
                <div>
                  <dt>Уверенность</dt>
                  <dd>{proposal.confidence}</dd>
                </div>
                <div>
                  <dt>Кто предложил</dt>
                  <dd>{approval?.requested_by ?? "unknown"}</dd>
                </div>
                <div>
                  <dt>Действует до</dt>
                  <dd>{formatDate(proposal.expires_at)}</dd>
                </div>
                <div>
                  <dt>Режим источника</dt>
                  <dd>{labelFor(proposal.provider_mode)}</dd>
                </div>
              </dl>
              <div className="old-new-grid">
                <div>
                  <span>Сейчас</span>
                  <strong>
                    {parameterValue(
                      proposal.parameters,
                      ["current_daily_budget", "current_status"],
                      "Смотрите основания",
                    )}
                  </strong>
                </div>
                <div>
                  <span>Предлагается</span>
                  <strong>
                    {parameterValue(
                      proposal.parameters,
                      ["proposed_daily_budget", "proposed_status"],
                      "Параметры изменения",
                    )}
                  </strong>
                </div>
              </div>
              <details className="change-box">
                <summary>Технические параметры изменения</summary>
                <pre>{JSON.stringify(proposal.parameters, null, 2)}</pre>
              </details>
              <div className="evidence-block">
                <h3>Основания</h3>
                {proposal.evidence.map((evidence) => (
                  <div key={evidence.name}>
                    <span>{evidence.name}</span>
                    <strong>{evidence.current.value ?? "unavailable"}</strong>
                    <small>{evidence.current.unit}</small>
                  </div>
                ))}
              </div>
              <p>{proposal.reasoning}</p>
              <ul className="risk-list">
                {proposal.risks.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
              {isLiveAdvisory ? (
                <div className="manual-instructions">
                  <h3>Как выполнить вручную в рекламном кабинете</h3>
                  <ol>
                    {(proposal.manual_action_instructions ?? []).map(
                      (instruction) => (
                        <li key={instruction}>{instruction}</li>
                      ),
                    )}
                  </ol>
                </div>
              ) : null}
              <label className="field">
                <span>Причина решения</span>
                <textarea
                  disabled={decisionDisabled}
                  onChange={(event) => {
                    setReasonByProposal((current) => ({
                      ...current,
                      [proposal.proposal_id]: event.target.value,
                    }));
                  }}
                  placeholder="Объясните, почему вы принимаете это решение"
                  value={reasonByProposal[proposal.proposal_id] ?? ""}
                />
              </label>
              <footer>
                <button
                  className="button secondary"
                  disabled={decisionDisabled}
                  onClick={() => void decide(proposal, false)}
                  type="button"
                >
                  Отклонить
                </button>
                <button
                  className="button"
                  disabled={decisionDisabled}
                  onClick={() => void decide(proposal, true)}
                  type="button"
                >
                  {isBusy
                    ? "Сохраняем…"
                    : isLiveAdvisory
                      ? "Подтвердить ознакомление"
                      : "Одобрить"}
                </button>
              </footer>
            </article>
          );
        })}
        {items.length === 0 ? (
          <div className="panel">
            <EmptyState
              title="Всё рассмотрено"
              detail="Нет действий, ожидающих согласования."
            />
          </div>
        ) : null}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">История решений</p>
            <h2>Принятые решения</h2>
          </div>
        </div>
        <div className="compact-history">
          {(approvalHistory?.items ?? [])
            .filter((approval) => approval.status !== "pending")
            .map((approval) => (
              <div key={approval.approval_id}>
                <code>{compactId(approval.proposal_id)}</code>
                <StatusBadge status={approval.status} />
                <time>{formatDate(approval.requested_at)}</time>
              </div>
            ))}
          {(approvalHistory?.items ?? []).every(
            (approval) => approval.status === "pending",
          ) ? (
            <div className="empty-inline">Принятых решений пока нет.</div>
          ) : null}
        </div>
      </section>
    </>
  );
}
