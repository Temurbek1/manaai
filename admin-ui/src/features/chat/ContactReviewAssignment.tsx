"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { QueryState } from "@/components/QueryState";
import { useI18n } from "@/i18n/LanguageProvider";

type Action = components["schemas"]["WorkspaceContactView"];
type Options = components["schemas"]["ContactReviewOptions"];

export function ContactReviewAssignment({
  action,
  url,
}: {
  action: Action;
  url: string;
}): React.JSX.Element {
  const { t } = useI18n();
  const { session } = useSession();
  const endpoint = `${url}/${encodeURIComponent(action.action_id)}/review`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    Options,
    Error
  >(endpoint);
  const [reviewer, setReviewer] = useState("");
  const [attempted, setAttempted] = useState({ share: false, revoke: false });
  const [notice, setNotice] = useState<string | null>(null);
  const guard = useRef({ share: false, revoke: false });
  async function submit(revoke: boolean): Promise<void> {
    const kind = revoke ? "revoke" : "share";
    if (guard.current[kind] || !data || !hasRole(session, "operator")) return;
    guard.current[kind] = true;
    setAttempted((current) => ({ ...current, [kind]: true }));
    try {
      await apiPost(
        endpoint + (revoke ? "/revoke" : ""),
        revoke
          ? { confirmed: true, fingerprint: action.fingerprint }
          : {
              request_id: crypto.randomUUID(),
              confirmed: true,
              reviewer_id: reviewer,
              fingerprint: action.fingerprint,
            },
      );
    } catch {
      setNotice("Ответ не подтверждён. Повтор не отправлен. Обновите статус.");
    } finally {
      await mutate().catch(() =>
        setNotice("Статус недоступен. Повтор не отправлен."),
      );
    }
  }
  return (
    <section aria-label={t("Передать на согласование")}>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={() => mutate()}
        subject={t("согласование")}
      />
      {data &&
        !error &&
        (data.review ? (
          <>
            <p>{data.review.reviewer.label}</p>
            {data.review.revoked ? (
              <p>{t("Доступ к согласованию отозван.")}</p>
            ) : (
              <>
                <Link
                  href={`/reviews?review=${encodeURIComponent(data.review.review_id)}`}
                >
                  {t("Ссылка для выбранного сотрудника")}
                </Link>
                <ConfirmAction
                  className="button secondary compact"
                  label={t("Отозвать доступ")}
                  confirmLabel={t("Подтвердить отзыв")}
                  disabled={attempted.revoke || !hasRole(session, "operator")}
                  onConfirm={() => void submit(true)}
                  description={t(
                    "Отозвать только это согласование до принятия решения.",
                  )}
                />
              </>
            )}
          </>
        ) : (
          <>
            <label>
              {t("Согласующий сотрудник")}
              <select
                value={reviewer}
                disabled={attempted.share || !hasRole(session, "operator")}
                onChange={(event) => setReviewer(event.target.value)}
              >
                <option value="">{t("Выберите сотрудника")}</option>
                {data.reviewers.map((item) => (
                  <option key={item.user_id} value={item.user_id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <ConfirmAction
              className="button secondary compact"
              label={t("Передать на согласование")}
              confirmLabel={t("Подтвердить передачу")}
              disabled={
                attempted.share || !reviewer || !hasRole(session, "operator")
              }
              onConfirm={() => void submit(false)}
              description={t(
                "Показать выбранному сотруднику только это тестовое сообщение. Переписка и данные не открываются.",
              )}
            />
            {data.more_omitted && (
              <p>{t("Показаны только первые 20 сотрудников.")}</p>
            )}
          </>
        ))}
      {notice && <p role="status">{t(notice)}</p>}
    </section>
  );
}
