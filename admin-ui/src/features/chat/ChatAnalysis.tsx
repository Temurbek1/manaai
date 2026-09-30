"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { ConfirmAction } from "@/components/ConfirmAction";
import { CHAT_BASE } from "./agents";
import { labelFor } from "@/ui/labels";
import { ChatApprovals } from "./ChatApprovals";

type AnalysisState = components["schemas"]["ChatAnalysisState"];

export function AnalysisButton({
  topicId,
  disabled,
  onDone,
}: {
  topicId: string;
  disabled: boolean;
  onDone: () => Promise<unknown>;
}): React.JSX.Element {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useRef<string | null>(null);
  async function launch(): Promise<void> {
    if (busy) return;
    setBusy(true);
    setError(null);
    id.current ??= crypto.randomUUID();
    try {
      await apiPost(`${CHAT_BASE}/topics/${topicId}/analysis`, {
        request_id: id.current,
        confirmed: true,
      });
      await onDone();
      id.current = null;
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Не удалось подтвердить запуск. Обновите переписку перед повтором.",
      );
      await onDone().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="chat-analysis-control">
      <ConfirmAction
        label="Новый анализ"
        confirmLabel="Подтвердить сбор данных"
        className="button secondary compact"
        disabled={disabled || busy || !hasRole(session, "operator")}
        description="Запустит анализ по текущей конфигурации агента. Возможны платные чтения API/Firebase в пределах серверных лимитов. Приложение, выбранное в теме, НЕ фильтрует источники. Результат не считается данными MANA или 360REC без проверенной привязки. Изменения и отправка сообщений клиентам не выполняются."
        onConfirm={() => void launch()}
      />
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export function AnalysisResult({
  topicId,
  turnId,
}: {
  topicId: string;
  turnId: string;
}): React.JSX.Element {
  const { data, error, isValidating, mutate } = useSWR<AnalysisState, Error>(
    `${CHAT_BASE}/topics/${topicId}/analysis/${turnId}`,
    {
      refreshInterval: (current) =>
        current &&
        ![
          "completed",
          "failed",
          "cancelled",
          "waiting_approval",
          "unconfirmed",
        ].includes(current.state)
          ? 5000
          : 0,
    },
  );
  return (
    <section className="chat-analysis-result" aria-label="Результат анализа">
      <strong>
        {error
          ? "Состояние недоступно"
          : data
            ? data.state === "unconfirmed"
              ? "Ожидаем подтверждение запуска"
              : labelFor(data.state)
            : "Проверяем запуск…"}
      </strong>
      {data && <p>{data.summary}</p>}
      {data?.state === "waiting_approval" && data.run_id && (
        <ChatApprovals runId={data.run_id} />
      )}
      <div>
        <button
          type="button"
          disabled={isValidating}
          onClick={() => void mutate().catch(() => undefined)}
        >
          Обновить состояние
        </button>
        {data?.run_id && (
          <Link href={`/runs?run=${encodeURIComponent(data.run_id)}`}>
            Подробности запуска ↗
          </Link>
        )}
      </div>
    </section>
  );
}
