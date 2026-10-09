"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChatViewTurn } from "./contracts";
import { formatDate } from "@/ui/format";

function evidenceState(
  source: NonNullable<ChatViewTurn["sources"]>[number],
  now: number,
): "stale" | "unknown" | "recent" {
  if (source.refresh_status === "stale") return "stale";
  const collected = Date.parse(source.collected_at ?? "");
  const expires = Date.parse(source.fresh_until ?? "");
  if (
    !["live", "cached"].includes(source.refresh_status ?? "") ||
    !Number.isFinite(collected) ||
    !Number.isFinite(expires) ||
    collected > now ||
    expires <= collected
  )
    return "unknown";
  // Display only: the server independently validates freshness before actions.
  return expires <= now ? "stale" : "recent";
}

export function ChatMessageDetails({
  turn,
}: {
  turn: ChatViewTurn;
}): React.JSX.Element {
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const expiries = (turn.sources ?? [])
      .filter((source) => evidenceState(source, now) === "recent")
      .map((source) => Date.parse(source.fresh_until ?? ""));
    if (!expiries.length) return;
    // Local display update only, never a data/model poll or action admission.
    const delay = Math.min(
      2_147_483_647,
      Math.max(0, Math.min(...expiries) - Date.now()),
    );
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [now, turn.sources]);
  const states =
    turn.sources?.map((source) => evidenceState(source, now)) ?? [];
  const warnings = [
    ...(states.includes("stale")
      ? ["Есть устаревшие данные — только для исторического разбора."]
      : []),
    ...(states.includes("unknown")
      ? ["Свежесть части данных не подтверждена."]
      : []),
    ...(turn.sources?.some(
      (source) => !source.scope_verified || !source.product,
    )
      ? ["Приложение источника не подтверждено."]
      : []),
  ];
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setNotice("Ответ скопирован");
    } catch {
      setNotice("Не удалось скопировать. Выделите текст вручную.");
    }
  }
  return (
    <>
      {warnings.length > 0 && (
        <p className="chat-evidence-warning" role="note">
          {warnings.join(" ")}
        </p>
      )}
      <details className="chat-message-details">
        <summary>
          Детали ответа
          {turn.sources?.length ? ` · ${turn.sources.length} ист.` : ""}
        </summary>
        {turn.model && (
          <p>
            {turn.model} · {turn.reasoning ?? "auto"}
          </p>
        )}
        {Boolean(turn.plan?.length) && (
          <div className="chat-plan">
            <strong>План работы</strong>
            <ol>
              {turn.plan?.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          </div>
        )}
        {Boolean(turn.sources?.length) && (
          <div className="chat-sources">
            <p>Сохранённые отчёты, без нового сбора.</p>
            {turn.sources?.map((source) => (
              <Link
                key={source.report_id}
                href={`/runs?run=${encodeURIComponent(source.run_id)}`}
              >
                {source.title} ·{" "}
                {source.collected_at
                  ? `Данные: ${formatDate(source.collected_at)}`
                  : "Дата сбора неизвестна"}{" "}
                · {source.refresh_status === "stale" ? "Устаревшие · " : ""}
                {source.scope_verified && source.product
                  ? `Только ${source.product === "mana" ? "MANA" : "360REC"}`
                  : "Приложение не подтверждено"}{" "}
                ↗
              </Link>
            ))}
          </div>
        )}
        <button
          className="copy-answer"
          type="button"
          onClick={() => void copy()}
          aria-label="Скопировать ответ"
        >
          Копировать
        </button>
        <span role="status">{notice}</span>
      </details>
    </>
  );
}
