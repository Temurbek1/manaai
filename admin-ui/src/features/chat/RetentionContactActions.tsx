"use client";

import { useRef, useState } from "react";
import useSWR from "swr";
import { ApiError, apiGet, apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { QueryState } from "@/components/QueryState";
import { useI18n } from "@/i18n/LanguageProvider";
import { ContactReviewAssignment } from "./ContactReviewAssignment";
import {
  loadPreparationAttempt,
  preparationScope,
  savePreparationAttempt,
  type PreparationAttempt,
} from "./contactPreparationAttempt";

type Page = components["schemas"]["WorkspaceContactPage"];
type Contact = components["schemas"]["WorkspaceContactView"];
type Prepare = components["schemas"]["WorkspaceContactPrepare"];

type Props = {
  topicId: string;
  turnId: string;
  onContinued?: () => Promise<unknown>;
};

export function RetentionContactActions(props: Props): React.JSX.Element {
  const { session } = useSession();
  return (
    <BoundRetentionContactActions
      key={preparationScope(session.user.user_id, props.topicId, props.turnId)}
      {...props}
    />
  );
}

function BoundRetentionContactActions({
  topicId,
  turnId,
  onContinued,
}: Props): React.JSX.Element {
  const { t } = useI18n();
  const { session } = useSession();
  const url = `/api/v1/admin/operation/workspace/topics/${encodeURIComponent(topicId)}/messages/${encodeURIComponent(turnId)}/retention-contacts`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<Page, Error>(
    url,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
    },
  );
  const [recipient, setRecipient] = useState<Prepare["recipient"]>("sample_ru");
  const [template, setTemplate] =
    useState<Prepare["template"]>("onboarding_help");
  const scope = preparationScope(session.user.user_id, topicId, turnId);
  const [initial] = useState(() => {
    try {
      return { attempt: loadPreparationAttempt(scope), blocked: false };
    } catch {
      return { attempt: null, blocked: true };
    }
  });
  const [attempt, setAttempt] = useState<PreparationAttempt | null>(
    initial.attempt,
  );
  const [storageBlocked, setStorageBlocked] = useState(initial.blocked);
  const [admissionChecked, setAdmissionChecked] = useState(false);
  const [checking, setChecking] = useState(false);
  const [observed, setObserved] = useState<Contact | null>(null);
  const canPrepare =
    !storageBlocked &&
    !checking &&
    !error &&
    data?.items.length === 0 &&
    !observed &&
    data?.preparation_availability?.state === "requires_confirmation" &&
    (!attempt || (attempt.state === "refused" && admissionChecked)) &&
    hasRole(session, "operator");
  const attempted = attempt !== null || storageBlocked;
  const guard = useRef(false);
  const [notice, setNotice] = useState<string | null>(null);
  const continueGuard = useRef(false);
  const [continueAttempted, setContinueAttempted] = useState(false);
  function retain(next: PreparationAttempt): void {
    try {
      savePreparationAttempt(next);
      setAttempt(next);
    } catch {
      setStorageBlocked(true);
      throw Error("Preparation recovery storage unavailable");
    }
  }
  function matches(action: Contact, request: Prepare): boolean {
    return (
      action.topic_id === topicId &&
      action.turn_id === turnId &&
      action.recipient === request.recipient &&
      action.message?.template === request.template &&
      action.product === "mana" &&
      action.synthetic === true &&
      action.provider === "fake_retention_contact"
    );
  }
  async function observePreparation(): Promise<void> {
    if (checking) return;
    setChecking(true);
    setAdmissionChecked(false);
    try {
      if (attempt) {
        const result = await apiGet<
          components["schemas"]["WorkspacePreparationObservation"]
        >(
          `${url}/preparation?request_id=${encodeURIComponent(attempt.request.request_id)}`,
        );
        if (result.request_id !== attempt.request.request_id)
          throw Error("Wrong request receipt");
        if (
          result.state === "recorded" &&
          result.action &&
          matches(result.action, attempt.request)
        ) {
          retain({ ...attempt, state: "recorded" });
          setObserved(result.action);
        } else if (result.state !== "absent" && result.state !== "pending")
          throw Error("Invalid preparation observation");
        // An absent SQL row cannot prove a delayed POST will not arrive later.
        // Only a closed refusal of this exact request permits human re-admission.
        if (result.state === "pending" && attempt.state === "refused")
          retain({ ...attempt, state: "unknown" });
      }
      const fresh = await mutate();
      if (fresh?.preparation_availability?.state === "requires_confirmation")
        setAdmissionChecked(true);
      setNotice(null);
    } catch {
      setNotice("Статус недоступен. Повтор не отправлен.");
    } finally {
      setChecking(false);
    }
  }
  async function continueWithAgent(): Promise<void> {
    const action = data?.items[0];
    if (
      !action ||
      !data?.continuation_available ||
      continueGuard.current ||
      !hasRole(session, "operator")
    )
      return;
    continueGuard.current = true;
    setContinueAttempted(true);
    try {
      await apiPost<components["schemas"]["ChatTurn"]>(`${url}/continue`, {
        request_id: crypto.randomUUID(),
        confirmed: true,
        action_id: action.action_id,
        action_fingerprint: action.fingerprint,
        revision: action.revision,
      });
    } catch {
      setNotice("Ответ не подтверждён. Повтор не отправлен. Обновите статус.");
    } finally {
      await mutate().catch(() =>
        setNotice("Статус недоступен. Повтор не отправлен."),
      );
      await onContinued?.().catch(() =>
        setNotice("Статус недоступен. Повтор не отправлен."),
      );
    }
  }
  async function prepare(): Promise<void> {
    if (guard.current || !canPrepare || !data) return;
    guard.current = true;
    setAdmissionChecked(false);
    let pending: PreparationAttempt | null = null;
    try {
      const request: Prepare = attempt?.request ?? {
        request_id: crypto.randomUUID(),
        confirmed: true,
        recipient: data.preparation_request?.recipient ?? recipient,
        template: data.preparation_request?.template ?? template,
        ...(data.preparation_request
          ? {
              selection_fingerprint:
                data.preparation_request.selection_fingerprint,
            }
          : {}),
      };
      pending = { version: 1, scope, request, state: "unknown" };
      retain(pending);
      const saved = await apiPost<Contact>(`${url}/prepare`, request);
      if (!matches(saved, request)) throw Error("Wrong preparation receipt");
      retain({ ...pending, state: "recorded" });
      setObserved(saved);
      setNotice(null);
    } catch (failure) {
      if (
        pending &&
        failure instanceof ApiError &&
        [
          "contact_preparation_stopped",
          "contact_preparation_limit",
          "contact_preparation_history_unavailable",
        ].includes(failure.code ?? "")
      ) {
        try {
          retain({ ...pending, state: "refused" });
        } catch {
          /* Keep fail-closed storage state. */
        }
        setNotice(failure.message);
      } else
        setNotice(
          "Ответ не подтверждён. Повтор не отправлен. Обновите статус.",
        );
    } finally {
      guard.current = false;
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
              {data.preparation_request ? (
                <p>
                  {t("Агент выбрал тестовое действие")} ·{" "}
                  {data.preparation_request.recipient === "sample_uz"
                    ? "UZ"
                    : "RU"}{" "}
                  ·{" "}
                  {t(
                    data.preparation_request.template === "renewal_reminder"
                      ? "Напоминание о сроке доступа"
                      : "Помощь с настройкой",
                  )}
                </p>
              ) : (
                <>
                  <label>
                    {t("Вымышленный получатель")}
                    <select
                      aria-label={t("Вымышленный получатель")}
                      value={attempt?.request.recipient ?? recipient}
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
                          {t("Взрослый · {0}", {
                            0: item.language.toUpperCase(),
                          })}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("Шаблон сообщения")}
                    <select
                      value={attempt?.request.template ?? template}
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
                </>
              )}
              <ConfirmAction
                className="button secondary compact"
                label={t("Подготовить тестовое сообщение")}
                confirmLabel={t("Подтвердить подготовку")}
                disabled={!canPrepare}
                onConfirm={() => void prepare()}
                description={t(
                  "Подготовка сохраняет проект сообщения. Отправка требует отдельного решения.",
                )}
              />
            </>
          )}
          {(observed &&
          !data.items.some((item) => item.action_id === observed.action_id)
            ? [observed, ...data.items]
            : data.items
          ).map((item) => (
            <RetentionContactCard
              key={item.action_id}
              action={item}
              url={url}
              refresh={() => mutate()}
              peerReviewsEnabled={data.peer_reviews_enabled}
            />
          ))}
          {data.more_omitted && (
            <p>
              {t("Показаны только три предложения из ограниченной выборки.")}
            </p>
          )}
          {data.continuation_available && (
            <button
              type="button"
              className="button secondary compact"
              disabled={continueAttempted || !hasRole(session, "operator")}
              onClick={() => void continueWithAgent()}
            >
              {t("Продолжить с агентом")}
            </button>
          )}
          {data.continuation && (
            <p role="status">
              <a href={`#turn-${data.continuation.turn_id}`}>
                {t("Продолжение в чате")}
              </a>
            </p>
          )}
        </>
      )}
      {storageBlocked && (
        <p role="status">
          {t(
            "Не удалось сохранить запрос подготовки. Подготовка заблокирована.",
          )}
        </p>
      )}
      {attempt?.state === "unknown" && (
        <p role="status">
          {t("Результат подготовки неизвестен. Новый запрос не отправляется.")}
        </p>
      )}
      {attempt?.state === "refused" && (
        <p role="status">
          {t(
            "Подготовка отклонена до чтения. Проверьте статус перед новым подтверждением.",
          )}
        </p>
      )}
      {data?.preparation_availability?.state === "stopped" && (
        <p role="status">
          {t(
            "Подготовка остановлена. Снятие остановки не подтверждает действие.",
          )}
        </p>
      )}
      {data?.preparation_availability?.state === "pending" && (
        <p role="status">
          {t("Подготовка уже начата. Повторное чтение запрещено.")}
        </p>
      )}
      <button
        type="button"
        className="button secondary compact"
        disabled={checking || isValidating}
        onClick={() => void observePreparation()}
      >
        {t("Проверить подготовку")}
      </button>
      {notice && <p role="status">{t(notice)}</p>}
    </section>
  );
}

export function RetentionContactCard({
  action,
  url,
  refresh,
  peerReviewsEnabled = false,
}: {
  action: Contact;
  url: string;
  refresh: () => Promise<unknown>;
  peerReviewsEnabled?: boolean;
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
          {peerReviewsEnabled && (
            <ContactReviewAssignment action={action} url={url} />
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
