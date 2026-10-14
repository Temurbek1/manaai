"use client";

import { useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { QueryState } from "@/components/QueryState";
import { useI18n } from "@/i18n/LanguageProvider";

type Page = components["schemas"]["WorkspaceContactPage"];
type Contact = components["schemas"]["WorkspaceContactView"];
type Prepare = components["schemas"]["WorkspaceContactPrepare"];

export function RetentionContactActions({
  topicId,
  turnId,
}: {
  topicId: string;
  turnId: string;
}): React.JSX.Element {
  const { t } = useI18n();
  const { session } = useSession();
  const url = `/api/v1/admin/operation/workspace/topics/${encodeURIComponent(topicId)}/messages/${encodeURIComponent(turnId)}/retention-contacts`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<Page, Error>(
    url,
  );
  const [recipient, setRecipient] = useState<Prepare["recipient"]>("sample_ru");
  const [template, setTemplate] =
    useState<Prepare["template"]>("onboarding_help");
  const [attempted, setAttempted] = useState(false);
  const guard = useRef(false);
  const [notice, setNotice] = useState<string | null>(null);
  async function prepare(): Promise<void> {
    if (guard.current || !hasRole(session, "operator") || !data) return;
    guard.current = true;
    setAttempted(true);
    try {
      await apiPost<Contact>(`${url}/prepare`, {
        request_id: crypto.randomUUID(),
        confirmed: true,
        recipient,
        template,
      });
    } catch {
      setNotice("Ответ не подтверждён. Повтор не отправлен. Обновите статус.");
    } finally {
      await mutate().catch(() =>
        setNotice("Статус недоступен. Повтор не отправлен."),
      );
    }
  }
  return (
    <section
      className="chat-approvals"
      aria-label={t("Контактный sandbox Retention")}
    >
      <h3>{t("Контактный sandbox Retention")}</h3>
      <p>
        {t(
          "Только вымышленные взрослые. Реальные родители не получают сообщений.",
        )}
      </p>
      <QueryState
        error={error}
        loading={isLoading}
        hasData={Boolean(data)}
        retrying={isValidating}
        onRetry={() => mutate()}
        subject={t("действия")}
      />
      {data && !error && (
        <>
          {data.items.length === 0 && (
            <>
              <label>
                {t("Вымышленный получатель")}
                <select
                  aria-label={t("Вымышленный получатель")}
                  value={recipient}
                  disabled={attempted || !hasRole(session, "operator")}
                  onChange={(event) =>
                    setRecipient(
                      event.target.value === "sample_uz"
                        ? "sample_uz"
                        : "sample_ru",
                    )
                  }
                >
                  {data.recipients.map((item) => (
                    <option key={item.key} value={item.key}>
                      {t("Взрослый · {0}", { 0: item.language.toUpperCase() })}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("Шаблон сообщения")}
                <select
                  value={template}
                  disabled={attempted || !hasRole(session, "operator")}
                  onChange={(event) =>
                    setTemplate(
                      event.target.value === "renewal_reminder"
                        ? "renewal_reminder"
                        : "onboarding_help",
                    )
                  }
                >
                  <option value="onboarding_help">
                    {t("Помощь с настройкой")}
                  </option>
                  <option value="renewal_reminder">
                    {t("Напоминание о сроке доступа")}
                  </option>
                </select>
              </label>
              <ConfirmAction
                className="button secondary compact"
                label={t("Подготовить тестовое сообщение")}
                confirmLabel={t("Подтвердить подготовку")}
                disabled={attempted || !hasRole(session, "operator")}
                onConfirm={() => void prepare()}
                description={t(
                  "Подготовка сохраняет проект сообщения. Отправка требует отдельного решения.",
                )}
              />
            </>
          )}
          {data.items.map((item) => (
            <ContactCard
              key={item.action_id}
              action={item}
              url={url}
              refresh={() => mutate()}
            />
          ))}
          {data.more_omitted && (
            <p>
              {t("Показаны только три предложения из ограниченной выборки.")}
            </p>
          )}
        </>
      )}
      {notice && <p role="status">{t(notice)}</p>}
    </section>
  );
}

function ContactCard({
  action,
  url,
  refresh,
}: {
  action: Contact;
  url: string;
  refresh: () => Promise<unknown>;
}): React.JSX.Element {
  const { t } = useI18n();
  const { session } = useSession();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const guard = useRef(false);
  const observing = useRef(false);
  const disabled =
    busy ||
    attempted ||
    action.decision_recorded ||
    action.status !== "proposed" ||
    !hasRole(session, "approver") ||
    !reason.trim();
  async function decide(approve: boolean): Promise<void> {
    if (
      guard.current ||
      disabled ||
      (approve && action.self_approval_forbidden)
    )
      return;
    guard.current = true;
    setAttempted(true);
    setBusy(true);
    try {
      await apiPost<Contact>(
        `${url}/${encodeURIComponent(action.action_id)}/decision`,
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
      await refresh().catch(() =>
        setNotice("Статус недоступен. Повтор не отправлен."),
      );
      setBusy(false);
    }
  }
  async function reconcile(): Promise<void> {
    if (observing.current || busy || !hasRole(session, "approver")) return;
    observing.current = true;
    setBusy(true);
    try {
      await apiPost<Contact>(
        `${url}/${encodeURIComponent(action.action_id)}/reconcile`,
        { confirmed: true, fingerprint: action.fingerprint },
      );
    } catch {
      setNotice("Статус недоступен. Повтор не отправлен.");
    } finally {
      await refresh().catch(() => undefined);
      observing.current = false;
      setBusy(false);
    }
  }
  const statuses: Record<Contact["status"], string> = {
    proposed: "Ожидает согласования",
    rejected: "Отклонено",
    dispatching: "Выполняется",
    verified: "Принято тестовым получателем",
    uncertain: "Результат неизвестен",
    refused: "Контакт запрещён проверками",
  };
  return (
    <article className="chat-proposal-card">
      <strong>{t(statuses[action.status])}</strong>
      <p>
        {t("Вымышленный получатель")} · {action.message.language.toUpperCase()}
      </p>
      <blockquote lang={action.message.language}>
        {action.message.text}
      </blockquote>
      <p>{t("Реальная доставка и влияние на удержание не измерены.")}</p>
      {action.status === "proposed" && (
        <>
          {action.self_approval_forbidden && (
            <p>{t("Решение должен принять другой сотрудник.")}</p>
          )}
          <label>
            {t("Причина решения")}
            <textarea
              value={reason}
              maxLength={1000}
              disabled={busy || attempted || !hasRole(session, "approver")}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <ConfirmAction
            className="button secondary compact"
            label={t("Отправить в sandbox")}
            confirmLabel={t("Подтвердить тестовую отправку")}
            disabled={disabled || action.self_approval_forbidden}
            onConfirm={() => void decide(true)}
            description={t(
              "Отправить показанный текст только вымышленному получателю. Реальных сообщений не будет.",
            )}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => void decide(false)}
          >
            {t("Отклонить")}
          </button>
        </>
      )}
      {["uncertain", "dispatching"].includes(action.status) && (
        <ConfirmAction
          className="button secondary compact"
          label={t("Проверить квитанцию")}
          confirmLabel={t("Подтвердить проверку квитанции")}
          disabled={busy || !hasRole(session, "approver")}
          onConfirm={() => void reconcile()}
          description={t(
            "Проверка читает квитанцию. Повторной отправки не будет.",
          )}
        />
      )}
      <details>
        <summary>{t("Параметры и результат")}</summary>
        <p>{action.result_code}</p>
        <p>{action.policy_reasons.join("; ")}</p>
        <p>{action.message.version}</p>
      </details>
      {notice && <p role="status">{t(notice)}</p>}
    </article>
  );
}
