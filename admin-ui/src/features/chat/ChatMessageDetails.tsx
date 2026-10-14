"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChatViewTurn } from "./contracts";
import {
  evidenceCollectionLabel,
  evidenceState,
  evidenceStateLabel,
} from "./evidenceDisplay";

export function ChatMessageDetails({
  turn,
}: {
  turn: ChatViewTurn;
}): React.JSX.Element {
  const { t, locale } = useI18n();

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
      ? [t("Есть устаревшие данные — только для исторического разбора.")]
      : []),
    ...(states.includes("unknown")
      ? [t("Свежесть части данных не подтверждена.")]
      : []),
    ...(turn.sources?.some(
      (source) => !source.scope_verified || !source.product,
    )
      ? [t("Приложение источника не подтверждено.")]
      : []),
  ];
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setNotice(t("Ответ скопирован"));
    } catch {
      setNotice(t("Не удалось скопировать. Выделите текст вручную."));
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
          {t("Детали ответа")}{" "}
          {turn.sources?.length
            ? t(" · {0} ист.", { "0": turn.sources.length })
            : ""}
        </summary>
        {turn.model && (
          <p>
            {turn.model} · {turn.reasoning ?? "auto"}
          </p>
        )}
        {Boolean(turn.plan?.length) && (
          <div className="chat-plan">
            <strong>{t("План работы")}</strong>
            <ol>
              {turn.plan?.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          </div>
        )}
        {Boolean(turn.sources?.length) && (
          <div className="chat-sources">
            <p>{t("Сохранённые отчёты, без нового сбора.")}</p>
            {turn.sources?.map((source) => (
              <Link
                key={source.report_id}
                href={`/runs?run=${encodeURIComponent(source.run_id)}`}
              >
                {source.title} ·{" "}
                {evidenceCollectionLabel(source.collected_at, locale)} ·{" "}
                {t(evidenceStateLabel(evidenceState(source, now)))} ·{" "}
                {source.scope_verified && source.product
                  ? t("Только {0}", {
                      "0": source.product === "mana" ? "MANA" : "360REC",
                    })
                  : t("Приложение не подтверждено")}{" "}
                ↗
              </Link>
            ))}
          </div>
        )}
        <button
          className="copy-answer"
          type="button"
          onClick={() => void copy()}
          aria-label={t("Скопировать ответ")}
        >
          {t("Копировать")}{" "}
        </button>
        <span role="status">{t(notice)}</span>
      </details>
    </>
  );
}
