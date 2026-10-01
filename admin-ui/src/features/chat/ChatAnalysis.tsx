"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import useSWR from "swr";
import { apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { hasRole, useSession } from "@/auth/SessionContext";
import { CHAT_BASE } from "./agents";
import { labelFor } from "@/ui/labels";
import { ChatApprovals } from "./ChatApprovals";

type AnalysisState = components["schemas"]["ChatAnalysisState"];

export function AnalysisButton({
  topicId,
  disabled,
  onDone,
  kind = "default",
}: {
  topicId: string;
  disabled: boolean;
  onDone: () => Promise<unknown>;
  kind?: "default" | "mana_parents";
}): React.JSX.Element {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useRef<string | null>(null);
  const guard = useRef(false);
  async function launch(): Promise<void> {
    if (guard.current || submitted || disabled || !hasRole(session, "operator"))
      return;
    guard.current = true;
    setBusy(true);
    setError(null);
    id.current ??= crypto.randomUUID();
    try {
      await apiPost(`${CHAT_BASE}/topics/${topicId}/analysis`, {
        request_id: id.current,
        confirmed: true,
        // Keep the default request compatible with the unchanged production chat API.
        ...(kind === "mana_parents" ? { kind } : {}),
      });
      setSubmitted(true);
      await onDone().catch(() => {
        setError(
          "Запрос принят. Не запускайте повторно: обновите переписку, чтобы увидеть результат.",
        );
      });
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Не удалось подтвердить запуск. Обновите переписку перед повтором.",
      );
      await onDone().catch(() => undefined);
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="chat-action-suggestion"
      aria-label="Предлагаемый следующий шаг"
    >
      <strong>
        {kind === "mana_parents"
          ? "Проверить родителей MANA?"
          : "Собрать свежие данные?"}
      </strong>
      <p>
        {kind === "mana_parents"
          ? "Одна ограниченная страница родителей MANA, не чаще раза в 6 часов. Firebase не вызывается, данные не изменяются. Тариф может быть бесплатным — это не отчёт о выручке."
          : "Обращусь к настроенным источникам агента. Возможны платные чтения API/Firebase в пределах серверных лимитов. Выбор приложения в теме НЕ фильтрует источники. Изменений данных и сообщений клиентам не будет."}
      </p>
      <button
        type="button"
        className="button secondary compact"
        disabled={
          disabled || busy || submitted || !hasRole(session, "operator")
        }
        onClick={() => void launch()}
      >
        {submitted
          ? "Запрос принят"
          : busy
            ? "Отправляем подтверждение…"
            : "Подтвердить сбор данных"}
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export function AnalysisResult({
  topicId,
  turnId,
}: {
  topicId: string;
  turnId: string;
}): React.JSX.Element {
  const [startedAt] = useState(() => Date.now());
  const { data, error, isValidating, mutate } = useSWR<AnalysisState, Error>(
    `${CHAT_BASE}/topics/${topicId}/analysis/${turnId}`,
    {
      refreshInterval: (current) => {
        if (!current || current.state === "unconfirmed") {
          // Poll saved state briefly, never resubmit an uncertain source read.
          return Date.now() - startedAt < 60_000 ? 5000 : 0;
        }
        return [
          "completed",
          "failed",
          "cancelled",
          "waiting_approval",
        ].includes(current.state)
          ? 0
          : 5000;
      },
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
      <details className="chat-result-details">
        <summary>Подробности запуска</summary>
        {(error || data?.state === "unconfirmed") && (
          <button
            type="button"
            disabled={isValidating}
            onClick={() => void mutate().catch(() => undefined)}
          >
            Обновить состояние
          </button>
        )}
        {data?.run_id && (
          <Link href={`/runs?run=${encodeURIComponent(data.run_id)}`}>
            Открыть журнал ↗
          </Link>
        )}
      </details>
    </section>
  );
}
