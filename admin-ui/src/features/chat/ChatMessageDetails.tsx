"use client";

import Link from "next/link";
import { useState } from "react";
import type { ChatViewTurn } from "./contracts";
import { formatDate } from "@/ui/format";

export function ChatMessageDetails({
  turn,
}: {
  turn: ChatViewTurn;
}): React.JSX.Element {
  const [notice, setNotice] = useState("");
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setNotice("Ответ скопирован");
    } catch {
      setNotice("Не удалось скопировать. Выделите текст вручную.");
    }
  }
  return (
    <details className="chat-message-details">
      <summary>
        Детали ответа
        {turn.sources?.length ? ` · ${turn.sources.length} ист.` : ""}
      </summary>
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
          <p>
            Сохранённые отчёты, не свежий сбор. Привязка к приложению
            подтверждена только у источников с отдельной отметкой MANA.
          </p>
          {turn.sources?.map((source) => (
            <Link
              key={source.report_id}
              href={`/runs?run=${encodeURIComponent(source.run_id)}`}
            >
              {source.title} · {formatDate(source.created_at)} ·{" "}
              {source.scope_verified && source.product === "mana"
                ? "Только MANA"
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
  );
}
