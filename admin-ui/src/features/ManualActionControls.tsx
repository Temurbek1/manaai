"use client";

import { useState } from "react";
import useSWR from "swr";
import { apiPut } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession, hasRole } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { useI18n } from "@/i18n/LanguageProvider";
import type { ChatViewAvailability } from "@/features/chat/contracts";

type ControlPage = components["schemas"]["ManualActionControlPage"];
type Control = components["schemas"]["ManualActionControlView"];
const CONTROL_URL =
  "/api/v1/admin/operation/workspace/manual-action-controls?agent_id=retention-agent";

export function ManualActionControls(): React.JSX.Element | null {
  const { t } = useI18n();
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const { data: availability } = useSWR<ChatViewAvailability>(
    "/api/v1/admin/operation/chat/availability",
    { refreshInterval: 0, revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const { data, error, isValidating, mutate } = useSWR<ControlPage, Error>(
    availability?.retention_contact_reviews_enabled ? CONTROL_URL : null,
    {
      refreshInterval: 0,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
    },
  );
  const control = data?.items?.find(
    (item) =>
      item.definition.agent_id === "retention-agent" &&
      item.definition.capability_key === "retention.contact.sandbox" &&
      item.definition.product === "mana" &&
      item.definition.provider === "fake_retention_contact" &&
      item.definition.execution_mode === "human_review_sandbox" &&
      typeof item.capability_kill_switch === "boolean" &&
      typeof item.agent_kill_switch === "boolean" &&
      typeof item.global_kill_switch === "boolean",
  );

  async function change(current: Control): Promise<void> {
    if (busy || unknown || error || isValidating || !hasRole(session, "admin"))
      return;
    setBusy(true);
    try {
      await apiPut<Control>(
        "/api/v1/admin/operation/workspace/manual-action-controls/retention-agent/retention.contact.sandbox",
        { confirmed: true, enabled: !current.capability_kill_switch },
      );
      await mutate();
    } catch {
      // A lost acknowledgement is observation-only, never a repeated PUT.
      setUnknown(true);
    } finally {
      setBusy(false);
    }
  }

  async function observe(): Promise<void> {
    try {
      const result = await mutate();
      if (result) setUnknown(false);
    } catch {
      setUnknown(true);
    }
  }

  if (!availability?.retention_contact_reviews_enabled) return null;
  return (
    <section aria-labelledby="manual-action-controls-title">
      <h3 id="manual-action-controls-title">
        {t("Ручные действия Retention")}
      </h3>
      <p className="muted">
        {t(
          "Контактный sandbox MANA: только вымышленные взрослые и fake-получатель. Без расписания.",
        )}
      </p>
      {error || unknown ? (
        <p role="alert" className="notice notice-warning">
          {t(
            "Состояние остановки требует проверки. Повторное изменение заблокировано.",
          )}
        </p>
      ) : null}
      {control ? (
        <>
          <p>
            {t(
              control.capability_kill_switch
                ? "Остановка включена"
                : "Остановка снята",
            )}
          </p>
          {control.agent_kill_switch || control.global_kill_switch ? (
            <p className="notice">
              {t(
                "Дополнительно действует остановка агента или всей платформы.",
              )}
            </p>
          ) : null}
          <div className="button-row">
            <ConfirmAction
              className={
                control.capability_kill_switch
                  ? "button secondary"
                  : "button danger"
              }
              label={t(
                control.capability_kill_switch
                  ? "Снять остановку sandbox"
                  : "Остановить sandbox",
              )}
              confirmLabel={t(
                control.capability_kill_switch
                  ? "Подтвердить возобновление"
                  : "Подтвердить остановку",
              )}
              description={t(
                "Меняется только остановка этой возможности. Это не согласование и не отправка сообщения; остальные проверки остаются обязательными.",
              )}
              disabled={
                !hasRole(session, "admin") ||
                busy ||
                unknown ||
                Boolean(error) ||
                isValidating
              }
              onConfirm={() => void change(control)}
            />
            <button
              className="button secondary"
              type="button"
              disabled={busy || isValidating}
              onClick={() => void observe()}
            >
              {t("Проверить состояние")}
            </button>
          </div>
        </>
      ) : (
        <p className="muted">{t("Управление ручным действием недоступно.")}</p>
      )}
    </section>
  );
}
