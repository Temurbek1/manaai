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
import { compactId, formatDate } from "../ui/format";
import { isRecord } from "../ui/format";

function parameterValue(parameters: unknown, keys: readonly string[], fallback: string): string {
  if (!isRecord(parameters)) return fallback;
  const value = keys.map((key) => parameters[key]).find((item) => item !== undefined);
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : fallback;
}

export function ApprovalsPage(): React.JSX.Element {
  const { session } = useSession();
  const canDecide = hasRole(session, "approver");
  const { data: approvals } = useSWR<ApprovalPage>(
    "/api/v1/admin/operation/approvals?status=pending&limit=100",
  );
  const { data: approvalHistory } = useSWR<ApprovalPage>(
    "/api/v1/admin/operation/approvals?limit=100",
  );
  const { data: proposals } = useSWR<ProposalPage>(
    "/api/v1/admin/operation/action-proposals?limit=100",
  );
  const { mutate } = useSWRConfig();
  const [reasonByProposal, setReasonByProposal] = useState<Record<string, string>>({});
  const [busyProposal, setBusyProposal] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [bulkReason, setBulkReason] = useState("");
  const approvalByProposal = new Map(
    (approvals?.items ?? []).map((approval) => [approval.proposal_id, approval]),
  );

  async function decide(proposal: Proposal, approve: boolean): Promise<void> {
    const reason = reasonByProposal[proposal.proposal_id]?.trim();
    if (!reason) {
      setMessage("Add a decision reason before approving or rejecting.");
      return;
    }
    setBusyProposal(proposal.proposal_id);
    setMessage(null);
    try {
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
            ? "Advisory recommendation acknowledged; execution remains forbidden."
            : `Approved and ${result.execution?.status ?? "queued"}.`
          : "Proposal rejected.",
      );
      await Promise.all([
        mutate("/api/v1/admin/operation/approvals?status=pending&limit=100"),
        mutate("/api/v1/admin/operation/action-proposals?limit=100"),
        mutate("/api/v1/admin/operation/dashboard"),
      ]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Approval decision failed");
    } finally {
      setBusyProposal(null);
    }
  }

  async function bulkDecide(approve: boolean): Promise<void> {
    const selectedProposals = (proposals?.items ?? []).filter((proposal) =>
      selected.has(proposal.proposal_id),
    );
    if (!bulkReason.trim() || selectedProposals.length === 0) {
      setMessage("Select proposals and add a bulk decision reason.");
      return;
    }
    const actionTypes = new Set(selectedProposals.map((proposal) => proposal.action_type));
    if (actionTypes.size !== 1 || (approve && !actionTypes.has("decrease_budget"))) {
      setMessage("Bulk approval is limited to homogeneous budget-decrease actions.");
      return;
    }
    setBusyProposal("bulk");
    try {
      await apiPost("/api/v1/admin/operation/approvals/bulk-decision", {
        proposal_ids: selectedProposals.map((proposal) => proposal.proposal_id),
        approve,
        reason: bulkReason.trim(),
        correlation_id: crypto.randomUUID(),
      });
      setMessage(approve ? "Selected budget decreases approved." : "Selected actions rejected.");
      setSelected(new Set());
      setBulkReason("");
      await Promise.all([
        mutate("/api/v1/admin/operation/approvals?status=pending&limit=100"),
        mutate("/api/v1/admin/operation/approvals?limit=100"),
        mutate("/api/v1/admin/operation/action-proposals?limit=100"),
      ]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Bulk decision failed");
    } finally {
      setBusyProposal(null);
    }
  }

  const items = (proposals?.items ?? []).filter((proposal) =>
    proposal.status === "awaiting_approval" || proposal.status === "expired",
  );
  return (
    <>
      <PageHeader
        eyebrow="Decision queue"
        title="Approvals"
        description="Review current state, proposed change, evidence, policy, and risk before acting."
      />
      {message ? <p className="notice" role="status">{message}</p> : null}
      {items.length > 0 ? (
        <section className="panel bulk-bar" aria-label="Bulk decision">
          <label className="field">
            <span>Bulk decision reason</span>
            <input onChange={(event) => setBulkReason(event.target.value)} value={bulkReason} />
          </label>
          <span>{selected.size} selected</span>
          <button className="button secondary compact" disabled={!canDecide || busyProposal !== null || selected.size === 0} onClick={() => void bulkDecide(false)} type="button">Reject selected</button>
          <button className="button compact" disabled={!canDecide || busyProposal !== null || selected.size === 0} onClick={() => void bulkDecide(true)} type="button">Approve safe decreases</button>
        </section>
      ) : null}
      <section className="approval-grid">
        {items.map((proposal) => {
          const approval = approvalByProposal.get(proposal.proposal_id);
          const isBusy = busyProposal === proposal.proposal_id;
          const isLiveAdvisory = proposal.execution_forbidden;
          return (
            <article className="approval-card" key={proposal.proposal_id}>
              <header>
                <input
                  aria-label={`Select ${proposal.action_type} proposal`}
                  checked={selected.has(proposal.proposal_id)}
                  disabled={
                    !canDecide || proposal.status !== "awaiting_approval" || isLiveAdvisory
                  }
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
                  <h2>{proposal.action_type.replaceAll("_", " ")}</h2>
                </div>
                <StatusBadge status={proposal.status} />
              </header>
              {isLiveAdvisory ? (
                <p className="live-advisory-note">
                  <strong>LIVE META — READ-ONLY ADVISORY</strong>
                  No approve or execute control can dispatch this recommendation to Meta.
                </p>
              ) : null}
              <dl className="detail-grid">
                <div><dt>Provider object</dt><dd><code>{compactId(proposal.provider_object_id)}</code></dd></div>
                <div><dt>Confidence</dt><dd>{proposal.confidence}</dd></div>
                <div><dt>Requested by</dt><dd>{approval?.requested_by ?? "unknown"}</dd></div>
                <div><dt>Expires</dt><dd>{formatDate(proposal.expires_at)}</dd></div>
                <div><dt>Provider mode</dt><dd>{proposal.provider_mode}</dd></div>
              </dl>
              <div className="old-new-grid">
                <div><span>Current value</span><strong>{parameterValue(proposal.parameters, ["current_daily_budget", "current_status"], "See evidence")}</strong></div>
                <div><span>Proposed value</span><strong>{parameterValue(proposal.parameters, ["proposed_daily_budget", "proposed_status"], "Typed change")}</strong></div>
              </div>
              <div className="change-box">
                <span>Typed change</span>
                <pre>{JSON.stringify(proposal.parameters, null, 2)}</pre>
              </div>
              <div className="evidence-block">
                <h3>Evidence</h3>
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
                {proposal.risks.map((risk) => <li key={risk}>{risk}</li>)}
              </ul>
              {isLiveAdvisory ? (
                <div className="manual-instructions">
                  <h3>Manual Ads Manager instructions</h3>
                  <ol>
                    {(proposal.manual_action_instructions ?? []).map((instruction) => (
                      <li key={instruction}>{instruction}</li>
                    ))}
                  </ol>
                </div>
              ) : null}
              <label className="field">
                <span>Decision reason</span>
                <textarea
                  disabled={!canDecide || proposal.status !== "awaiting_approval"}
                  onChange={(event) => {
                    setReasonByProposal((current) => ({
                      ...current,
                      [proposal.proposal_id]: event.target.value,
                    }));
                  }}
                  placeholder="Explain the evidence and decision"
                  value={reasonByProposal[proposal.proposal_id] ?? ""}
                />
              </label>
              <footer>
                <button
                  className="button secondary"
                  disabled={!canDecide || isBusy || proposal.status !== "awaiting_approval"}
                  onClick={() => void decide(proposal, false)}
                  type="button"
                >
                  Reject
                </button>
                <button
                  className="button"
                  disabled={!canDecide || isBusy || proposal.status !== "awaiting_approval"}
                  onClick={() => void decide(proposal, true)}
                  type="button"
                >
                  {isBusy
                    ? "Saving…"
                    : isLiveAdvisory
                      ? "Acknowledge advisory"
                      : "Approve"}
                </button>
              </footer>
            </article>
          );
        })}
        {items.length === 0 ? (
          <div className="panel"><EmptyState title="Queue is clear" detail="No actions currently require approval." /></div>
        ) : null}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Decision history</p><h2>Completed approvals</h2></div></div>
        <div className="compact-history">
          {(approvalHistory?.items ?? []).filter((approval) => approval.status !== "pending").map((approval) => (
            <div key={approval.approval_id}><code>{compactId(approval.proposal_id)}</code><StatusBadge status={approval.status} /><time>{formatDate(approval.requested_at)}</time></div>
          ))}
          {(approvalHistory?.items ?? []).every((approval) => approval.status === "pending") ? <div className="empty-inline">No completed decisions yet.</div> : null}
        </div>
      </section>
    </>
  );
}
