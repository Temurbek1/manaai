"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import Link from "next/link";
import useSWR from "swr";
import { type ProposalPage } from "@/api/client";
import { QueryState } from "@/components/QueryState";
import { labelFor } from "@/ui/labels";

// Historical proposals have no verified application binding. This lane is read-only.
export function ChatApprovals({
  runId,
}: {
  runId?: string | undefined;
}): React.JSX.Element {
  const { t } = useI18n();

  const query = new URLSearchParams({ limit: "20" });
  if (runId) query.set("run_id", runId);
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    ProposalPage,
    Error
  >(`/api/v1/admin/operation/action-proposals?${query.toString()}`);
  const proposals = (data?.items ?? [])
    .filter((item) =>
      ["growth-agent", "marketing-agent"].includes(item.agent_id),
    )
    .slice(0, 3);
  return (
    <section className="chat-approvals" aria-label={t("Предложения агента")}>
      <h3>{t("Предложения агента")}</h3>
      <p>
        {t(
          "Привязка к MANA / 360REC не подтверждена. Согласование в этом чате недоступно.",
        )}{" "}
      </p>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={() => mutate()}
        subject={t("предложения")}
      />
      {!error && data && proposals.length === 0 && (
        <p>{t("В сохранённой выборке предложений нет.")}</p>
      )}
      {!error &&
        proposals.map((proposal) => (
          <article key={proposal.proposal_id} className="chat-proposal-card">
            <header>
              <strong>{t(labelFor(proposal.action_type))}</strong>
              <span>{t(labelFor(proposal.status))}</span>
            </header>
            <p>{proposal.reasoning}</p>
            {proposal.execution_forbidden && (
              <p>{t("Только рекомендация: изменения в Meta запрещены.")}</p>
            )}
          </article>
        ))}
      <Link href="/approvals">
        {t("Профессиональная очередь согласований ↗")}
      </Link>
    </section>
  );
}
